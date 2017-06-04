# Copyright 2016 Capital One Services, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from botocore.exceptions import ClientError
import boto3
import click
import json
from c7n.credentials import assumed_session
from c7n.executor import MainThreadExecutor
from c7n.utils import get_retry, dumps, chunks
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from dateutil.tz import tzutc, tzlocal
from dateutil.parser import parse
import fnmatch
import functools
import jsonschema
import logging
import time
import os
import yaml

logging.basicConfig(level=logging.INFO)
logging.getLogger('c7n.worker').setLevel(logging.DEBUG)
logging.getLogger('botocore').setLevel(logging.WARNING)

log = logging.getLogger('c7n-log-exporter')


CONFIG_SCHEMA = {
    '$schema': 'http://json-schema.org/schema#',
    'id': 'http://schema.cloudcustodian.io/v0/logexporter.json',
    'definitions': {
        'destination': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['bucket'],
            'properties': {
                'bucket': {'type': 'string'},
                'prefix': {'type': 'string'},
            },
        },
        'account': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['role', 'groups'],
            'properties': {
                'name': {'type': 'string'},
                'role': {'oneOf': [
                    {'type': 'array', 'items': {'type': 'string'}},
                    {'type': 'string'},
                    ]},
                'groups': {
                    'type': 'array', 'items': {'type': 'string'}
                }
            }
        }
    },
    'type': 'object',
    'additionalProperties': False,
    'required': ['accounts', 'destination'],
    'properties': {
        'accounts': {
            'type': 'array',
            'items': {'$ref': '#/definitions/account'}
        },
        'destination': {'$ref': '#/definitions/destination'}
    }
}


def debug(func):
    @functools.wraps(func)
    def run(*args, **kw):
        try:
            return func(*args, **kw)
        except SystemExit:
            raise
        except Exception:
            import traceback
            import pdb
            import sys
            traceback.print_exc()
            pdb.post_mortem(sys.exc_info()[-1])
            raise
    return run


@click.group()
def cli():
    """c7n cloudwatch log group exporter"""


@cli.command()
@click.option('--config', type=click.Path())
def validate(config):
    with open(config) as fh:
        content = fh.read()

    try:
        data = yaml.safe_load(content)
    except Exception:
        log.error("config file: %s is not valid yaml", config)
        raise

    try:
        jsonschema.validate(data, CONFIG_SCHEMA)
    except Exception:
        log.error("config file: %s is not valid", config)
        raise

    log.info("config file valid, accounts:%d", len(data['accounts']))
    return data


@cli.command()
@click.option('--config', type=click.Path(), required=True)
@click.option('--start', required=True)
@click.option('--end')
@click.option('-a', '--accounts', multiple=True)
@debug
def run(config, start, end, accounts):
    config = validate.callback(config)
    destination = config.get('destination')
    start = start and parse(start) or start
    end = end and parse(end) or datetime.now()
    with ThreadPoolExecutor(max_workers=32) as w:
        futures = {}
        for account in config.get('accounts', ()):
            if accounts and account['name'] not in accounts:
                continue
            futures[
                w.submit(process_account, account, start, end, destination)] = account
        for f in as_completed(futures):
            account = futures[f]
            if f.exception():
                log.error("Error on account %s err: %s",
                          account['name'], f.exception())
            log.info("Completed %s", account['name'])


def lambdafan(func):
    """simple decorator that will auto fan out async style in lambda.

    outside of lambda, this will invoke synchrously.
    """
    if 'AWS_LAMBDA_FUNCTION_NAME' not in os.environ:
        return func

    @functools.wraps(func)
    def scaleout(*args, **kw):
        client = boto3.client('lambda')
        client.invoke(
            FunctionName=os.environ['AWS_LAMBDA_FUNCTION_NAME'],
            InvocationType='Event',
            Payload=dumps({
                'event': 'fanout',
                'function': func.__name__,
                'args': args,
                'kwargs': kw}),
            Qualifier=os.environ['AWS_LAMBDA_FUNCTION_VERSION'])
    return scaleout


