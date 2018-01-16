
import boto3
import click
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import timedelta
from dateutil.parser import parse as date_parse
import gzip
import json
import logging
import multiprocessing
import os
import pprint
import sqlite3
import time


log = logging.getLogger('ipdb')

APP_TAG = os.environ.get('APP_TAG', 'app')
ENV_TAG = os.environ.get('ENV_TAG', 'env')
CONTACT_TAG = os.environ.get('CONTACT_TAG', 'contact')


def download_config(client, bucket, prefix, account_id, region, day, store, rtypes=()):
    config_prefix = "%sAWSLogs/%s/Config/%s/%s/ConfigHistory/" % (
        prefix,
        account_id,
        region,
        day.strftime('%Y/%m/%-d'))

    results = client.list_objects_v2(
        Bucket=bucket,
        Prefix=config_prefix)

    if not os.path.exists(store):
        os.makedirs(store)

    files = []
    downloads = Counter()

    log.debug("Downloading Config info prefix:%s" % config_prefix)

    for k in results.get('Contents', ()):
        found = False
        for rt in rtypes:
            if rt in k['Key']:
                found = True
        if not found:
            continue
        fname = k['Key'].rsplit('/', 1)[-1]
        fpath = os.path.join(store, fname)
        files.append(fpath)
        if os.path.exists(fpath):
            downloads['Cached'] += 1
            downloads['CacheSize'] += k['Size']
            continue
        downloads['Downloads'] += 1
        downloads['DownloadSize'] += k['Size']
        client.download_file(bucket, k['Key'], fpath)

    log.debug(
        "Downloaded:%d Size:%d Cached:%d Size:%s",
        downloads['Downloads'],
        downloads['DownloadSize'],
        downloads['Cached'],
        downloads['CacheSize'])
    return files, downloads


def process_account_resources(
        account_id, bucket, prefix, region,
        store, start, end, resource='NetworkInterface'):

    client = boto3.client('s3')
    files = []
    t = time.time()
    period_stats = Counter()
    period = (end - start).days
    resource = RESOURCE_MAPPING[resource]

    for i in range(period):
        day = start + timedelta(i)
        d_files, stats = download_config(
            client, bucket, prefix, account_id, region, day, store,
            rtypes=(resource,))
        files.extend(d_files)
        period_stats.update(stats)
    period_stats['FetchTime'] = int(time.time() - t)
    return files, period_stats



