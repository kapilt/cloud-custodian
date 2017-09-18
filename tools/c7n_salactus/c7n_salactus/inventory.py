"""

inventories

  account - inventory bucket, inventory-prefix
  bucket
    - inventory-bucket, inventory-prefix
    
"""

import csv
import datetime
import functools
import gzip
import json
import os
import random
import tempfile
import time

import boto3
import click
from c7n.utils import chunks, local_session
from dateutil.parser import parse

from c7n_salactus.worker import connection, CONN_CACHE


def load_manifest_file(client, bucket, versioned, key_info):
    """Given an inventory csv file, return an iterator over keys
    """
    # to avoid thundering herd downloads
    #yield None
    size = 0
    with tempfile.NamedTemporaryFile() as fh:
        print "download files", key_info
        inventory_data = client.download_fileobj(
            Bucket=bucket, Key=key_info['key'], Fileobj=fh)
        fh.seek(0)
        reader = csv.reader(gzip.GzipFile(fileobj=fh, mode='r'))
        for key_set in chunks(reader, 1000):
            import pdb; pdb.set_trace()
            size += len(key_set)
            if versioned:
                keys = []
                for kr in key_set:
                    if kr[3] == 'true':
                        keys.append((kr[1], kr[2], True))
                    else:
                        keys.append((kr[1], kr[2]))
            else:
                keys = [kr[1] for kr in key_set]
            yield keys

    print key_info, size


def load_bucket_inventory(
        session_factory, inventory_bucket, inventory_prefix, region):
    """Given an inventory location for a bucket, return an iterator over keys

    on the most recent delivered manifest.
    """
    client = local_session(session_factory).client('s3', region_name=region)
    now = datetime.datetime.now()
    key_prefix = "%s/%s" % (inventory_prefix, now.strftime('%Y-%m-'))
    keys = client.list_objects(
        Bucket=inventory_bucket, Prefix=key_prefix).get('Contents', [])
    keys = [k['Key'] for k in keys if k['Key'].endswith('.json')]
    keys.sort()
    latest_manifest = keys[-1]
    manifest = client.get_object(Bucket=inventory_bucket, Key=latest_manifest)
    manifest_data = json.load(manifest['Body'])
    versioned = 'IsLatest' in manifest_data['fileSchema']
    processor = functools.partial(
        load_manifest_file, client, inventory_bucket, versioned)
    generators = map(processor, manifest_data.get('files', ()))
    return random_chain(generators)


def random_chain(generators):
    """Generator to generate a set of keys from
    from a set of generators, each generator is selected
    at random and consumed to exhaustion.
    """
    while generators:
        g = random.choice(generators)
        try:
            v = g.next()
            if v is None:
                continue
            yield v
        except StopIteration:
            generators.remove(g)

def get_bucket_config(bid):

    bucket_config = getattr(CONN_CACHE, 'bucket_config', None)

    # we'll get some races
    if bucket_config is not None and bid in bucket_config:
        pass


    
    return

def handler_bucket_enable_inventory(bid, info):
    account, bucket = bid.split(':', 1)
    session = get_session(json.loads(connection.hget('bucket-accounts', account)))
    region = connection.hget('bucket-regions', bid)
    s3 = session.client('s3', region_name=region, config=s3config)

def handler_bucket_keyset_scan(bid, info):
    pass


def handler_bucket_check_permissions(bid, info):
    pass


def process_bucket_inventory(bid):
    account, bucket = bid.split(':', 1)
    client = boto3.Session().client('s3')
    inventories = client.list_bucket_inventory_configurations(Bucket=bucket)
    for i in inventories.get('InventoryConfigurationList', []):
        if i['Id'] != 'salactus':
            continue
        s3_info = i['Destination']['S3BucketDestination']
        return load_bucket_inventory(
            boto3.Session,
            s3_info['Bucket'].rsplit(':', 1)[1],
            "%s/%s/%s" % (s3_info['Prefix'], bucket, i['Id']),
            'us-east-1')


@click.command(name="process-inventories")
@click.option('--bucket')
def main(bucket):
    count = 0
    key_count = 0
    start_time = time.time()
    for key_set in process_bucket_inventory(":%s" % bucket):
        count += 1
        key_count += len(key_set)
        if count % 1000 == 0:
            print count
    print "inventory"
    print count
    print key_count
    print time.time() - start_time

if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except:
        import traceback, pdb, sys
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])
        