@lambdafan
def process_account(account, start, end, destination, incremental=True):
    session = get_session(account['role'])
    client = session.client('logs')

    paginator = client.get_paginator('describe_log_groups')
    groups = []
    for p in paginator.paginate():
        groups.extend([g for g in p.get('logGroups', ())])

    group_count = len(groups)
    groups = filter_creation_date(
        filter_group_names(groups, account['groups']),
        start, end)

    if incremental:
        groups = filter_last_write(client, groups, start)

    account_id = session.client('sts').get_caller_identity()['Account']
    prefix = destination.get('prefix', '').rstrip('/') + '/%s' % account_id

    log.info("account:%s matched %d groups of %d",
             account.get('name', account_id), len(groups), group_count)

    t = time.time()
    for g in groups:
        export.callback(
            g,
            destination['bucket'], prefix,
            g['exportStart'], end, account['role'],
            name=account['name'])

    log.info("account:%s exported %d log groups in time:%0.2f",
             account.get('name') or account_id,
             len(groups), time.time() - t)


def get_session(role, session_name="c7n-log-exporter", session=None):
    if role == 'self':
        session = boto3.Session()
    elif isinstance(role, basestring):
        session = assumed_session(role, session_name)
    elif isinstance(role, list):
        session = None
        for r in role:
            session = assumed_session(r, session_name, session=session)
    else:
        session = boto3.Session()
    return session


def filter_group_names(groups, patterns):
    """Filter log groups by shell patterns.
    """
    group_names = [g['logGroupName'] for g in groups]
    matched = set()
    for p in patterns:
        matched.update(fnmatch.filter(group_names, p))
    return [g for g in groups if g['logGroupName'] in matched]


def filter_creation_date(groups, start, end):
    """Filter log groups by their creation date.

    Also sets group specific value for start to the minimum
    of creation date or start.
    """
    results = []
    for g in groups:
        created = datetime.fromtimestamp(g['creationTime'] / 1000.0)
        if created > end:
            continue
        if created > start:
            g['exportStart'] = created
        else:
            g['exportStart'] = start
        results.append(g)
    return results


def filter_last_write(client, groups, start):
    """Filter log groups where the last write was before the start date.
    """
    retry = get_retry(('ThrottlingException',))

    def process_group(group_set):
        matched = []
        for g in group_set:
            streams = retry(
                client.describe_log_streams,
                logGroupName=g['logGroupName'],
                orderBy='LastEventTime',
                limit=1, descending=True)
            if not streams.get('logStreams'):
                continue
            stream = streams['logStreams'][0]
            if stream['storedBytes'] == 0 and datetime.fromtimestamp(
                    stream['creationTime'] / 1000) > start:
                matched.append(g)
            elif 'lastIngestionTime' in stream and datetime.fromtimestamp(
                    stream['lastIngestionTime'] / 1000) > start:
                matched.append(g)
        return matched

    results = []

    with ThreadPoolExecutor(max_workers=3) as w:
        futures = {}
        for group_set in chunks(groups, 10):
            futures[w.submit(process_group, group_set)] = group_set

        for f in as_completed(futures):
            if f.exception():
                log.error(
                    "Error processing groupset:%s error:%s",
                    group_set,
                    f.exception())
            results.extend(f.result())

    return results


def filter_extant_exports(client, bucket, prefix, days, start, end=None):
    """Filter days where the bucket already has extant export keys.
    """
    end = end or datetime.now()
    # days = [start + timedelta(i) for i in range((end-start).days)]
    try:
        tag_set = client.get_object_tagging(Bucket=bucket, Key=prefix).get('TagSet', [])
    except ClientError as e:
        if e.response['Error']['Code'] != 'NoSuchKey':
            raise
        tag_set = []
    tags = {t['Key']: t['Value'] for t in tag_set}

    if not 'LastExport' in tags:
        return sorted(days)
    last_export = parse(tags['LastExport'])
    return [d for d in sorted(days) if d > last_export]


