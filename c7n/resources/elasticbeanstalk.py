# Copyright 2015-2017 Capital One Services, LLC
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

from c7n.filters import FilterRegistry, AgeFilter, OPERATORS
from c7n.manager import resources
from c7n.query import QueryResourceManager
from c7n.utils import type_schema

eb_env_filters = FilterRegistry('elasticbeanstalk-environment.filters')

@resources.register('elasticbeanstalk')
class ElasticBeanstalk(QueryResourceManager):

    class resource_type(object):
        service = 'elasticbeanstalk'
        enum_spec = ('describe_applications', 'Applications', None)
        name = "ApplicationName"
        id = "ApplicationName"
        dimension = None
        default_report_fields = (
            'ApplicationName',
            'DateCreated',
            'DateUpdated'
        )
        filter_name = 'ApplicationNames'
        filter_type = 'list'

@resources.register('elasticbeanstalk-environment')
class ElasticBeanstalkEnvironment(QueryResourceManager):
    """ Resource manager for Elasticbeanstalk Environments
    """

    class resource_type(object):
        service = 'elasticbeanstalk'
        enum_spec = ('describe_environments', 'Environments', None)
        name = id = "EnvironmentName"
        dimension = None
        default_report_fields = (
            'EnvironmentName',
            'DateCreated',
            'DateUpdated',
            )
        filter_name = 'EnvironmentNames'
        filter_type = 'list'

    filter_registry = eb_env_filters

@eb_env_filters.register('environment-uptime')
class EnvironmentUptimeFilter(AgeFilter):
    """Elastic Beanstalk Envrionment Uptime filter

    Filters Elastic Beanstalk Environments based on days since DateCreated.

    :Example:

    .. code-block: yaml

        policies:
          - name: 'eb-envs-two-days-or-older',
            resource: 'elasticbeanstalk-environment',
            filters:
              - type: environment-uptime
                days: 2
                op: greater-than
    """

    date_attribute = "DateCreated"
    schema = type_schema(
        'environment-uptime',
        op={'type': 'string', 'enum': list(OPERATORS.keys())},
        days={'type': 'number'})
