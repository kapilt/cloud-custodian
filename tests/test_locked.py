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

import time

from .common import BaseTest, Bag

from botocore.vendored import requests
from c7n.filters.locked import SignatureAuth
from c7n.filters import locked

class LockedTests(BaseTest):

    def xtest_auth(self):
        auth = SignatureAuth(
            Bag(secret_key='foo', access_key='bar', method='env', token=None),
            'us-east-1',
            'execute-api')

        req = requests.Request('POST', 'http://example.com', auth=auth)
        prepped = req.prepare()
        self.assertTrue(
            prepped.headers['Authorization'].startswith(
                'AWS4-HMAC-SHA256 Credential=bar/'))

    def xtest_unlocked(self):
        def get(*args, **kw):
            return Bag({'json': lambda : {'LockStatus': 'unlocked'}})
        self.patch(locked.requests, 'get', get)
        p = self.load_policy({
            'name': 'ltest',
            'resource': 'security-group',
            'filters': [
                {'type': 'locked', 'endpoint': 'http://example.com/bar'}]})
        f_locked = p.resource_manager.filters[0]
        result = f_locked.process([
            {'GroupId': 'sg-123', 'VpcId': 'vpc-123'}])
        self.assertEqual(len(result), 0)

    def xtest_status_error(self):
        def get(*args, **kw):
            return Bag({'json': lambda : {'Message': 'unknown'}})
        self.patch(locked.requests, 'get', get)
        p = self.load_policy({
            'name': 'ltest',
            'resource': 'security-group',
            'filters': [
                {'type': 'locked', 'endpoint': 'http://example.com/bar'}]})
        f_locked = p.resource_manager.filters[0]
        self.assertRaises(
            RuntimeError,
            f_locked.process,
            [{'GroupId': 'sg-123', 'VpcId': 'vpc-123'}])

    def xtest_locked(self):
        def get(*args, **kw):
            return Bag({'json': lambda : {
                'LockStatus': 'locked', 'RevisionDate': time.time()}})
        self.patch(locked.requests, 'get', get)
        p = self.load_policy({
            'name': 'ltest',
            'resource': 'security-group',
            'filters': [
                {'type': 'locked', 'endpoint': 'http://example.com/bar'}]})
        f_locked = p.resource_manager.filters[0]
        result = f_locked.process([
            {'GroupId': 'sg-123', 'VpcId': 'vpc-123'}])
        self.assertEqual(len(result), 1)

