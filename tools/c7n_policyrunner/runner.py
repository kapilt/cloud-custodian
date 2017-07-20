
from c7n.ctx import ExecutionContext
from c7n.handler import Config
from c7n.policies import PolicyCollection
from c7n.resources import load_resources
from c7n.utils import chunks

import yaml
from structlog import get_logger

from mu_helper import lambdafunc, dispatch, Events

log = get_logger()


def run_collection(config, collection):
    for p in collection:
        try:
            p.run()
        except Exception as e:
            log.error(policy=p.name, resource=p.resource, error=str(e))


@lambdafunc()
def process_policy_set(policy_config):
    config = get_config()
    policies = get_policies(config)
    run_collection(policies)


@lambdafunc(subscribes=(Events.Periodic,))
def process_periodic(event, context):
    config = get_config()
    policies = get_policies(config)
    for policy_set in get_policy_sets(policies, 5):
        process_policy_set(policy_set)


def get_policy_sets(collection):
    for pset in chunks(collection, 5):
        yield {'policies': [p.data for p in pset]}


def get_config():
    config = Config.empty()
    return config


def get_policies(config, policy_config=None):
    load_resources()
    if policy_config is None:
        policy_config = yaml.safe_load(open('policies.yml').read())
    return PolicyCollection.from_data(policy_config)


def handle_event(event, context):
    load_resources()
    dispatch(event, context)


    
