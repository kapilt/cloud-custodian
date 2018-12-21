from botocore.credentials import get_credentials
import boto3
import click
from c7n.credentials import assumed_session
from c7n.executor import MainThreadExecutor
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dateutil.parser import parse as parse_date
from elasticsearch import Elasticsearch, RequestsHttpConnection
from elasticsearch.client import IndicesClient
from elasticsearch.helpers import bulk
import functools
import json
import logging
import time
from requests_aws4auth import AWS4Auth


log = logging.getLogger('omnissm.idx')


@click.group()
def cli():
    """omnissm indexer cli"""


INVENTORY_TYPES = [
    "AWS:AWSComponent",
    "AWS:Application",
    "AWS:ComplianceItem",
    "AWS:ComplianceSummary",
    "AWS:Deleted",
    "AWS:Tag",
    "AWS:InstanceDetailedInformation",
    "AWS:InstanceInformation",
    "AWS:Network",
    "AWS:Service",
    "AWS:WindowsRole",
    "AWS:WindowsUpdate",
    "Custom:CloudInfo",
    "Custom:ProcessInfo"]

REQUIRED_INVENTORY = [
    'AWS:Tag', 'Custom:CloudInfo']


def get_es(eshosts, role_idx, session):
    if role_idx:
        if role_idx == 'host':
            credentials = get_credentials(session._session)
        else:
            credentials = assumed_session(role_idx, "OmnissmIndex", session)._credentials
        auth = AWS4Auth(
            credentials.access_key, credentials.secret_key,
            eshosts[0].split('.')[1], 'es', session_token=credentials.token)
        es = Elasticsearch(
            eshosts, use_ssl=True, verify_certs=True,
            connection_class=RequestsHttpConnection,
            http_auth=auth)
    else:
        es = Elasticsearch(eshosts)
    return es


@cli.command()
@click.option('-e', '--eshosts', multiple=True, help="Elasticsearch Hosts")
@click.option('--role-idx', help="IAM role for indexing")
@click.option(
    '-t', '--types', multiple=True, help="Which inventory types to index",
    type=click.Choice(INVENTORY_TYPES))
def reset(eshosts, role_idx, types):
    """Delete indexes - Caution"""
    session = role_idx and boto3.Session() or None
    es = get_es(eshosts, role_idx, session)
    idxc = IndicesClient(es)
    for t in types:
        tidx = t.split(':')[-1].lower()
        indexes = idxc.get('{}*'.format(tidx))
        for i in indexes:
            idxc.delete(i)

@cli.command()
@click.option('-b', '--bucket', required=True, help="Bucket to index")
@click.option('-p', '--prefix', required=True, help="Inventory prefix")
@click.option('--since', help="Only index data after date")
@click.option(
    '-t', '--types', multiple=True, help="Which inventory types to index",
    type=click.Choice(INVENTORY_TYPES))
@click.option('--role-s3', help="Role to assume for reading bucket")
@click.option('-e', '--eshosts', multiple=True, help="Elasticsearch Hosts")
@click.option('--role-idx', help="IAM role for indexing")
@click.option('--debug', is_flag=True, default=False)
@click.option('--queue', help="SQS Queue")
def index(bucket, prefix, types, since, role_s3, eshosts, role_idx, debug, queue):
    pass

@cli.command()
@click.option('-b', '--bucket', required=True, help="Bucket to index")
@click.option('-p', '--prefix', required=True, help="Inventory prefix")
@click.option('--since', help="Only index data after date")
@click.option(
    '-t', '--types', multiple=True, help="Which inventory types to index",
    type=click.Choice(INVENTORY_TYPES))
