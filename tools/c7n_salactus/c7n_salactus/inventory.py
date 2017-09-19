"""

inventories

  account - inventory bucket, inventory-prefix
  bucket
    - inventory-bucket, inventory-prefix
    
"""

import csv
import datetime
import functools
import fnmatch
import gzip
import json
import os
import random
import tempfile
import time

import boto3
from c7n.utils import chunks, local_session
from dateutil.parser import parse

from six.moves.urllib_parse import unquote_plus

def load_manifest_file(client, bucket, schema, versioned, key_info):
    """Given an inventory csv file, return an iterator over keys
    """
    # to avoid thundering herd downloads
    yield None

    with tempfile.NamedTemporaryFile() as fh:
        inventory_data = client.download_fileobj(
            Bucket=bucket, Key=key_info['key'], Fileobj=fh)
        fh.seek(0)
        reader = csv.reader(gzip.GzipFile(fileobj=fh, mode='r'))
        for key_set in chunks(reader, 1000):
            keys = []
            for kr in key_set:
                k = kr[1]
                if '%' in k:
                    k = unquote_plus(k)
                if versioned:
                    if kr[3] == 'true':
                        keys.append((k, kr[2], True))
                    else:
                        keys.append((k, kr[2]))
                else:
                    keys.append(k)
            yield keys


def load_bucket_inventory(client, inventory_bucket, inventory_prefix, versioned):
    """Given an inventory location for a bucket, return an iterator over keys

    on the most recent delivered manifest.
    """
    now = datetime.datetime.now()
    key_prefix = "%s/%s" % (inventory_prefix, now.strftime('%Y-%m-'))
    keys = client.list_objects(
        Bucket=inventory_bucket, Prefix=key_prefix).get('Contents', [])
    keys = [k['Key'] for k in keys if k['Key'].endswith('.json')]
    keys.sort()
    latest_manifest = keys[-1]
    manifest = client.get_object(Bucket=inventory_bucket, Key=latest_manifest)
    manifest_data = json.load(manifest['Body'])

    schema = [n.strip() for n in manifest_data['fileSchema'].split(',')]

    processor = functools.partial(
        load_manifest_file, client, inventory_bucket, schema, versioned)
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


def get_bucket_inventory(client, bucket, inventory_id):
    """Check a bucket for a named inventory, and return the inventory destination."""
    inventories = client.list_bucket_inventory_configurations(
        Bucket=bucket).get('InventoryConfigurationList', [])
    inventories = {i['Id']: i for i in inventories}
    found = fnmatch.filter(inventories, inventory_id)
    if not found:
        raise ValueError("Bucket:%s no inventories found %s" % (
            bucket, ', '.join(inventories)))

    i = inventories[found.pop()]
    s3_info = i['Destination']['S3BucketDestination']
    return {'bucket': s3_info['Bucket'].rsplit(':')[-1],
            'prefix': "%s/%s/%s" % (s3_info['Prefix'], bucket, i['Id'])}
