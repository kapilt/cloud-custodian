# Copyright 2019 Amazon.com, Inc. or its affiliates.
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

import logging
import os

import click
import jsonschema

from c7n.credentials import SessionFactory
from c7n.mu import custodian_archive, zinfo, LayerPublisher
from c7n import version


@click.group()
@click.pass_context
def cli(ctx):
    """custodian runtime cli"""
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger('botocore').setLevel(logging.INFO)
    logging.getLogger('urllib3').setLevel(logging.INFO)


@cli.command()
@click.option('-r', '--region', required=True)
def install(region):
    """install runtime"""
    factory = SessionFactory(region=region)
    publisher = RuntimePublisher(factory, 'us-east-1')
    publisher.publish()


class RuntimePublisher(LayerPublisher):

    default_packages = (
        'jsonschema',
        'yaml',
        'six',
        'attr',
        'pyrsistent',
        'dateutil',
        'jmespath',
        'boto3',
        'botocore',
        'urllib3',
        's3transfer')

    runtime = 'provided'

    def __init__(self, session_factory, region=None):
        self.session_factory = session_factory
        self.region = region

    def get_archive(self, packages):
        archive = custodian_archive(packages, prefix='python')

        # jsonschema looks at its pkg metadata for version info
        archive.add_directory(
            os.path.join(
                os.path.dirname(os.path.dirname(jsonschema.__file__)),
                "jsonschema-%s.dist-info" % jsonschema.__version__))

        # include executable bootstrap
        bootstrap_path = os.path.join(
            os.path.dirname(__file__), 'bootstrap.py')
        info = zinfo('bootstrap')
        info.external_attr = 0o755 << 16
        archive.add_file(bootstrap_path, info, no_prefix=True)

        archive.close()
        return archive

    def get_layer_name(self, packages):
        return "c7n-runtime-{}".format(version.version.replace('.', '_'))
