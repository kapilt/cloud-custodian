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

"""Salactus, eater of s3 buckets.

queues:
 - buckets-iterator
 - bucket-set
 - bucket-partition
 - bucket-page-iterator
 - bucket-keyset-scan

stats:
 - buckets-complete:set
 - buckets-start:hash
 - buckets-end:hash

 - buckets-size: hash
 - buckets-large: hash # TODO

 - keys-scanned:hash
 - keys-matched:hash
 - keys-denied:hash

monitor:
 - buckets-unknown-errors:hash
 - buckets-denied:set


"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import logging
import itertools
import math
import threading
import time
import random
import string
import os

import redis
from rq.decorators import job

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, ConnectionError

from c7n.credentials import assumed_session
from c7n.resources.s3 import EncryptExtantKeys
from c7n.utils import chunks

# We use a connection cache for sts role assumption
CONN_CACHE = threading.local()

SESSION_NAME = os.environ.get("SALACTUS_NAME", "s3-salactus")
REDIS_HOST = os.environ["SALACTUS_REDIS"]

# Minimum size of the bucket before partitioning
PARTITION_BUCKET_SIZE_THRESHOLD = 100000

# Page size for keys found during partition
PARTITION_KEYSET_THRESHOLD = 500

# Length of partition queue before going parallel
PARTITION_QUEUE_THRESHOLD = 6

BUCKET_OBJ_DESC = {
    True: ('Versions', 'list_object_versions',
           ('NextContinuationToken',)),
    False: ('Contents', 'list_objects_v2',
            ('NextKeyMarker', 'NextVersionIdMarker'))
    }

connection = redis.Redis(host=REDIS_HOST)
# Increase timeouts to assist with non local regions, also
# seeing some odd net slowness all around.
s3config = Config(read_timeout=420, connect_timeout=90)
keyconfig = {
    'report-only': False,
    'glacier': False,
    'large': True,
    'crypto': 'AES256'}

log = logging.getLogger("salactus")


def get_session(account_info):
    s = getattr(CONN_CACHE, '%s-session', None)
    t = getattr(CONN_CACHE, 'time', 0)
    n = time.time()
    if s is not None and t + (60 * random.uniform(20, 45)) > n:
        return s
    if account_info.get('role'):
        s = assumed_session(account_info['role'], SESSION_NAME)
    else:
        s = boto3.Session()
    CONN_CACHE.session = s
    CONN_CACHE.time = n
    return s


def bucket_id(account_info, bucket_name):
    return "%s:%s" % (account_info['name'], bucket_name)


def invoke(func, *args, **kw):
    func.delay(*args, **kw)


@contextmanager
def bucket_ops(account_info, bucket_name, api=""):
    """context manager for dealing with s3 errors in one place
    """
    try:
        yield 42
    except ClientError as e:
        code = e.response['Error']['Code']
        log.info(
            "bucket error account:%s bucket:%s error:%s",
            account_info['name'],
            bucket_name,
            e.response['Error']['Code'])
        if code == "NoSuchBucket":
            pass
        elif code == 'AccessDenied':
            connection.sadd(
                'buckets-denied',
                bucket_id(account_info, bucket_name))
        else:
            connection.hset(
                'buckets-unknown-errors',
                bucket_id(account_info, bucket_name),
                "%s:%s" % (api, e.response['Error']['Code']))
    except:
        # Let the error queue catch it
        raise


def page_strip(page, bucket):
    """Remove bits in content results to minimize memory utilization.

    TODO: evolve this to a key filter on metadata.
    """
    page.pop('ResponseMetadata', None)
    contents_key = bucket['versioned'] and 'Versions' or 'Contents'
    contents = page.get(contents_key, ())
    if not contents:
        return
    # Depending on use case we may want these
    for k in contents:
        k.pop('Owner', None)
        k.pop('LastModified')
    return page


def bucket_key_count(client, bucket):
    params = dict(
        Namespace='AWS/S3',
        MetricName='NumberOfObjects',
        Dimensions=[
            {'Name': 'BucketName',
             'Value': bucket['name']},
            {'Name': 'StorageType',
             'Value': 'AllStorageTypes'}],
        StartTime=datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0) - timedelta(1),
        EndTime=datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0),
        Period=60*60*24,
        Statistics=['Minimum'])
    response = client.get_metric_statistics(**params)
    if not response['Datapoints']:
        return 0
    return response['Datapoints'][0]['Average']


@job('buckets-iterator', timeout=3600, connection=connection)
def process_account(account_info):
    """Scan all buckets in an account and schedule processing"""
    log = logging.getLogger('salactus.bucket-iterator')
    log.info("processing account %s", account_info)
    session = get_session(account_info)
    client = session.client('s3', config=s3config)
    buckets = [n['Name'] for n in client.list_buckets()['Buckets']]
    log.info("processing %d buckets in account %s",
             len(buckets), account_info['name'])
    for bucket_set in chunks(buckets, 50):
        invoke(process_bucket_set, account_info, bucket_set)


@job('bucket-set', timeout=3600, connection=connection)
def process_bucket_set(account_info, buckets):
    """Process a collection of buckets.

    For each bucket fetch location, versioning and size and
    then kickoff processing strategy based on size.
    """
    region_clients = {}
    log = logging.getLogger('salactus.bucket-set')
    log.info("processing account %s", account_info)
    session = get_session(account_info)
    client = session.client('s3', config=s3config)

    for b in buckets:
        bid = bucket_id(account_info, b)
        with bucket_ops(account_info, b):
            info = {'name': b}
            location = client.get_bucket_location(
                Bucket=b).get('LocationConstraint')
            if location is None:
                region = "us-east-1"
            elif location == 'EU':
                region = "eu-west-1"
            else:
                region = location
            info['region'] = region
            if region not in region_clients:
                region_clients.setdefault(region, {})
                region_clients[region]['s3'] = s3 = session.client(
                    's3', region_name=region, config=s3config)
                region_clients[region]['cloudwatch'] = cw = session.client(
                    'cloudwatch', region_name=region, config=s3config)
            else:
                s3 = region_clients[region]['s3']
                cw = region_clients[region]['cloudwatch']
            versioning = s3.get_bucket_versioning(Bucket=b)
            info['versioned'] = (
                versioning and versioning.get('Status', '')
                in ('Enabled', 'Suspended') or False)
            info['keycount'] = bucket_key_count(cw, info)
            connection.hset('bucket-size', bid, info['keycount'])
            log.info("processing bucket %s", info)
            if info['keycount'] > PARTITION_BUCKET_SIZE_THRESHOLD:
                invoke(process_bucket_partitions, account_info, info)
            else:
                invoke(process_bucket_iterator, account_info, info)


class CharSet(object):
    """Sets of character/gram populations for the ngram partition strategy.
    """
    hex_lower = set(string.hexdigits.lower())
    hex = set(string.hexdigits)
    digits = set(string.digits)
    ascii_lower = set(string.ascii_lowercase)
    ascii_letters = set(string.ascii_letters)
    ascii_lower_digits = set(string.ascii_lowercase + string.digits)
    ascii_alphanum = set(string.ascii_letters + string.digits)

    @classmethod
    def charsets(cls):
        return [
            cls.hex_lower,
            cls.hex,
            cls.digits,
            cls.ascii_lower,
            cls.ascii_letters,
            cls.ascii_lower_digits,
            cls.ascii_alphanum]


class NGramPartition(object):
    """A keyspace partition strategy that uses a fixed set of prefixes.

    Good for flat, shallow keyspaces.
    """

    name = "ngram"

    def __init__(self, grams=set(string.hexdigits.lower()), limit=3):
        self.grams = grams
        self.limit = limit

    def initialize_prefixes(self, prefix_queue):
        if prefix_queue != ('',):
            return prefix_queue
        return ["".join(n) for n in
                itertools.permutations(self.grams, self.limit)]

    def find_partitions(self, prefix_queue, results):
        return []

    def is_depth_execeeded(self, prefix):
        return False


class CommonPrefixPartition(object):
    """A keyspace partition strategy that probes common prefixes.

    We probe a bucket looking for common prefixes up to our max
    partition depth, and use parallel objects iterators on each that
    exceed the max depth or that have more than 1k keys.

    Note common prefixes are limited to a thousand by default, if that happens
    we should record an error.

    Good for nested hierarchical keyspaces.
    """

    name = "common-prefix"

    def __init__(self, partition='/', limit=4):
        self.partition = partition
        self.limit = limit

    def initialize_prefixes(self, prefix_queue):
        if prefix_queue == ('',):
            return ['']
        return prefix_queue

    def find_partitions(self, prefix_queue, results):
        return [p['Prefix'] for p in results.get('CommonPrefixes', [])]

    def is_depth_exceeded(self, prefix):
        return prefix.count(self.partition) > self.limit


def get_partition_strategy(account_info, bucket, strategy=None):
    if strategy is None:
        return CommonPrefixPartition()
    elif strategy == 'p':
        return CommonPrefixPartition()
    elif strategy == 'n':
        return NGramPartition()


def detect_partition_strategy(account_info, bucket, delimiters=('/', '-')):
    """Try to detect the best partitioning strategy for a large bucket

    """
    bid = bucket_id(account_info, bucket['name'])
    session = get_session(account_info)
    s3 = session.client('s3', region_name=bucket['region'], config=s3config)

    (contents_key,
     contents_method,
     continue_tokens) = BUCKET_OBJ_DESC[bucket['versioned']]

    with bucket_ops(account_info, bucket['name'], 'detect'):
        keys = set()
        for delimiter in delimiters:
            method = getattr(s3, contents_method, None)
            results = method(
                Bucket=bucket['name'], Prefix='', Delimiter=delimiter)
            prefixes = results.get('CommonPrefixes', [])
            contents = results.get(contents_key, [])
            keys.update([k['Key'] for k in contents])
            # If we have common prefixes within limit thresholds go wide
            if (len(prefixes) > 0 and
                len(prefixes) < 1000 and
                    len(contents) < 1000):
                process_bucket_partitions(
                    account_info, bucket, partition=delimiter,
                    strategy='p')

    # Switch out to ngram, first use the keys found to sample possible chars
    chars = set()
    for k in keys:
        chars.update(['Key'][:4])

    # Detect character sets
    charset = None
    for candidate in CharSet.charsets():
        if chars.issubset(candidate):
            charset = candidate
    if charset is None:
        raise ValueError("Failed charset ngram detetion %s" % ("".join(chars)))

    # Determine the depth we need to keep total api calls below threshold
    scan_count = bucket['keycount'] / 1000.0
    for limit in range(1, 5):
        if math.pow(len(charset), limit) * 1000 > scan_count:
            break

    # Dispatch
    prefixes = []
    NGramPartition(charset, limit=limit).initiaize_prefixes(prefixes)
    return process_bucket_partitions(
        account_info, bucket, prefix_set=prefixes, partition="", strategy="n")


@job('bucket-partition', timeout=3600*4, connection=connection)
def process_bucket_partitions(
        account_info, bucket, prefix_set=('',), partition='/',
        limit=5, strategy=None):
    """Split up a bucket keyspace into smaller sets for parallel iteration.
    """
    if strategy is None:
        return detect_partition_strategy(account_info, bucket)
    strategy = get_partition_strategy(strategy)
    (contents_key,
     contents_method,
     continue_tokens) = BUCKET_OBJ_DESC[bucket['versioned']]
    prefix_queue = list(prefix_set)
    keyset = []
    bid = bucket_id(account_info, bucket['name'])

    session = get_session(account_info)
    s3 = session.client('s3', region_name=bucket['region'], config=s3config)

    def statm(prefix):
        return "keyset:%d queue:%d prefix:%s bucket:%s size:%d" % (
            len(keyset), len(prefix_queue), prefix, bid, bucket['keycount'])

    while prefix_queue:
        connection.hincrby('bucket-partition', bid, 1)
        prefix = prefix_queue.pop()
        if strategy.is_depth_exceeded(partition):
            log.info("Partition max depth reached, %s", statm(prefix))
            invoke(process_bucket_iterator, account_info, bucket, prefix)
            continue
        method = getattr(s3, contents_method, None)
        results = page_strip(method(
            Bucket=bucket['name'], Prefix=prefix, Delimiter=partition))
        keyset.extend(results.get(contents_key, ()))

        # As we probe we find keys, process any found
        if len(keyset) > PARTITION_KEYSET_THRESHOLD:
            log.info("Partition, processing keyset %s", statm(prefix))
            invoke(
                process_keyset, account_info, bucket, page_strip({contents_key: keyset}))
            keyset = []

        strategy.find_partitions(prefix_queue, results)

        # Do we have more than 1k keys at this level, continue iteration
        continuation_params = {
            k: results[k] for k in continue_tokens if k in results}
        if continuation_params:
            log.info("Partition has 1k keys, %s", statm(prefix))
            invoke(process_bucket_iterator,
                   account_info, bucket, prefix, delimiter=partition,
                   **continuation_params)

        # If the queue get too deep, then go parallel
        if len(prefix_queue) > PARTITION_QUEUE_THRESHOLD:
            log.info("Partition add friends, %s", statm(prefix))
            for prefix_set in chunks(
                    prefix_queue[PARTITION_QUEUE_THRESHOLD-1:],
                    PARTITION_QUEUE_THRESHOLD-1):
                invoke(process_bucket_partitions,
                       account_info, bucket,
                       prefix_set=prefix_set, partition=partition, limit=limit,
                       strategy=strategy)
            prefix_queue = prefix_queue[:PARTITION_QUEUE_THRESHOLD-1]

    if keyset:
        invoke(process_keyset, account_info, bucket, {contents_key: keyset})


@job('bucket-page-iterator', timeout=3600*24, connection=connection)
def process_bucket_iterator(account_info, bucket,
                            prefix="", delimiter="", **continuation):
    """Bucket pagination
    """
    log.info("Iterating keys bucket %s prefix %s delimiter %s",
             bucket_id(account_info, bucket['name']), prefix, delimiter)
    session = get_session(account_info)
    s3 = session.client('s3', region_name=bucket['region'], config=s3config)

    (contents_key,
     contents_method,
     _) = BUCKET_OBJ_DESC[bucket['versioned']]

    params = dict(Bucket=bucket['name'], Prefix=prefix, Delimiter=delimiter)
    if continuation:
        params.update(continuation)
    paginator = s3.get_paginator(contents_method).paginate(**params)
    with bucket_ops(account_info, bucket['name'], 'page'):
        connection.hset(
            'buckets-start',
            bucket_id(account_info, bucket['name']), time.time())
        for page in paginator:
            page = page_strip(page, bucket)
            if page.get(contents_key):
                invoke(process_keyset, account_info, bucket, page)


@job('bucket-keyset-scan', timeout=3600*4, connection=connection)
def process_keyset(account_info, bucket, key_set):
    session = get_session(account_info)
    s3 = session.client('s3', region_name=bucket['region'], config=s3config)
    processor = EncryptExtantKeys(keyconfig)
    remediation_count = 0
    denied_count = 0
    contents_key, _, _ = BUCKET_OBJ_DESC[bucket['versioned']]
    processor = (bucket['versioned'] and processor.process_version
                 or processor.process_key)
    connection.hincrby(
        'keys-scanned', bucket_id(account_info, bucket['name']),
        len(key_set.get(contents_key, [])))
    log.info("processing page size: %d on %s",
             len(key_set.get(contents_key, ())),
             bucket_id(account_info, bucket['name']))

    with bucket_ops(account_info, bucket, 'key'):
        for k in key_set.get(contents_key, []):
            try:
                result = processor(s3, bucket_name=bucket['name'], key=k)
            except ConnectionError:
                continue
            except ClientError as e:
                # https://goo.gl/HZLv9b
                code = e.response['Error']['Code']
                if code == '403': # Permission Denied
                    denied_count += 1
                    continue
                elif code == '404':  # Not Found
                    continue
                elif code in ('503', '400'):  # Slow Down, or token err
                    # TODO, consider backoff alg usage, and re-queue of keys
                    time.sleep(3)
                    continue
                raise
            if result is False:
                continue
            remediation_count += 1
        if remediation_count:
            connection.hincrby(
                'keys-matched',
                bucket_id(account_info, bucket['name']),
                remediation_count)
        if denied_count:
            connection.hincrby(
                'keys-denied',
                bucket_id(account_info, bucket['name']),
                denied_count)


def setup_parser():
    parser = argparse.ArgumentParser(
        description="Scan s3 at scale, format")
    parser.add_argument("--accounts", required=True)
    parser.add_argument("--tag", required=True)
    return parser


def main():
    parser = setup_parser()
    options = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s: %(name)s:%(levelname)s %(message)s")
    logging.getLogger('botocore').setLevel(level=logging.WARNING)
    with open(options.accounts) as fh:
        data = json.load(fh)
        for account in data:
            if options.tag not in account.get('tags', ()):
                continue
            invoke(process_account, account)


if __name__ == '__main__':
    try:
        main()
    except (SystemExit, KeyboardInterrupt) as e:
        raise
    except:
        import traceback, sys, pdb
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])
