import logging

import yaml

from c7n.ctx import ExecutionContext
from c7n.handler import Config as Bag
from c7n.policies import PolicyCollection
from c7n.resources import load_resources
from c7n.utils import chunks

from c7n_org.utils import environ, account_tags
from mu_helper import lambdafunc, dispatch, Events

log = logging.getLogger('c7n.policyrun')


# Entry points
def handle_event(event, context):
    load_resources()
    dispatch(event, context)


@lambdafunc(subscribes=(Events.Periodic,))
def run_org(event, context):
    accounts = yaml.safe_load(open('accounts.yml')).get('accounts')
    policies = yaml.safe_load(open('policies.yml')).get('policies')
    # 128kb max payload, may need to chunk policies
    for account_set in chunks(accounts, 20):
        run_account_set(account_set, policies)


@lambdafunc()
def run_account_set(accounts, policies):
    for account in accounts:
        for policy_set in chunks(policies, 5):
            run_policy_set(account, policy_set)


@lambdafunc()
def run_policy_set(account, policies):
    for policy in policies:
        run_policy(account, policy)


@lambdafunc()
def run_policy(account, policy):
    bag = get_run_config(account)
    policies = PolicyCollection.from_data({'policies': [policy]}, bag)
    with environ(**account_tags(account)):
        for p in policies:
            log.debug("Running policy:%s account:%s", p.name, account['name'])
            st = time.time()
            try:
                resources = p.run()
                log.info("Ran account:%s region:%s policy:%s matched:%d time:%0.2f",
                             account['name'], region, p.name, len(resources), time.time()-st)
            except Exception as e:
                log.error(
                    "Exception running policy:%s account:%s error:%s",
                    p.name, account['name'], e)
    

# helpers
def get_run_config(account):
    return Bag.empty(
        assume_role=account['role'],
        account_id=account['account_id'],
        metrics_enabled=False,
        log_group=None)
