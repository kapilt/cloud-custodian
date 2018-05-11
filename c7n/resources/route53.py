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

import functools

from c7n.query import QueryResourceManager, ChildResourceManager
from c7n.manager import resources
from c7n.utils import chunks, get_retry, generate_arn, local_session,type_schema
from c7n.actions import BaseAction
from c7n.filters import Filter

from c7n.resources.shield import IsShieldProtected, SetShieldProtection
from c7n.tags import RemoveTag, Tag


class Route53Base(object):

    permissions = ('route53:ListTagsForResources',)
    retry = staticmethod(get_retry(('Throttled',)))

    @property
    def generate_arn(self):
        if self._generate_arn is None:
            self._generate_arn = functools.partial(
                generate_arn,
                self.get_model().service,
                resource_type=self.get_model().type)
        return self._generate_arn

    def get_arn(self, r):
        return self.generate_arn(r[self.get_model().id].split("/")[-1])

    def augment(self, resources):
        _describe_route53_tags(
            self.get_model(), resources, self.session_factory,
            self.executor_factory, self.retry)
        return resources


def _describe_route53_tags(
        model, resources, session_factory, executor_factory, retry):

    def process_tags(resources):
        client = local_session(session_factory).client('route53')
        resource_map = {}
        for r in resources:
            k = r[model.id]
            if "hostedzone" in k:
                k = k.split("/")[-1]
            resource_map[k] = r

        for resource_batch in chunks(list(resource_map.keys()), 10):
            results = retry(
                client.list_tags_for_resources,
                ResourceType=model.type,
                ResourceIds=resource_batch)
            for resource_tag_set in results['ResourceTagSets']:
                if ('ResourceId' in resource_tag_set and
                        resource_tag_set['ResourceId'] in resource_map):
                    resource_map[resource_tag_set['ResourceId']]['Tags'] = resource_tag_set['Tags']

    with executor_factory(max_workers=2) as w:
        return list(w.map(process_tags, chunks(resources, 20)))


@resources.register('hostedzone')
class HostedZone(Route53Base, QueryResourceManager):

    class resource_type(object):
        service = 'route53'
        type = 'hostedzone'
        enum_spec = ('list_hosted_zones', 'HostedZones', None)
        # detail_spec = ('get_hosted_zone', 'Id', 'Id', None)
        id = 'Id'
        filter_name = None
        name = 'Name'
        date = None
        dimension = None
        universal_taggable = True

    def get_arns(self, resource_set):
        arns = []
        for r in resource_set:
            _id = r[self.get_model().id].split("/")[-1]
            arns.append(self.generate_arn(_id))
        return arns


HostedZone.filter_registry.register('shield-enabled', IsShieldProtected)
HostedZone.action_registry.register('set-shield', SetShieldProtection)


@resources.register('healthcheck')
class HealthCheck(Route53Base, QueryResourceManager):

    class resource_type(object):
        service = 'route53'
        type = 'healthcheck'
        enum_spec = ('list_health_checks', 'HealthChecks', None)
        name = id = 'Id'
        filter_name = None
        date = None
        dimension = None
        universal_taggable = True


@resources.register('rrset')
class ResourceRecordSet(ChildResourceManager):

    class resource_type(object):
        service = 'route53'
        type = 'rrset'
        parent_spec = ('hostedzone', 'HostedZoneId', None)
        enum_spec = ('list_resource_record_sets', 'ResourceRecordSets', None)
        name = id = 'Name'
        filter_name = None
        date = None
        dimension = None


@resources.register('r53domain')
class Route53Domain(QueryResourceManager):

    class resource_type(object):
        service = 'route53domains'
        type = 'r53domain'
        enum_spec = ('list_domains', 'Domains', None)
        name = id = 'DomainName'
        filter_name = None
        date = None
        dimension = None

    permissions = ('route53domains:ListTagsForDomain',)

    def augment(self, domains):
        client = local_session(self.session_factory).client('route53domains')

        def _list_tags(d):
            tags = client.list_tags_for_domain(
                DomainName=d['DomainName'])['TagList']
            d['Tags'] = tags
            return d

        with self.executor_factory(max_workers=1) as w:
            return list(filter(None, w.map(_list_tags, domains)))


@Route53Domain.action_registry.register('tag')
class Route53DomainAddTag(Tag):
    """Adds tags to a route53 domain

    :example:

    .. code-block: yaml

        policies:
          - name: route53-tag
            resource: r53domain
            filters:
              - "tag:DesiredTag": absent
            actions:
              - type: tag
                key: DesiredTag
                value: DesiredValue
    """
    permissions = ('route53domains:UpdateTagsForDomain',)

    def process_resource_set(self, domains, tags):
        client = local_session(
            self.manager.session_factory).client('route53domains')

        for d in domains:
            client.update_tags_for_domain(
                DomainName=d[self.id_key],
                TagsToUpdate=tags)


