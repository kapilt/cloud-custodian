# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from concurrent.futures import as_completed

from c7n.filters import Filter
from c7n.actions import Action
from c7n.manager import resources
from c7n.query import QueryResourceManager, TypeInfo
from c7n.utils import local_session, type_schema, get_retry
from c7n.tags import RemoveTag, Tag, TagDelayedAction, TagActionFilter


@resources.register('service-quota')
class ServiceQuota(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'service-quotas'
        enum_spec = ('list_services', 'Services', None)
        id = 'QuotaCode'
        arn = 'QuotaArn'
        name = 'QuotaName'

    def augment(self, resources):
        client = local_session(self.session_factory).client('service-quotas')
        retry = get_retry(('TooManyRequestsException',))

        def get_quotas(client, s):
            quotas = {}
            token = None
            while True:
                response = retry(client.list_service_quotas, ServiceCode=s['ServiceCode'])
                rquotas = {q['QuotaCode']: q for q in response['Quotas']}
                token = response.get('NextToken')
                new = set(rquotas) - set(quotas)
                quotas.update(rquotas)

                if token is None:
                    break
                # ssm, ec2, kms have bad behaviors.
                elif token and not new:
                    break
                
            return quotas.values()

        results = []
        with self.executor_factory(max_workers=3) as w:
            futures = {}
            for r in resources:
                futures[w.submit(get_quotas, client, r)] = r

            for f in as_completed(futures):
                if f.exception():
                    raise f.exception()
                results.extend(f.result())

        return results


class History(Filter):

    schema = type_schema('history')


class Increase(Action):

    schema = type_schema('increase')



