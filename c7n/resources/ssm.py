# Copyright 2016-2017 Capital One Services, LLC
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
from __future__ import absolute_import, division, print_function, unicode_literals

import json
import hashlib

from c7n.actions import Action
from c7n.exceptions import PolicyValidationError
from c7n.query import QueryResourceManager, TypeInfo
from c7n.manager import resources
from c7n.utils import chunks, get_retry, local_session, type_schema, filter_empty
from c7n.version import version

from .aws import shape_validate
from .ec2 import EC2


@resources.register('ssm-parameter')
class SSMParameter(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'ssm'
        enum_spec = ('describe_parameters', 'Parameters', None)
        name = "Name"
        id = "Name"
        universal_taggable = True
        arn_type = "parameter"

    retry = staticmethod(get_retry(('Throttled',)))
    permissions = ('ssm:GetParameters',
                   'ssm:DescribeParameters')


@resources.register('ssm-managed-instance')
class ManagedInstance(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'ssm'
        enum_spec = ('describe_instance_information', 'InstanceInformationList', None)
        id = 'InstanceId'
        name = 'Name'
        date = 'RegistrationDate'
        arn_type = "managed-instance"

    permissions = ('ssm:DescribeInstanceInformation',)


@EC2.action_registry.register('send-command')
@ManagedInstance.action_registry.register('send-command')
class SendCommand(Action):
    """Run an SSM Automation Document on an instance.

    :Example:

    Find ubuntu 18.04 instances are active with ssm.

    .. code-block:: yaml

        policies:
          - name: ec2-osquery-install
            resource: ec2
            filters:
              - type: ssm
                key: PingStatus
                value: Online
              - type: ssm
                key: PlatformName
                value: Ubuntu
              - type: ssm
                key: PlatformVersion
                value: 18.04
            actions:
              - type: send-command
                command:
                  DocumentName: AWS-RunShellScript
                  Parameters:
                    commands:
                      - wget https://pkg.osquery.io/deb/osquery_3.3.0_1.linux.amd64.deb
                      - dpkg -i osquery_3.3.0_1.linux.amd64.deb
    """

    schema = type_schema(
        'send-command',
        command={'type': 'object'},
        required=('command',))

    permissions = ('ssm:SendCommand',)
    shape = "SendCommandRequest"
    annotation = 'c7n:SendCommand'

    def validate(self):
        shape_validate(self.data['command'], self.shape, 'ssm')
        # If used against an ec2 resource, require an ssm status filter
        # to ensure that we're not trying to send commands to instances
        # that aren't in ssm.
        if self.manager.type != 'ec2':
            return

        found = False
        for f in self.manager.iter_filters():
            if f.type == 'ssm':
                found = True
                break
        if not found:
            raise PolicyValidationError(
                "send-command requires use of ssm filter on ec2 resources")

    def process(self, resources):
        client = local_session(self.manager.session_factory).client('ssm')
        for resource_set in chunks(resources, 50):
            self.process_resource_set(client, resource_set)

    def process_resource_set(self, client, resources):
        command = dict(self.data['command'])
        command['InstanceIds'] = [
            r['InstanceId'] for r in resources]
        result = client.send_command(**command).get('Command')
        for r in resources:
            r.setdefault('c7n:SendCommand', []).append(result['CommandId'])


@resources.register('ssm-activation')
class SSMActivation(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'ssm'
        enum_spec = ('describe_activations', 'ActivationList', None)
        id = 'ActivationId'
        name = 'Description'
        date = 'CreatedDate'
        arn = False

    permissions = ('ssm:DescribeActivations',)


@SSMActivation.action_registry.register('delete')
class DeleteSSMActivation(Action):
    schema = type_schema('delete')
    permissions = ('ssm:DeleteActivation',)

    def process(self, resources):
        client = local_session(self.manager.session_factory).client('ssm')
        for a in resources:
            client.delete_activation(ActivationId=a["ActivationId"])


@resources.register('ops-item')
class OpsItem(QueryResourceManager):

    class resource_type(TypeInfo):

        enum_spec = ('describe_ops_items', 'OpsItemSummaries', None)
        service = 'ssm'
        arn = False
        id = 'OpsItemId'

        default_report_fields = (
            'Status', 'Title', 'LastModifiedTime',
            'CreatedBy', 'CreatedTime')


class PostItem(Action):
    """Post an OpsItem to AWS Systems Manager OpsCenter.

    https://docs.aws.amazon.com/systems-manager/latest/userguide/OpsCenter.html

    : Example :
x
    Create an ops item for sqs queues with cross account access as ops
    items.

    .. code-block:: yaml

        policies:
          - name: sqs-cross-account-access
            resource: aws.sqs
            filters:
              - type: cross-account
            actions:
              - type: post-item

    : Example :

    Create an ops item for ec2 instances with Create User permissions

    .. code-block:: yaml

        policies:
          - name: over-privileged-ec2
            resource: aws.ec2
            filters:
              - type: check-permissions
                match: allowed
                actions:
                  - iam:CreateUser
            actions:
              - type: post-item
    """

    schema = type_schema(
        'post-item',
        description={'type': 'string'},
        tags={'type': 'object'},
        priority={'enum': list(range(1, 6))},
        title={'type': 'string'},
    )
    schema_alias = True

    def process(self, resources, event=None):
        client = local_session(
            self.manager.session_factory).client('ssm')

        for resource_set in chunks(resources, 225):
            resource_arns = json.dumps(
                [{'arn': arn} for arn in sorted(self.manager.get_arns(resource_set))])
            item = self.get_item_template()
            item['OperationalData']['/aws/resources'] = {
                'Type': 'SearchableString',
                'Value': resource_arns}
            try:
                oid = client.create_ops_item(
                    **filter_empty(item)).get('OpsItemId')
                for r in resource_set:
                    r['c7n:opsitem'] = oid
            except client.exceptions.OpsItemAlreadyExistsException:
                continue

    def get_item_template(self):
        dedup = ("%s %s %s" % (
            self.manager.data['name'],
            self.manager.config.region,
            self.manager.config.account_id)).encode('utf8')
        dedup = hashlib.md5(dedup).hexdigest()

        return dict(
            Title=self.data.get('title', self.manager.data.get('name')),
            Description=self.data.get(
                'description',
                self.manager.data.get(
                    'description',
                    self.manager.data.get('name'))),
            Priority=self.data.get('priority'),
            Source="Cloud Custodian",
            Tags=self.data.get('tags', self.manager.data.get('tags')),
            OperationalData={
                '/aws/dedup': {
                    'Type': 'SearchableString',
                    'Value': json.dumps({'dedupString': dedup})},
                '/custodian/execution-id': {
                    'Type': 'String',
                    'Value': self.manager.ctx.execution_id},
                '/custodian/policy': {
                    'Type': 'String',
                    'Value': json.dumps(self.manager.data)},
                '/custodian/version': {
                    'Type': 'String',
                    'Value': version},
                '/custodian/policy-name': {
                    'Type': 'SearchableString',
                    'Value': self.manager.data['name']},
                '/custodian/resource': {
                    'Type': 'SearchableString',
                    'Value': self.manager.type},
            }
        )

    @classmethod
    def register(cls, registry, _):
        for resource in registry.keys():
            klass = registry.get(resource)
            klass.action_registry.register('post-item', cls)


resources.subscribe(resources.EVENT_FINAL, PostItem.register)