@click.option('--role-s3', help="Role to assume for reading bucket")
@click.option('-e', '--eshosts', multiple=True, help="Elasticsearch Hosts")
@click.option('--role-idx', help="IAM role for indexing")
@click.option('--debug', is_flag=True, default=False)
@click.option('--queue', help="SQS Queue")
def index(bucket, prefix, types, since, role_s3, eshosts, role_idx, debug, queue):
    """index resouces into elasticearch"""
    #logging.basicConfig(level=logging.INFO)
    # todo auto fetch lastest for each inventory type from indexed
    modified_since = since and parse_date(since) or None
    session = boto3.Session()

    es = get_es(eshosts, role_idx, session)
    if role_s3:
        s3 = assumed_session(role_s3, "OmnissmIndex", session).client('s3')
    else:
        s3 = session.client('s3')

    if queue:
        sqs = session.client('sqs')

    worker_factory = ThreadPoolExecutor
    if debug:
        MainThreadExecutor.async = False
        worker_factory = MainThreadExecutor

    with worker_factory(max_workers=16) as w:
        for itype in types:
            iprefix = "{}/{}/".format(
                prefix.strip('/'), itype)
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(
                    Bucket=bucket,
                    Prefix=iprefix):
                key_set = filter_page(page, since)
                if queue:
                    queue_key_set(key_set, sqs, queue)
                else:
                    fanout_key_set(key_set, bucket, prefix, es, s3, w)


def filter_page(page, since):
    key_set = []
    for k in page.get("Contents", []):
        if since and k['LastModified'] < since:
            continue
        key_set.append(k)
    return key_set


def queue_key_set(key_set, sqs, queue):
    sqs.send_message(
        QueueUrl=queue,
        MessageBody=json.dumps({'Contents': key_set}))


def fanout_key_set(key_set, bucket, prefix, es, s3, workers):
    futures = {}
    t = time.time()
    for kchunk in chunks(key_set, 50):
        futures[
            workers.submit(
                process_key_set, s3, es, bucket, prefix, kchunk)] = kchunk

    completed = 0
    stats = Counter()
    for f in as_completed(futures):
        if f.exception():
            raise f.exception()
        completed += len(futures[f])
        for r, v in f.result().items():
            stats[r] += v
        continue

    print(
        "indexed processed keys:%d seconds:%0.2f stats:%s" % (
        len(key_set), time.time() - t, stats.items()))


def process_key_set(s3, es, bucket, prefix, key_set):
    stats = Counter()
    for k in key_set:
        for r, v in process_key(s3, es, bucket, prefix, k).items():
            stats[r] += v
    return stats


def process_key(s3, es, bucket, prefix, k):
    inventory_type, account, region, resource_type, info = k[
        'Key'][len(prefix)+1:].strip('/').split('/')
    account_env = prefix.split('/')[-1]

    content = s3.get_object(Bucket=bucket, Key=k['Key'])
    required = {}
    for i in REQUIRED_INVENTORY:
        ikey = "{}/{}/{}/{}/{}/{}".format(
            prefix, i, account, region, resource_type, info)
        try:
            idata = s3.get_object(Bucket=bucket, Key=ikey)
        except s3.exceptions.NoSuchKey:
            continue
        for l in idata['Body'].iter_lines():
            required.setdefault(i.split(':')[-1], []).append(
                json.loads(l.decode('utf8')))

    if not required:
        return {'missing-cloudinfo': 1}

    resource = required['CloudInfo'][0]
    if 'Tag' not in required:
        #print("missing tags %s" % (required,))
        return {'missing-tags': 1}
    for t in required['Tag']:
        resource[t['Key']] = t['Value']

    records = get_records(content["Body"])
    idx = inventory_type.split(':')[-1].lower()
    for d in records:
        ct = d.pop('captureTime', None)
        d.update(resource)
        d['_index'] = idx
        d['_type'] = idx
        d['AccountEnv'] = account_env
        if ct:
            d['captureTime'] = ct

    while True:
        try:
            bulk(es, records)
            return {'ok': 1, 'records': len(records)}
        except Exception as e:
            import traceback, pdb, sys
            traceback.print_exc()
            print("error indexing records %s" % e)
            time.sleep(5)
            return {'error': 1}

def get_records(fh):
    content = fh.read().strip().decode('utf8')
    if not content:
        return []
    try:
        data = json.loads(content)
        return [data]
    except Exception:
        pass
    return list(map(json.loads, content.split('\n')))


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


if __name__ == '__main__':

    try:
        cli()
    except Exception as e:
        import traceback, sys, pdb  # NOQA
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])
