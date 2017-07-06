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
import fakeredis
import logging

from c7n_mailer.ldap_lookup import LdapLookup, Redis
from ldap3 import Server, Connection, MOCK_SYNC
logger = logging.getLogger('custodian.mailer')

PETER = (
    'uid=peter,cn=users,dc=initech,dc=com',
    {
        'uid': ['peter'],
        'manager': 'uid=bill_lumbergh,cn=users,dc=initech,dc=com',
        'mail': 'peter@initech.com',
        'displayName': 'Peter',
        'objectClass': 'person'
    }
)
BILL = (
    'uid=bill_lumbergh,cn=users,dc=initech,dc=com',
    {
        'uid': ['bill_lumbergh'],
        'mail': 'bill_lumberg@initech.com',
        'displayName': 'Bill Lumberg',
        'objectClass': 'person'
    }
)

MAILER_CONFIG = {
    'smtp_port': 25,
    'from_address': 'devops@initech.com',
    'contact_tags': ['OwnerEmail', 'SupportEmail'],
    'queue_url': 'https://sqs.us-east-1.amazonaws.com/xxxx/cloudcustodian-mailer',
    'region': 'us-east-1',
    'ldap_uri': 'ldap.initech.com',
    'smtp_server': 'smtp.inittech.com',
    'cache_engine': 'sqlite',
    'role': 'arn:aws:iam::xxxx:role/cloudcustodian-mailer',
    'ldap_uid_tags': ['CreatorName', 'Owner'],
}

RESOURCE_1 = {
    'AvailabilityZone': 'us-east-1a',
    'Attachments': [],
    'Tags': [
        {
            'Value': 'milton@initech.com',
            'Key': 'SupportEmail'
        },
        {
            'Value': 'peter',
            'Key': 'CreatorName'
        }
    ],
    'VolumeId': 'vol-01a0e6ea6b89f0099'
}

SQS_MESSAGE_1 = {
    'account': 'core-services-dev',
    'region': 'us-east-1',
    'action': {
        'to': ['resource-owner', 'ldap_uid_tags'],
        'email_ldap_username_manager': True,
        'template': '',
        'priority_header': '1',
        'type': 'notify',
        'transport': {'queue': 'xxx', 'type': 'sqs'},
        'subject': '{{ account }} AWS EBS Volumes will be DELETED in 15 DAYS!'
    },
    'policy': {
        'filters': [{'Attachments': []}, {'tag:maid_status': 'absent'}],
        'resource': 'ebs',
        'actions': [
            {
                'type': 'mark-for-op',
                'days': 15,
                'op': 'delete'
            },
            {
                'to': ['resource-owner', 'ldap_uid_tags'],
                'email_ldap_username_manager': True,
                'template': '',
                'priority_header': '1',
                'type': 'notify',
                'subject': 'EBS Volumes will be DELETED in 15 DAYS!'
            }
        ],
        'comments': 'We are deleting your EBS volumes.',
        'name': 'ebs-mark-unattached-deletion'
    },
    'event': None,
    'resources': [RESOURCE_1]
}


def get_fake_ldap_connection():
    server = Server('my_fake_server')
    connection = Connection(
        server,
        client_strategy=MOCK_SYNC
    )
    connection.bind()
    connection.strategy.add_entry(PETER[0], PETER[1])
    connection.strategy.add_entry(BILL[0], BILL[1])
    return connection


def get_ldap_lookup(cache_engine=None, uid_regex=None):
        if cache_engine == 'sqlite':
            config = {
                'cache_engine': 'sqlite',
                'ldap_cache_file': ':memory:'
            }
        elif cache_engine == 'redis':
            config = {
                'cache_engine': 'redis',
                'redis_host': 'localhost'
            }
        if uid_regex:
            config['ldap_uid_regex'] = uid_regex
        ldap_lookup = MockLdapLookup(config, logger)
        michael_bolton = {
            'dn': 'CN=Michael Bolton,cn=users,dc=initech,dc=com',
            'mail': 'michael_bolton@initech.com',
            'manager': 'CN=Milton,cn=users,dc=initech,dc=com',
            'displayName':'Michael Bolton'
        }
        milton = {
            'uid': '123456',
            'dn': 'CN=Milton,cn=users,dc=initech,dc=com',
            'mail': 'milton@initech.com',
            'manager': 'CN=cthulhu,cn=users,dc=initech,dc=com',
            'displayName':'Milton'
        }
        bob_porter = {
            'dn': 'CN=Bob Porter,cn=users,dc=initech,dc=com',
            'mail': 'bob_porter@initech.com',
            'manager': 'CN=Bob Slydell,cn=users,dc=initech,dc=com',
            'displayName':'Bob Porter'
        }
        ldap_lookup.base_dn = 'cn=users,dc=initech,dc=com'
        ldap_lookup.uid_key = 'uid'
        ldap_lookup.attributes.append('uid')
        ldap_lookup.caching.set('michael_bolton', michael_bolton)
        ldap_lookup.caching.set(bob_porter['dn'], bob_porter)
        ldap_lookup.caching.set('123456', milton)
        ldap_lookup.caching.set(milton['dn'], milton)
        return ldap_lookup


class MockLdapLookup(LdapLookup):

    # allows us to instantiate this object and not need a redis daemon
    def get_redis_connection(self, redis_host, redis_port):
        return MockRedisLookup()

    # us to instantiate this object and not have ldap3 try to connect
    # to anything or raise exception in unit tests, we replace connection with a mock
    def get_connection(self, ignore, these, params):
        return get_fake_ldap_connection()


class MockRedisLookup(Redis):
    def __init__(self):
        self.connection = fakeredis.FakeStrictRedis()
