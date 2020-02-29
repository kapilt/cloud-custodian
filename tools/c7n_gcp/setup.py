# Automatically generated from poetry/pyproject.toml
# -*- coding: utf-8 -*-
from setuptools import setup

packages = \
['c7n_gcp', 'c7n_gcp.actions', 'c7n_gcp.filters', 'c7n_gcp.resources']

package_data = \
{'': ['*']}

install_requires = \
['c7n',
 'google-api-python-client>=1.7,<2.0',
 'google-auth>=1.11.0,<2.0.0',
 'google-cloud-logging>=1.14,<2.0',
 'google-cloud-monitoring>=0.34.0,<0.35.0',
 'ratelimiter>=1.2.0,<2.0.0',
 'retrying>=1.3.3,<2.0.0']

setup_kwargs = {
    'name': 'c7n-gcp',
    'version': '0.3.8',
    'description': 'Cloud Custodian - Google Cloud Provider',
    'long_description': '# Custodian GCP Support\n\nStatus - Alpha\n\n# Features\n\n - Serverless ✅\n - Api Subscriber ✅\n - Metrics ✅\n - Resource Query ✅\n - Multi Account (c7n-org) ✅\n\n# Getting Started\n\n\n## via pip\n\n```\npip install c7n_gcp\n```\n\nBy default custodian will use credentials associated to the gcloud cli, which will generate\nwarnings per google.auth (https://github.com/googleapis/google-auth-library-python/issues/292)\n\nThe recommended authentication form for production usage is to create a service account and\ncredentials, which will be picked up via by the custodian cli via setting the\n*GOOGLE_APPLICATION_CREDENTIALS* environment variable.\n\n\n# Serverless\n\nCustodian supports both periodic and api call events for serverless policy execution.\n',
    'author': 'Cloud Custodian Project',
    'author_email': 'https://github.com/cloud-custodian/cloud-custodian',
    'maintainer': None,
    'maintainer_email': None,
    'url': 'https://cloudcustodian.io',
    'packages': packages,
    'package_data': package_data,
    'install_requires': install_requires,
    'python_requires': '>=3.6,<4.0',
}


setup(**setup_kwargs)
