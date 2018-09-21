# Copyright 2018 Capital One Services, LLC
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
#

from c7n.utils import type_schema

from .method import MethodFilter


class IamAccess(MethodFilter):
    """
    """

    schema = type_schema(
        'iam-policy',
        scope={'enum': ['binding', 'member']})

    method_spec = {
        'op': 'getIamPolicy',
        'annotation_key': 'c7n:iam-policy'}

    def get_resource_params(self, m, r):
        pass