def resource_info(eni_cfg):
    desc = eni_cfg.get('description')
    instance_id = eni_cfg['attachment'].get('instanceId', '')
    if instance_id:
        rtype = 'ec2'
        rid = instance_id
    elif desc.startswith('ELB app/'):
        rtype = "alb"
        rid = desc.split('/')[1]
    elif desc.startswith('ELB net/'):
        rtype = "nlb"
        rid = desc.split('/')[1]
    elif desc.startswith('ELB '):
        rtype = 'elb'
        rid = desc.split(' ', 1)[1]
    elif desc.startswith('AWS ElasticMapReduce'):
        rtype = 'emr'
        rid = desc.rsplit(' ', 1)[1]
    elif desc.startswith('AWS created network interface for directory'):
        rtype = 'dir'
        rid = desc.rsplit(' ', 1)[1]
    elif desc.startswith('AWS Lambda VPC ENI:'):
        rtype = 'lam'
        rid = eni_cfg['requesterId'].split(':', 1)[1]
    elif desc == 'RDSNetworkInterface':
        rtype = 'rds'
        rid = ''
    elif desc == 'RedshiftNetworkInterface':
        rtype = 'red'
        rid = ''
    elif desc.startswith('ElastiCache '):
        rtype = 'eca'
        rid = desc.split(' ', 1)[1]
    elif desc.startswith('ElastiCache+'):
        rtype = 'eca'
        rid = desc.split('+', 1)[1]
    elif desc.startswith('Interface for NAT Gateway '):
        rtype = 'nat'
        rid = desc.rsplit(' ', 1)[1]
    elif desc.startswith('EFS mount target'):
        rtype = 'fsmt'
        fsid, fsmd = desc.rsplit(' ', 2)[1:]
        rid = "%s:%s" % (fsid, fsmd[1:-1])
    elif desc.startswith('CloudHSM Managed Interface'):
        rtype = 'hsm'
        rid = ''
    elif desc.startswith('CloudHsm ENI '):
        rtype = 'hsmv2'
        rid = desc.rsplit(' ', 1)[1]
    elif desc == 'DMSNetworkInterface':
        rtype = 'DMSNetworkInterface'
        rid = ''
    elif desc.startswith('DAX '):
        rtype = 'dax'
        rid = desc.rsplit(' ', 1)[1]
    elif desc.startswith('arn:aws:ecs:'):
        # a running task with attached net
        # 'arn:aws:ecs:us-east-1:0111111111110:attachment/37a927f2-a8d1-46d7-8f96-d6aef13cc5b0'
        # also has public ip.
        rtype = 'ecs'
        rid = desc.rsplit('/', 1)[1]
    elif desc.startswith('VPC Endpoint Interface'):
        # instanceOwnerId: amazon-aws
        # interfaceType: 'vpc_endpoint'
        rtype = 'vpce'
        rid = desc.rsplit(' ', 1)[1]
    elif eni_cfg['attachment']['instanceOwnerId'] == 'aws-lambda':
        rtype = 'lam'
        rid = eni_cfg['requesterId'].split(':', 1)[1]
    else:
        rtype = 'unknown'
        rid = json.dumps(eni_cfg)
    return rtype, rid


def resource_config_iter(files, batch_size=10000):
    for f in files:
        with gzip.open(f) as fh:
            data = json.load(fh)
        for config_set in chunks(data['configurationItems'], batch_size):
            yield config_set


def record_stream_filter(record_stream, record_filter, batch_size=5000):
    batch = []
    for record_set in record_stream:
        for r in record_set:
            if record_filter(r):
                batch.append(r)
            if len(batch) % batch_size == 0:
                yield batch
                batch = []
    if batch:
        yield batch


EBS_SCHEMA = """
create table if not exists ebs (
   volume_id text primary key,
   instance_id text,
   account_id  text,
   region      text,
   app         text,
   env         text,
   contact     text,
   start       text,
   end         text
)
"""


