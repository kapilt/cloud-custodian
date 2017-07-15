"""Run a custodian policy across an organization's accounts
"""
from collections import Counter
import csv
import logging
from io import StringIO
import urllib2
import os
import time

from concurrent.futures import (
    ProcessPoolExecutor,
    as_completed)
import yaml

import click
import jsonschema
from botocore.compat import OrderedDict

from c7n.executor import MainThreadExecutor
from c7n.handler import Config as Bag
from c7n.policy import PolicyCollection
from c7n.reports.csvout import Formatter, fs_record_set
from c7n.resources import load_resources
from c7n.manager import resources as resource_registry
from c7n.utils import CONN_CACHE, dumps

log = logging.getLogger('c7n_org')

CONFIG_SCHEMA = {
    '$schema': 'http://json-schema.org/schema#',
    'id': 'http://schema.cloudcustodian.io/v0/logexporter.json',
    'definitions': {
        'account': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['role', 'account_id'],
            'properties': {
                'name': {'type': 'string'},
                'account_id': {'type': 'string'},
                'tags': {'type': 'array', 'items': {'type': 'string'}},
#                'bucket': {'type': 'string'},
                'regions': {'type': 'array', 'items': {'type': 'string'}},
                'role': {'oneOf': [
                    {'type': 'array', 'items': {'type': 'string'}},
                    {'type': 'string'}]},
                }
            }
        },
    'type': 'object',
    'additionalProperties': False,
    'required': ['accounts'],
    'properties': {
        'accounts': {
            'type': 'array',
            'items': {'$ref': '#/definitions/account'}
            }
    }
}


def run_account(account, region, policies_config, output_path, cache_period, dryrun, debug):
    """Execute a set of policies on an account.
    """
    CONN_CACHE.session = None
    CONN_CACHE.time = None
    output_path = os.path.join(output_path, account['name'], region)
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    cache_path = os.path.join(output_path, "c7n.cache")
    bag = Bag.empty(
        region=region, assume_role=account['role'],
        cache_period=cache_period, dryrun=dryrun, output_dir=output_path,
        account_id=account['account_id'], metrics_enabled=False,
        cache=cache_path, log_group=None, profile=None, external_id=None)

    policies = PolicyCollection.from_data(policies_config, bag)

    policy_counts = {}
    for p in policies:
        log.debug(
            "Running policy:%s account:%s region:%s", p.name, account['name'], region)
        try:
            resources = p.run()
            policy_counts[p.name] = resources and len(resources) or 0
            if not resources:
                continue
            log.info("Ran account:%s region:%s policy:%s matched:%d",
                         account['name'], region, p.name, len(resources))
        except Exception as e:
            log.error(
                "Exception running policy:%s account:%s region:%s error:%s",
                p.name, account['name'], region, e)
            if not debug:
                continue
            import traceback, pdb, sys
            pdb.post_mortem(sys.exc_info()[-1])
            raise

    return policy_counts

@click.group()
def cli():
    """custodian organization multi-account runner."""


def init(config, use, debug, verbose, accounts, tags, policies):
    level = verbose and logging.DEBUG or logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s: %(name)s:%(levelname)s %(message)s")

    logging.getLogger('botocore').setLevel(logging.ERROR)
    logging.getLogger('custodian').setLevel(logging.WARNING)
    logging.getLogger('custodian.s3').setLevel(logging.ERROR)

    with open(config) as fh:
        accounts_config = yaml.safe_load(fh.read())
        jsonschema.validate(accounts_config, CONFIG_SCHEMA)

    with open(use) as fh:
        custodian_config = yaml.safe_load(fh.read())

    filtered_policies = []
    for p in custodian_config.get('policies', ()):
        if policies and p['name'] not in policies:
            continue
        filtered_policies.append(p)
    custodian_config['policies'] = filtered_policies

    filtered_accounts = []
    for a in accounts_config.get('accounts', ()):
        if accounts and a['name'] not in accounts:
            continue
        if tags:
            found = False
            for t in tags:
                if t in a.get('tags', ()):
                    found = True
                    break
            if not found:
                continue
        filtered_accounts.append(a)
    accounts_config['accounts'] = filtered_accounts
    load_resources()
    MainThreadExecutor.async = False
    executor = debug and MainThreadExecutor or ProcessPoolExecutor
    return accounts_config, custodian_config, executor


