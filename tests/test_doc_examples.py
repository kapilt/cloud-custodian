# Copyright 2019 Capital One Services, LLC
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
import itertools
import os
import yaml

from c7n.provider import resources
from .common import BaseTest

try:
    import pytest
    skipif = pytest.mark.skipif
except ImportError:
    skipif = lambda func, reasion="": func  # noqa E731


def get_doc_examples():
    policies = []
    for resource_name, v in resources().items():
        for k, cls in itertools.chain(v.filter_registry.items(), v.action_registry.items()):
            if not cls.__doc__:
                continue
            # split on yaml and new lines
            split_doc = [x.split('\n\n') for x in cls.__doc__.split('yaml')]
            for item in itertools.chain.from_iterable(split_doc):
                if 'policies:\n' in item:
                    policies.append((item, resource_name, cls.type))
    return policies


class DocExampleTest(BaseTest):

    @skipif(
        # Okay slightly gross, basically if we're explicitly told via env var to run doc tests
        # do it.
        (os.environ.get("C7N_TEST_DOC") not in ('yes', 'true')
         or
         # Or for ci to avoid some tox pain, we'll auto configure here to run the py3.6 test
         # runner.
         os.environ.get('C7N_TEST_RUN') and sys.version.major == 3 and sys.version.minor == 6)
            reason="Doc tests must be explicitly enabled with C7N_DOC_TEST")
    def test_doc_examples(self):
        policies = []
        idx = 1
        for ptext, resource_name, el_name in get_doc_examples():
            data = yaml.safe_load(ptext)
            for p in data.get('policies', []):
                # Give each policy a unique name so that we do
                p['name'] = "%s-%s-%s-%d" % (resource_name, el_name, p.get('name', 'unknown'), idx)
                policies.append(p)
                idx += 1
        self.load_policy_set({'policies': policies})
