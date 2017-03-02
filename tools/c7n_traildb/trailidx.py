from collections import defaultdict
import datetime
import logging
import os
import subprocess
import tempfile
import time

import boto3
from botocore.exceptions import ClientError
import click
from concurrent.futures import ProcessPoolExecutor, as_completed
from dateutil.parser import parse as parse_date
import jsonschema
from influxdb import InfluxDBClient
import sqlalchemy as rdb
import yaml


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s: %(name)s:%(levelname)s %(message)s")

#  logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
logging.getLogger('requests').setLevel(logging.INFO)
logging.getLogger('s3transfer').setLevel(logging.INFO)
logging.getLogger('botocore.vendored').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.INFO)

log = logging.getLogger('trailidx')

CONFIG_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'key_template': {'type': 'string'},
        'influx': {
            'type': 'object',
            'properties': {
                'db': {'type': 'string'},
                'host': {'type': 'string'},
                'user': {'type': 'string'},
                'password': {'type': 'string'},
            }
        },
        'accounts': {
            'type': 'array',
            'items': {
                'type': {
                    'type': 'object',
                    'required': ['name', 'bucket', 'regions', 'title'],
                    'properties': {
                        'name': {'type': 'string'},
                        'title': {'type': 'string'},
                        'bucket': {'type': 'string'},
                        'regions': {'type': 'array', 'items': {'type': 'string'}}
                        }
                }
            }
        }
    }
}


def process_traildb(db, influx, account_name, region, since=None):
    md = rdb.MetaData(bind=db, reflect=True)
    t = md.tables['events']

    qt = time.time()
    log.info("query account:%s region:%s services time:%0.2f",
             account_name, region, time.time()-qt)

    record_count = 0
    for b in ['console', 'program']:
        for f in ['user_id', 'event_name', 'user_agent', 'error_code']:
            if b == 'console' and f == 'user_agent':
                continue
            q = query_by(t, f, b, since)
            qt = time.time()
            results = q.execute().fetchall()
            log.debug(
                "query account:%s region:%s bucket:%s field:%s points:%d time:%0.2f",
                account_name, region, b, f, len(results), time.time()-qt)
            measurements = []
            for p in results:
                if f == 'user_id':
                    v = p[2].split(':', 5)[-1]
                    if '/' in v:
                        parts = v.split('/')
                        # roll up old lambda functions to their role name
                        if parts[-1].startswith('i-') or parts[-1].startswith('awslambda'):
                            v = parts[1]
                else:
                    v = p[2]
                measurements.append({
                    'measurement': '%s_%s' % (b, f),
                    'tags': {
                        'region': region,
                        'account': account_name,
                        'service': p[3],
                        'bucket': b,
                        f: v},
                    'time': '%sZ' % p[0],
                    'fields': {
                        'call_count': p[1]}})
            pt = time.time()
            influx.write_points(measurements)
            record_count += len(measurements)
            log.debug(
                "post account:%s region:%s bucket:%s field:%s points:%d time:%0.2f",
                account_name, region, b, f, len(measurements), time.time()-pt)
    return record_count


def query_by(
        t, field, bucket='console', error=False, throttle=False, since=None):

    fields = [
        rdb.func.strftime(
            "%Y-%m-%dT%H:%M", t.c.event_date).label('short_time'),
        rdb.func.count().label('call_count'),
        t.c[field],
        t.c.event_source]

    query = rdb.select(fields).group_by(
        'short_time').group_by(t.c[field]).having(
            rdb.text('call_count > 3'))

    if field == 'error_code':
        query = query.where(t.c.error_code != None)

    query = query.group_by(t.c.event_source)

    if bucket == 'program':
        query = query.where(
            rdb.and_(
                t.c.user_agent != 'console.amazonaws.com',
                t.c.user_agent != 'console.ec2.amazonaws.com'))
    else:
        query = query.where(
            rdb.or_(
                t.c.user_agent == 'console.amazonaws.com',
                t.c.user_agent == 'console.ec2.amazonaws.com'))

    if throttle:
        query = query.where(
            rdb.or_(
                t.c.error_code == 'ThrottlingException',
                t.c.error_code == 'Client.RequestLimitExceeded'))
    elif error:
        query = query.where(
            rdb.and_(
                t.c.error_code != None,
                rdb.or_(
                    t.c.error_code != 'ThrottlingException',
                    t.c.error_code != 'Client.RequestLimitExceeded')))

    if since:
        query = query.where(
            rdb.text("short_time > %s" % (since.strftime("%Y-%m-%dT%H:%M"))))

    return query


