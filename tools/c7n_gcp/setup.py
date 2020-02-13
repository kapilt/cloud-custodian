# Automatically generated from pyproject.toml
# flake8: noqa
# -*- coding: utf-8 -*-
from setuptools import setup

packages = \
['c7n_gcp', 'c7n_gcp.actions', 'c7n_gcp.filters', 'c7n_gcp.resources']

package_data = \
{'': ['*']}

install_requires = \
['argcomplete==1.11.1',
 'attrs==19.3.0',
 'boto3==1.11.12',
 'botocore==1.14.12',
 'c7n==0.8.46.1',
 'cachetools==4.0.0',
 'certifi==2019.11.28',
 'chardet==3.0.4',
 'docutils==0.15.2',
 'google-api-core==1.16.0',
 'google-api-python-client==1.7.11',
 'google-auth-httplib2==0.0.3',
 'google-auth==1.11.0',
 'google-cloud-core==1.3.0',
 'google-cloud-logging==1.14.0',
 'google-cloud-monitoring==0.34.0',
 'googleapis-common-protos==1.51.0',
 'grpcio==1.26.0',
 'httplib2==0.17.0',
 'idna==2.8',
 'importlib-metadata==1.5.0; python_version < "3.8"',
 'jmespath==0.9.4',
 'jsonpatch==1.25',
 'jsonpointer==2.0',
 'jsonschema==3.2.0',
 'protobuf==3.11.3',
 'pyasn1-modules==0.2.8',
 'pyasn1==0.4.8',
 'pyrsistent==0.15.7',
 'python-dateutil==2.8.1',
 'pytz==2019.3',
 'pyyaml==5.3',
 'ratelimiter==1.2.0.post0',
 'requests==2.22.0',
 'retrying==1.3.3',
 'rsa==4.0',
 's3transfer==0.3.3',
 'six==1.14.0',
 'tabulate==0.8.6',
 'uritemplate==3.0.1',
 'urllib3==1.25.8',
 'zipp==2.1.0; python_version < "3.8"']

setup_kwargs = {
    'name': 'c7n-gcp',
    'version': '0.3.8',
    'description': 'Cloud Custodian - Google Cloud Provider',
    'long_description': '# Custodian GCP Support\n\nStatus - Alpha\n\n# Features\n\n - Serverless ✅\n - Api Subscriber ✅\n - Metrics ✅\n - Resource Query ✅\n - Multi Account (c7n-org) ✅\n\n# Getting Started\n\n\n## via pip\n\n```\npip install c7n_gcp\n```\n\nBy default custodian will use credentials associated to the gcloud cli, which will generate\nwarnings per google.auth (https://github.com/googleapis/google-auth-library-python/issues/292)\n\nThe recommended authentication form for production usage is to create a service account and\ncredentials, which will be picked up via by the custodian cli via setting the\n*GOOGLE_APPLICATION_CREDENTIALS* environment variable.\n\n\n# Serverless\n\nCustodian supports both periodic and api call events for serverless policy execution.\n',
    'author': 'Cloud Custodian Project',
    'author_email': 'https://github.com/cloud-custodian/cloud-custodian',
    'maintainer': None,
    'maintainer_email': None,
    'url': None,
    'packages': packages,
    'package_data': package_data,
    'install_requires': install_requires,
    'python_requires': '>=3.6,<4.0',
}


setup(**setup_kwargs)
