"""
A tool to manage
"""

import click
import jsonschema
import yaml

from c7n_gcp.client import Session
from c7n_gcp import mu


SCHEMA = {
    'properties': {
        'scope': {'enum': ['project', 'organization']},
        'topic_name': {'type': 'string'},
        'projects': {'type': 'array', 'items': {'type': 'string'}},
        'events': {
            'type': 'array',
            'items': {
                'type': 'object',
                'source': {'type': 'string'},
                'methods': {'type': ['array']}
            },
        },
                
    },



}

def load_config(config_file):
    config = yaml.safe_load(config_file)
    jsonschema.validate(config, SCHEMA)
    return config

    
@click.group()
def cli():
    """GCP Audit Log API Notifier"""
    

@click.command()
def create(config_file):
    """Provision notifications."""
    config = load_config(config_file)
    session = Session()
    subscriber_config = {
        'methods': [m['methods'] for m in config['events']],
        'topic_name': config['topic_name'],
        'sink_name': config['sink_name']}
 
    subscriber = mu.ApiSubscriber(session, subscriber_config)
    subscriber.add(
        mu.CloudFunction({'name': config['topic_name']})


@click.command()
def delete():
    """Remove notification infrastructure."""
    config = load_config(config_file)
    session = Session()
    subscriber_config = {
        'methods': [m['methods'] for m in config['events']],
        'topic_name': config['topic_name'],
        'sink_name': config['sink_name']}
 
    subscriber = mu.ApiSubscriber(session, subscriber_config)
    subscriber.remove(
        mu.CloudFunction({'name': config['topic_name']})