@cli.command()
@click.option('--group', required=True)
@click.option('--bucket', required=True)
@click.option('--prefix')
@click.option('--start', required=True, help="export logs from this date")
@click.option('--end')
@click.option('--role', help="sts role to assume for log group access")
@click.option('--role', help="sts role to assume for log group access")
@click.option('--poll-period', type=float, default=300)
# @click.option('--bucket-role', help="role to scan destination bucket")
# @click.option('--stream-prefix)
@lambdafan
def export(group, bucket, prefix, start, end, role, poll_period=300, session=None, name=""):
    start = start and isinstance(start, basestring) and parse(start) or start
    end = (end and isinstance(start, basestring) and
           parse(end) or end or datetime.now())
    start = start.replace(tzinfo=tzlocal()).astimezone(tzutc())
    end = end.replace(tzinfo=tzlocal()).astimezone(tzutc())

    if session is None:
        session = get_session(role)

    client = session.client('logs')

    if prefix:
        prefix = "%s/%s" % (prefix.rstrip('/'),
            group['logGroupName'].strip('/'))
    else:
        prefix = group

    named_group = "%s:%s" % (name, group['logGroupName'])
    log.info(
        "Log exporting group:%s start:%s end:%s bucket:%s prefix:%s size:%s",
        named_group,
        start.strftime('%Y/%m/%d'),
        end.strftime('%Y/%m/%d'),
        bucket,
        prefix,
        group['storedBytes'])

    t = time.time()
    days = [(start + timedelta(i)).replace(minute=0, hour=0, second=0, microsecond=0)
            for i in range((end - start).days)]
    day_count = len(days)
    s3 = boto3.Session().client('s3')
    days = filter_extant_exports(s3, bucket, prefix, days, start, end)

    log.info("Group:%s filtering s3 extant keys from %d to %d",
             named_group, day_count, len(days))
    t = time.time()

    for idx, d in enumerate(days):
        date = d.replace(minute=0, microsecond=0, hour=0)
        export_prefix = "%s%s" % (prefix, date.strftime("/%Y/%m/%d"))
        params = {
            'taskName': "%s-%s" % ("c7n-log-exporter",
                                   date.strftime("%Y-%m-%d")),
            'logGroupName': group['logGroupName'],
            'fromTime': int(time.mktime(
                date.replace(
                    minute=0, microsecond=0, hour=0).timetuple()) * 1000),
            'to': int(time.mktime(
                date.replace(
                    minute=59, hour=23, microsecond=0).timetuple()) * 1000),
            'destination': bucket,
            'destinationPrefix': export_prefix
        }

        # if stream_prefix:
        #    params['logStreamPrefix'] = stream_prefix
        s3.put_object(
            Bucket=bucket,
            Key=prefix,
            Body=json.dumps({}),
            ACL="bucket-owner-full-control",
            ServerSideEncryption="AES256")

        t = time.time()
        counter = 0
        while True:
            counter += 1
            try:
                result = client.create_export_task(**params)
            except ClientError as e:
                if e.response['Error']['Code'] == 'LimitExceededException':
                    time.sleep(poll_period)
                    # log every 30m of export waiting
                    if counter % 6 == 0:
                        log.debug(
                            "group:%s day:%s waiting for %0.2f minutes",
                            named_group, d.strftime('%Y-%m-%d'),
                            (count * poll_period) / 60.0)
                    continue
                raise
            s3.put_object_tagging(
                Bucket=bucket, Key=prefix,
                Tagging={
                    'TagSet': [{
                        'Key': 'LastExport',
                        'Value': d.isoformat()}]})
            break

        log.info("Log export time:%0.2f group:%s day:%s bucket:%s prefix:%s task:%s",
                  time.time()-t,
                  named_group,
                  d.strftime("%Y-%m-%d"),
                  bucket,
                  params['destinationPrefix'],
                  result['taskId'])

    log.info(
        ("Exported log group:%s time:%0.2f days:%d start:%s"
         " end:%s bucket:%s prefix:%s"),
        named_group,
        time.time() - t,
        len(days),
        start.strftime('%Y/%m/%d'),
        end.strftime('%Y/%m/%d'),
        bucket,
        prefix)


if __name__ == '__main__':
    cli()
