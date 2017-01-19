
from urlparse import urlparse

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.vendored import requests


from c7n.credentials import assumed_session
from c7n.filters import Filter
from c7n.utils import local_session, type_schema, get_account_id


class Locked(Filter):
    """Has the resource been locked using sphere11
    """
    permissions = ('iam:ListRoles', 'sts:AssumeRole')

    schema = type_schema(
        'locked',
        role={'type': 'string'},
        endpoint={'type': 'string'},
        region={'type': 'string'},
        required=('endpoint',))

    def process(self, resources):
        session = local_session(self.manager.session_factory)
        if self.data.get('role'):
            session = assumed_session(
                self.data.get('role'), 'CustodianSphere11', session)

        credentials = session.get_credentials()
        endpoint = self.data['endpoint'].rstrip('/')
        region = self.data.get('region', 'us-east-1')
        auth = SignatureAuth(credentials, region, 'execute-api')
        account_id = get_account_id(session)

        m = self.manager.get_model()

        for r in resources:
            params = {'parent_id': self.get_parent_id(r, account_id)}
            result = requests.get("%s/%s/locks/%s" % (
                endpoint,
                account_id,
                r[m.id]), params=params, auth=auth)
            data = result.json()
            if data['LockStatus'] == 'locked':
                pass

    def get_parent_id(self, resource, account_id):
        return account_id


class SignatureAuth(requests.auth.AuthBase):
    """AWS V4 Request Signer for Requests.
    """

    def __init__(self, credentials, region, service):
        self.credentials = credentials
        self.region = region
        self.service = service

    def __call__(self, r):
        url = urlparse(r.url)
        path = url.path or '/'
        qs = url.query and '?%s' % url.query or ''
        safe_url = url.scheme + '://' + url.netloc.split(':')[0] + path + qs
        request = AWSRequest(
            method=r.method.upper(), url=safe_url, data=r.body)
        SigV4Auth(
            self.credentials, self.service, self.region).add_auth(request)
        r.headers.update(dict(request.headers.items()))
        return r
