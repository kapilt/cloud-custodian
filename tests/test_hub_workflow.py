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
"""Meta check on ci files being valid, as some validation is lazy.
"""
from jsonschema import Draft7Validator
import requests
import os
import pytest

from pathlib import Path


# only test in ci as by default tests run offline, and we're downloading
# a schema.
@pytest.mark.skipif("GITHUB_ACTIONS" not in os.environ, reason="validates in ci")
def test_validate_github_workflows():
    schema = requests.get('http://json.schemastore.org/github-workflow').json()
    validator = Draft7Validator(schema)
    workflow_dir = Path('.github/workflows')
    for f in workflow_dir.glob('*yml'):
        validator.validate(f.read_text())


