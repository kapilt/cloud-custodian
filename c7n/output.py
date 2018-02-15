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
"""
Outputs metrics, logs, structured records across
a variety of sources.

See docs/usage/outputs.rst

"""
from __future__ import absolute_import, division, print_function, unicode_literals


from .outputs.fs import DirectoryOutput, S3Output, FSOutput
from .outputs.log import CloudWatchLogOutput
from .outputs.metrics import MetricsOutput, NullMetricsOutput, DEFAULT_NAMESPACE