def report_account(account, region, policies_config, output_path, debug):
    cache_path = os.path.join(output_path, "c7n.cache")
    output_path = os.path.join(output_path, account['name'], region)
    bag = Bag.empty(
        region=region, assume_role=account['role'],
        output_dir=output_path,
        account_id=account['account_id'], metrics_enabled=False,
        cache=cache_path, log_group=None, profile=None, external_id=None)

    policies = PolicyCollection.from_data(policies_config, bag)
    records = []
    for p in policies:
        log.debug(
            "Report policy:%s account:%s region:%s path:%s",
            p.name, account['name'], region, output_path)
        policy_records = fs_record_set(p.ctx.output_path, p.name)
        for r in policy_records:
            r['policy'] = p.name
            r['region'] = p.options.region
            r['account'] = account['name']
            for t in account['tags']:
                if ':' in t:
                    k, v = t.split(':', 1)
                    r[k] = v
        records.extend(policy_records)
    return records


@cli.command()
@click.option('-c', '--config', required=True, help="Accounts config file")
@click.option('-f', '--output', type=click.File('wb'), default='-', help="Output File")
@click.option('-u', '--use', required=True)
@click.option('-s', '--output-dir', required=True, type=click.Path())
@click.option('-a', '--accounts', multiple=True, default=None)
@click.option('--field', multiple=True)
@click.option('-t', '--tags', multiple=True, default=None)
@click.option('-r', '--region', default=['us-east-1', 'us-west-2'], multiple=True)
@click.option('--debug', default=False, is_flag=True)
@click.option('-v', '--verbose', default=False, help="Verbose", is_flag=True)
@click.option('-p', '--policy', multiple=True)
@click.option('--format', default='csv', type=click.Choice(['csv', 'json']))
def report(config, output, use, output_dir, accounts, field, tags, region, debug, verbose, policy, format):
    accounts_config, custodian_config, executor = init(
        config, use, debug, verbose, accounts, tags, policy)

    resource_types = set()
    for p in custodian_config.get('policies'):
        resource_types.add(p['resource'])
    if len(resource_types) > 1:
        raise ValueError("can only report on one resource type at a time")

    records = []
    with executor(max_workers=16) as w:
        futures = {}
        for a in accounts_config.get('accounts', ()):
            account_regions = region or a['regions']
            for r in account_regions:
                futures[w.submit(
                    report_account,
                    a, r,
                    custodian_config,
                    output_dir,
                    debug)] = (a, r)

        for f in as_completed(futures):
            a, r = futures[f]
            if f.exception():
                if debug:
                    raise
                log.warning(
                    "Error running policy in %s @ %s exception: %s",
                    a['name'], r, f.exception())
            records.extend(f.result())

    log.debug(
        "Found %d records across %d accounts and %d policies",
        len(records), len(accounts_config['accounts']),
        len(custodian_config['policies']))

    if format == 'json':
        dumps(records, output, indent=2)
        return

    prefix_fields = OrderedDict(
        (('Account', 'account'), ('Region', 'region'), ('Policy', 'policy')))
    config = Bag.empty()
    factory = resource_registry.get(list(resource_types)[0])

    formatter = Formatter(
        factory.resource_type,
        extra_fields=field,
        include_default_fields=True,
        include_region=False,
        include_policy=False,
        fields=prefix_fields)

    rows = formatter.to_csv(records)
    writer = csv.writer(output, formatter.headers())
    writer.writerow(formatter.headers())
    writer.writerows(rows)


@cli.command(name='run')
@click.option('-c', '--config', required=True, help="Accounts config file")
@click.option("-u", "--use", required=True)
@click.option('-s', '--output-dir', required=True, type=click.Path())
@click.option('-a', '--accounts', multiple=True, default=None)
@click.option('-t', '--tags', multiple=True, default=None)
@click.option('-r', '--region', default=['us-east-1', 'us-west-2'], multiple=True)
@click.option('-p', '--policy', multiple=True)
@click.option('--cache-period', default=15, type=int)
@click.option("--dryrun", default=False, is_flag=True)
@click.option('--debug', default=False, is_flag=True)
@click.option('-v', '--verbose', default=False, help="Verbose", is_flag=True)
def run(config, use, output_dir, accounts, tags, region, policy, cache_period, dryrun, debug, verbose):
    accounts_config, custodian_config, executor = init(
        config, use, debug, verbose, accounts, tags, policy)
    policy_counts = Counter()
    with executor(max_workers=32) as w:
        futures = {}
        for a in accounts_config.get('accounts', ()):
            account_regions = region or a['regions']
            for r in account_regions:
                futures[w.submit(
                    run_account,
                    a, r,
                    custodian_config,
                    output_dir,
                    cache_period,
                    dryrun,
                    debug)] = (a, r)

        for f in as_completed(futures):
            a, r = futures[f]
            if f.exception():
                if debug:
                    raise
                log.warning(
                    "Error running policy in %s @ %s exception: %s",
                    a['name'], r, f.exception())

            for p, count in f.result().items():
                policy_counts[p] += count

    log.info("Policy resource counts %s" % policy_counts)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        raise
        import traceback, pdb, sys
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])