def index_ebs_files(db, record_stream):
    stats = Counter()
    t = time.time()
    with sqlite3.connect(db) as conn:
        cursor = conn.cursor()
        cursor.execute(EBS_SCHEMA)
        rows = []
        deletes = {}
        skipped = 0
        for record_set in record_stream:
            for cfg in record_set:
                if cfg['configurationItemStatus'] in ('ResourceDeleted',):
                    deletes[cfg['resourceId']] = cfg['configurationItemCaptureTime']
                    continue
                if not cfg['configuration'].get('attachments'):
                    skipped += 1
                    continue
                rows.append((
                    cfg['resourceId'],
                    cfg['configuration']['attachments'][0]['instanceId'],
                    cfg['awsAccountId'],
                    cfg['awsRegion'],
                    cfg['tags'].get(APP_TAG),
                    cfg['tags'].get(ENV_TAG),
                    cfg['tags'].get(CONTACT_TAG),
                    cfg['resourceCreationTime'],
                    None
                    ))
        if rows:
            for idx, r in enumerate(rows):
                if r[0] in deletes:
                    rows[idx] = list(r)
                    rows[idx][-1] = deletes[r[0]]
            cursor.executemany(
            '''insert or replace into ebs values (?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
            stats['RowCount'] += len(rows)

        log.debug("ebs stored:%d", len(rows))

    stats['RowCount'] += len(rows)
    stats['IndexTime'] = int(time.time() - t)
    return stats



EC2_SCHEMA = """
create table if not exists ec2 (
           instance_id    text primary key,
           account_id     text,
           region         text,
           ip_address     text,
           app            text,
           env            text,
           contact        text,
           asg            text,
           start      datetime,
           end        datetime
"""

def index_ec2_files(db, record_stream):
    stats = Counter()
    t = time.time()
    with sqlite3.connect(db) as conn:
        cursor = conn.cursor()
        cursor.execute(EC2_SCHEMA)
        rows = []
        deletes = []
        skipped = 0
        for record_set in record_stream:
            for cfg in record_set:
                if cfg['configurationItemStatus'] in ('ResourceDeleted',):
                    deletes.append((
                        (cfg['configurationItemCaptureTime'], cfg['resourceId'])
                        ))
                    continue
                if not cfg.get('tags'):
                    continue
                rows.append((
                    cfg['resourceId'],
                    cfg['awsAccountId'],
                    cfg['awsRegion'],
                    cfg['configuration'].get('privateIpAddress', ''),
                    cfg['tags'].get(APP_TAG),
                    cfg['tags'].get(ENV_TAG),
                    cfg['tags'].get(CONTACT_TAG),
                    cfg['tags'].get('aws:autoscaling:groupName', ''),
                    cfg['resourceCreationTime'],
                    None
                    ))
                if len(rows) % 1000 == 0:
                    stats['RowCount'] += len(rows)
                    cursor.executemany(
                    '''insert or replace into ec2 values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
                    rows = []
        if deletes:
            log.info("Delete count %d", len(deletes))
            stmt = 'update ec2 set end = ? where instance_id = ?'
            for p in deletes:
                cursor.execute(stmt, p)

        if rows:
            cursor.executemany(
            '''insert or replace into ec2 values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
        log.debug("ec2s stored:%d", len(rows))

    stats['RowCount'] += len(rows)
    stats['IndexTime'] = int(time.time() - t)
    return stats


S3_SCHEMA = """
create table if not exists buckets (
   name           text,
   account_id     text,
   region         text,
   app            text,
   env            text,
   contact        text,
   start      datetime,
   end        datetime,
   resource       text
)"""

import csv

def get_bucket_ids():
    with open(os.path.expanduser('~/s3-buckets.csv'), 'rU') as fh:
        return {r['BucketName'] for r in csv.DictReader(fh)}


def index_filtered_s3_files(db, record_stream):
    bucket_ids = get_bucket_ids()
    def filter_resources(r):
        return r['resourceId'] in bucket_ids
    return index_s3_files(db, record_stream_filter(record_stream, filter_resources))


def index_s3_files(db, record_stream):
    stats = Counter()
    t = time.time()
    with sqlite3.connect(db) as conn:
        cursor = conn.cursor()
        cursor.execute(S3_SCHEMA)
        deletes = {}
        rows = []
        skipped = 0

        for record_set in record_stream:
            for cfg in record_set:
                if cfg['configurationItemStatus'] == 'ResourceNotRecorded':
                    continue
                if cfg['configurationItemStatus'] in ('ResourceDeleted'):
                    deletes[cfg['resourceId']] = cfg['configurationItemCaptureTime']
                    rows.append((
                        cfg['resourceId'], None, None, None, None, None, None,
                        cfg['configurationItemCaptureTime'], None))
                    continue
                rows.append((
                    cfg['resourceId'],
                    cfg['awsAccountId'],
                    cfg['awsRegion'],
                    cfg['tags'].get(APP_TAG),
                    cfg['tags'].get(ENV_TAG),
                    cfg['tags'].get(CONTACT_TAG),
                    cfg['resourceCreationTime'],
                    None,
                    json.dumps(cfg)
                    ))

            if len(rows) % 10000:
                cursor.executemany(
                '''insert or replace into buckets values (?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
                stats['RowCount'] += len(rows)

        if rows:
            cursor.executemany(
            '''insert or replace into buckets values (?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
            stats['RowCount'] += len(rows)

    stats['IndexTime'] = int(time.time() - t)
    return stats


ELB_SCHEMA = """
create table if not exists elbs (
           name           text primary key,
           account_id     text,
           region         text,
           app            text,
           env            text,
           contact        text,
           start      datetime,
           end        datetime
)"""



def index_elb_files(db, record_stream):
    stats = Counter()
    t = time.time()
    with sqlite3.connect(db) as conn:
        cursor = conn.cursor()
        cursor.execute(ELB_SCHEMA)
        rows = []
        deletes = {}
        skipped = 0
        for record_set in record_stream:
            for cfg in record_set:
                if cfg['configurationItemStatus'] in ('ResourceDeleted',):
                    deletes[cfg['resourceId']] = cfg['configurationItemCaptureTime']
                    continue
                rows.append((
                    cfg['resourceName'],
                    cfg['awsAccountId'],
                    cfg['awsRegion'],
                    cfg['tags'].get(APP_TAG),
                    cfg['tags'].get(ENV_TAG),
                    cfg['tags'].get(CONTACT_TAG),
                    cfg['resourceCreationTime'],
                    None
                    ))
        if rows:
            for idx, r in enumerate(rows):
                if r[0] in deletes:
                    rows[idx] = list(r)
                    rows[idx][-1] = deletes[r[0]]
            cursor.executemany(
            '''insert or replace into elbs values (?, ?, ?, ?, ?, ?, ?, ?)''', rows)
            stats['RowCount'] += len(rows)

        log.debug("elbs stored:%d", len(rows))

    stats['RowCount'] += len(rows)
    stats['IndexTime'] = int(time.time() - t)
    return stats


def index_eni_files(db, record_stream):
    stats = Counter()
    t = time.time()
    with sqlite3.connect(db) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        create table if not exists enis (
          eni_id        text primary key,
          ip_address    text,
          account_id    text,
          resource_id   text,
          resource_type text,
          subnet_id     text,
          start     datetime,
          end       datetime
        )''')
        cursor.execute('create index if not exists eni_idx on enis(ip_address)')
        rows = []
        skipped = 0
        deletes = {}
        for record_set in record_stream:
            for cfg in record_set:
                if cfg['configurationItemStatus'] in ('ResourceDeleted',):
                    deletes[cfg['resourceId']] = cfg['configurationItemCaptureTime']
                    continue

                eni = eni['configuration']
                if 'attachment' not in eni:
                    skipped += 1
                    continue

                rtype, rid = resource_info(eni)
                rows.append((
                    eni['networkInterfaceId'],
                    eni['privateIpAddress'],
                    cfg['awsAccountId'],
                    rid,
                    rtype,
                    eni['subnetId'],
                    eni['attachment'].get('attachTime') or cfg['configurationItemCaptureTime'],
                    None,
                    ))

        log.debug("inserting %d deletes %d skipped: %d", len(rows), len(deletes), skipped)
        if rows:
            for idx, r in enumerate(rows):
                if r[0] in deletes:
                    rows[idx] = list(r)
                    rows[idx][-1] = deletes[r[0]]
                    del deletes[r[0]]
            cursor.executemany(
            '''insert into enis values (?, ?, ?, ?, ?, ?, ?, ?)''', rows)
            stats['RowCount'] += len(rows)

    result = cursor.execute('select count(distinct ip_address) from enis').fetchone()

    stats['SkipCount'] = skipped
    stats['IndexTime'] = int(time.time() - t)
    return stats


def chunks(iterable, size=50):
    """Break an iterable into lists of size"""
    batch = []
    for n in iterable:
        batch.append(n)
        if len(batch) % size == 0:
            yield batch
            batch = []
    if batch:
        yield batch


RESOURCE_MAPPING = {
    'Instance': 'AWS::EC2::Instance',
    'LoadBalancer': 'AWS::ElasticLoadBalancing',
    'NetworkInterface': 'AWS::EC2::NetworkInterface',
    'Volume': 'AWS::EC2::Volume',
    'Bucket': 'AWS::S3::Bucket'
}

RESOURCE_FILE_INDEXERS = {
    'Instance': index_ec2_files,
    'NetworkInterface': index_eni_files,
    'LoadBalancer': index_elb_files,
    'Volume': index_ebs_files,
    'Bucket': index_filtered_s3_files
}


@click.group()
def cli():
    """AWS Network Resource Database"""


@cli.command('list-app-resources')
@click.option('--app')
@click.option('--env')
@click.option('--cmdb')
@click.option('--start')
@click.option('--end')
@click.option('--tz')
@click.option(
    '-r', '--resources', multiple=True,
    type=click.Choice(['Instance', 'LoadBalancer', 'Volume']))
def list_app_resources(
        app, env, resources, cmdb, start, end, tz):
    """Analyze flow log records for application and generate metrics per period"""
    logging.basicConfig(level=logging.INFO)
    start, end = get_dates(start, end, tz)

    all_resources = []
    for rtype_name in resources:
        rtype = Resource.get_type(rtype_name)
        resources = rtype.get_resources(cmdb, start, end, app, env)
        all_resources.extend(resources)
    print(json.dumps(all_resources, indent=2))

    
@cli.command('load-resources')
@click.option('--bucket', required=True)
@click.option('--prefix', required=True)
@click.option('--region', required=True)
@click.option('--account-config', type=click.Path(), required=True)
@click.option('-a', '--accounts', multiple=True)
@click.option('--start')
@click.option('--end')
@click.option('-r', '--resources', multiple=True,
                  type=click.Choice(list(RESOURCE_FILE_INDEXERS.keys())))
@click.option('--store', type=click.Path())
@click.option('-f', '--db')
@click.option('-v', '--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
def load_resources(bucket, prefix, region, account_config, accounts,
                       start, end, resources, store, db, verbose, debug):
    logging.basicConfig(level=(verbose and logging.DEBUG or logging.INFO))
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('s3transfer').setLevel(logging.WARNING)
    start = date_parse(start)
    end = date_parse(end)

    account_ids = []
    with open(account_config) as fh:
        for name, a in json.load(fh)['accounts'].items():
            if accounts:
                if a['accountNumber'] in accounts or name in accounts:
                    account_ids.append(a['accountNumber'])
            else:
                account_ids.append(a['accountNumber'])

    ip_count = 0
    executor = ProcessPoolExecutor
    if debug:
        from c7n.executor import MainThreadExecutor
        MainThreadExecutor.async = False
        executor = MainThreadExecutor

    stats = Counter()
    t = time.time()
    with executor(max_workers=multiprocessing.cpu_count()) as w:
        futures = {}
        for a in account_ids:
            for r in resources:
                futures[w.submit(
                    process_account_resources, a, bucket, prefix,
                    region, store, start, end, r)] = (a, r)

        indexer = RESOURCE_FILE_INDEXERS[r]
        for f in as_completed(futures):
            a, r = futures[f]
            if f.exception():
                log.error("account:%s error:%s", a, f.exception())
                continue
            files, dl_stats = f.result()
            idx_stats = indexer(db, resource_config_iter(files))
            log.info(
                "loaded account:%s files:%d bytes:%d resources:%d idx-time:%d dl-time:%d",
                a, len(files),
                dl_stats['DownloadSize'] + dl_stats['CacheSize'],
                idx_stats['RowCount'],
                idx_stats['IndexTime'],
                dl_stats['FetchTime'])
            stats.update(dl_stats)
            stats.update(idx_stats)
    log.info("Loaded %d resources across %d accounts in %0.2f",
                 stats['RowCount'], len(account_ids), time.time() - t)


if __name__ == '__main__':
    try:
        cli()
    except Exception:
        import pdb, traceback, sys
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])
