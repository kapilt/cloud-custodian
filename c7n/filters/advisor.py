from datetime import datetime, timedelta
from dateutil.parser import parse as parse_date
from dateutil.tz import tzutc

from .core import Filter
from c7n.utils import type_schema, local_session


class TrustedAdvisorBase(Filter):
    """Support trusted advisors filters on resources.
    """

    schema = type_schema(
        'trusted-advisor',
        {'refresh-period': {'type': 'float'}})

    check_id = None
    language = 'en'
    permissions = ('support:DescribeTrustedAdvisorCheckResult',)

    def process(self, resources):
        resource_ids = self.get_check_resources()
        resources = self.filter_check_resources(resources, resource_ids)
        return resources

    def filter_check_resources(self, resources, resource_ids):
        m = self.manager.get_model()
        rids = set(resource_ids)
        return [r for r in resources if r[m.id] in rids]

    def get_check_resources(self):
        client = local_session(
            self.manager.session_factory).client('support')
        checks = client.describe_trusted_advisor_check_result(
            checkId=self.check_id,
            language=self.language)['result']
        self.check_advisor_refresh(client, checks)
        return self.extract_check_resources(checks)
    
    def check_advisor_refresh(self, client, checks):
        delta = timedelta(self.data.get('refresh-period', 1))
        check_date = parse_date(checks['timestamp'])
        if datetime.now(tz=tzutc()) - delta > check_date:
            client.refresh_trusted_advisor_check(checkId=self.check_id)

    def extract_check_resources(self, checks):
        raise NotImplemented()


class AdvisorElbListenerSecurity(TrustedAdvisorBase):

    check_id = 'a2sEc6ILx'
    check_metadata = [
        u'Region', u'Load Balancer Name', u'Load Balancer Port',
        u'Status', u'Reason']

    # if region
    def extract_check_resources(self, checks):
        return [c[1] for c in checks]


class AdvisorELBSecurityGroups(TrustedAdvisorBase):

    check_id = 'xSqX82fQu'
    check_metadata = [
        u'Region', u'Load Balancer Name', u'Status',
        u'Security Group IDs', u'Reason']
    
    def extract_check_resources(self, checks):
        return [c[1] for c in checks]

    