def index_account(config, region, account, day, incremental):
    log = logging.getLogger('trailidx.processor')
    influx = InfluxDBClient(
        username=config['influx']['user'],
        password=config['influx']['password'],
        database=config['influx']['db'],
        host=config['influx'].get('host'))
    s3 = boto3.client('s3')
    bucket = account.get('bucket')
    name = account.get('name')
    key_template = config.get('key_template')

    log.info("processing account:%s region:%s day:%s",
             name, region, day.strftime("%Y/%m/%d"))

    with tempfile.NamedTemporaryFile(suffix='.db.bz2', delete=False) as fh:
        key_data = dict(account)
        key_data['region'] = region
        key_data['date_fmt'] = "%s/%s/%s" % (
            day.year, day.month, day.day)
        key = key_template % key_data
        st = time.time()

        try:
            s3.head_object(Bucket=bucket, Key=key)
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                log.warning("account:%s region:%s missing key:%s",
                            name, region, key)
                return
            raise
        s3.download_file(bucket, key, fh.name)
        log.debug("downloaded %s in %0.2f", key, time.time()-st)

        t = time.time()
        subprocess.check_call(["lbzip2", "-d", fh.name])
        log.debug("decompressed %s in %0.2f",  fh.name, time.time()-t)

        t = time.time()
        since = incremental and day or None
        record_count = process_traildb(
            rdb.create_engine("sqlite:////%s" % fh.name[:-4]),
            influx, name, region, since)
        log.debug("indexed %s in %0.2f",  fh.name, time.time()-t)
        os.remove(fh.name[:-4])
        log.info("account:%s day:%s region:%s records:%d complete:%0.2f",
                 name, region, day.strftime("%Y-%m-%d"),
                 record_count,
                 time.time()-st)


def get_date_range(start, end):
    if start:
        start = parse_date(start)
    if end:
        end = parse_date(end)

    if end and not start:
        raise ValueError("Missing start date")
    elif start and not end:
        end = datetime.datetime.utcnow()
    if not end and not start:
        return [
            datetime.datetime.utcnow() - datetime.timedelta(seconds=60 * 60)]

    days = []
    for n in range(1, (end-start).days):
        days.append(start + datetime.timedelta(n))
    days.insert(0, start)

    if start != end:
        days.append(end)

    return days


def get_incremental_starts(config, default_start):
    influx = InfluxDBClient(
        username=config['influx']['user'],
        password=config['influx']['password'],
        database=config['influx']['db'],
        host=config['influx'].get('host'))

    account_starts = {}
    for account in config.get('accounts'):
        for region in account.get('regions'):
            res = influx.query("""
                select * from program_event_name
                where account = '%s'
                  and region = '%s'
                order by time desc limit 1""" % (
                account['name'], region))
            if res is None or len(res) == 0:
                account_starts[account['name']] = default_start
            account_starts[account['name']] = parse_date(
                res.raw['series'][0]['values'][0][0])
    return account_starts


@click.command()
@click.option('-c', '--config', required=True, help="Config file")
@click.option('--start', required=True, help="Start date")
@click.option('--end', required=True, help="End Date")
@click.option('--incremental', default=False,
              help="Sync from last indexed timestamp")
@click.option('--concurrency', default=5)
def index(config, start, end, incremental=False, concurrency=5):
    """index traildbs directly from s3 for multiple accounts.

    context: assumes a daily traildb file in s3 with key path
             specified by key_template in config file for each account
    """
    with open(config) as fh:
        config = yaml.safe_load(fh.read())
    jsonschema.validate(config, CONFIG_SCHEMA)

    with ProcessPoolExecutor(max_workers=concurrency) as w:
        futures = {}

        if incremental:
            account_starts = get_incremental_starts(config['accounts'])
        else:
            account_starts = defaultdict(lambda : start)

        for account in config.get('accounts'):
            for d in get_date_range(account_starts[account['name']], end):
                for region in account.get('regions'):
                    i = bool(incremental and (d.hour or d.minute))
                    p = (config, region, account, d, i)
                    futures[w.submit(index_account, *p)] = p

        for f in as_completed(futures):
            _, region, account, d = futures[f]
            log.info("processed account:%s region:%s day:%s",
                     account['name'], region, d.strftime("%Y/%m/%d"))


if __name__ == '__main__':
    index(auto_envvar_prefix='TRAIL')