@Route53Domain.action_registry.register('remove-tag')
class Route53DomainRemoveTag(RemoveTag):
    """Remove tags from a route53 domain

    :example:

    .. code-block: yaml

        policies:
          - name: route53-expired-tag
            resource: r53domain
            filters:
              - "tag:ExpiredTag": present
            actions:
              - type: remove-tag
                tags: ['ExpiredTag']
    """
    permissions = ('route53domains:DeleteTagsForDomain',)

    def process_resource_set(self, domains, keys):
        client = local_session(
            self.manager.session_factory).client('route53domains')

        for d in domains:
            client.delete_tags_for_domain(
                DomainName=d[self.id_key],
                TagsToDelete=keys)


@HostedZone.action_registry.register('enable-query-logging')
class EnableQueryLogging(BaseAction):
    """Enables query logging on a public hosted zone

    :example:

    .. code-block: yaml

        policies:
          - name: enablednsquerylogging
            resource: hostedzone
            filters:
                - type: query-logging-enabled
                state: false
            actions:
                - type: enable-query-logging
                state: true
                logretentiondays: 30
    """
    permissions = ('route53:GetQueryLoggingConfig','route53:GetHostedZone',
        'route53:CreateQueryLoggingConfig','route53:DeleteQueryLoggingConfig',
        'logs:CreateLogGroup','logs:DescribeLogGroups','logs:PutRetentionPolicy')

    schema = type_schema('enable-query-logging', state={'type': 'boolean'},
        logretentiondays={'type': 'number'})

    def process(self, resources):

        client = local_session(self.manager.session_factory).client('route53')
        state = self.data.get('state', False)
        logretentiondays = self.data.get('logretentiondays', 30)
        valid_days = [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653]
        if logretentiondays not in valid_days:
            raise ValueError("logretentiondays must be one of : ", valid_days)

        for r in resources:
            hosted_zone_arn = self.manager.get_arn(r).split("/")[-1]

            # Take no action on Private Zones
            if r['Config']['PrivateZone'] is True:
                continue
            if state:
                # create cloudwatch loggroup if it doesn't exist
                logs_client = local_session(self.manager.session_factory).client('logs')
                log_group_name = '/aws/route53/' + r['Name']
                loggroup_arn = get_loggroup_arn(logs_client, log_group_name)
                if not loggroup_arn:
                    logs_client.create_log_group(logGroupName=log_group_name)
                loggroup_arn = get_loggroup_arn(logs_client, log_group_name)
                logs_client.put_retention_policy(logGroupName=log_group_name,
                    retentionInDays=logretentiondays)
                # create the query logging config
                client.create_query_logging_config(HostedZoneId=hosted_zone_arn,
                    CloudWatchLogsLogGroupArn=loggroup_arn)
            else:
                # delete query logging config
                log_config_id = client.list_query_logging_configs(HostedZoneId=hosted_zone_arn)
                client.delete_query_logging_config(Id=log_config_id['QueryLoggingConfigs'][0]['Id'])


def get_log_enabled_zones(client,zonelist=[],next_token=""):
    kwargs = {}
    if next_token != "":
        kwargs['NextToken'] = next_token
    logged_zones = client.list_query_logging_configs(**kwargs)
    for hz in logged_zones['QueryLoggingConfigs']:
        zonelist.append(hz['HostedZoneId'])
    if 'NextToken' in logged_zones:
        get_log_enabled_zones(client, zonelist,logged_zones['NextToken'])
    return zonelist


def get_loggroup_arn(logs_client, log_group_name):
    log_group = logs_client.describe_log_groups(logGroupNamePrefix=log_group_name)
    if len(log_group['logGroups']) == 0:
        return False
    else:
        return log_group['logGroups'][0]['arn']


@HostedZone.filter_registry.register('query-logging-enabled')
class IsQueryLoggingEnabled(Filter):

    permissions = ('route53:GetQueryLoggingConfig','route53:GetHostedZone')

    schema = type_schema('query-logging-enabled', state={'type': 'boolean'})

    def process(self, resources, event=None):
        client = local_session(self.manager.session_factory).client('route53')

        enabled_zones = get_log_enabled_zones(client)
        state = self.data.get('state', False)
        results = []

        for r in resources:
            host_zone_id = self.manager.get_arn(r).split("/")[-1]
            r['Id'].split("/")[-1] = logging = host_zone_id in enabled_zones
            if logging and state:
                results.append(r)
            elif not logging and not state:
                results.append(r)
        return results
