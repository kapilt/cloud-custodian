# Copyright 2020 Kapil Thangavelu
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

import json
try:
    import docker
except ImportError:
    docker = None
import os
import pytest

TEST_DOCKER = not (docker and os.environ.get('TEST_DOCKER', 'no') == 'yes')


CUSTODIAN_ORG_IMAGE = os.environ.get(
    'CUSTODIAN_ORG_IMAGE', 'cloudcustodian/c7n-org:latest')
CUSTODIAN_IMAGE = os.environ.get(
    'CUSTODIAN_CLI_IMAGE', 'cloudcustodian/c7n:latest')
CUSTODIAN_MAILER_IMAGE = os.environ.get(
    'CUSTODIAN_MAILER_IMAGE', 'cloudcustodian/mailer:latest')
CUSTODIAN_PSTREAM_IMAGE = os.environ.get(
    'CUSTODIAN_POLICYSTREAM_IMAGE', 'cloudcustodian/policystream:latest')


@pytest.fixture
def custodian_org_dir(tmpdir):
    with open(os.path.join(tmpdir, 'accounts.json'), 'w') as fh:
        fh.write(json.dumps({
            'accounts': [{
                'account_id': '644160558196',
                'name': 'c7n-test',
                'role': 'arn:aws:iam::644160558196:role/CloudCustodianRole',
                'region': [
                    'us-east-1',
                    'us-east-2',
                    'us-west-2',
                    'eu-west-1']}]
        }))

    with open(os.path.join(tmpdir, 'policy.json'), 'w') as fh:
        fh.write(json.dumps({
            'policies': [
                {'name': 'ec2',
                 'resource': 'aws.ec2'},
                {'name': 'lambda',
                 'resource': 'aws.lambda'}]
        }))

    return tmpdir


@pytest.fixture
def custodian_env_creds():
    env_keys = ["AWS_DEFAULT_REGION", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID"]
    env = []
    for k in env_keys:
        env.append("%s=%s" % (k, os.environ.get(k)))
    return env


@pytest.mark.skipif(TEST_DOCKER, reason="docker testing not requested")
def test_org_run(custodian_org_dir, custodian_env_creds):
    client = docker.from_env()
    client.containers.run(
        CUSTODIAN_ORG_IMAGE,
        ('run -v -a c7n -c {dir}/accounts.json'
         ' -s {dir}/output'
         ' --region=all'
         ' -u {dir}/policy.json').format(dir='/home/custodian/'),
        environment=custodian_env_creds,
        remove=True,
        stderr=True,
        volumes={custodian_org_dir: {'bind': '/home/custodian', 'mode': 'rw'}})


@pytest.mark.skipif(TEST_DOCKER, reason="docker testing not requested")
def test_run(custodian_org_dir, custodian_env_creds):
    client = docker.from_env()
    client.containers.run(
        CUSTODIAN_IMAGE,
        ('run -v'
         ' -s {dir}/output'
         ' {dir}/policy.json').format(dir='/home/custodian/'),
        environment=custodian_env_creds,
        remove=True,
        stderr=True,
        volumes={custodian_org_dir: {'bind': '/home/custodian', 'mode': 'rw'}})
