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


class AdvisorASGValidity(TrustedAdvisorBase):

    category = "fault_tolerance"
    check_id = "8CNsSllI5v"
    check_metadata = [
        "Region", "Auto Scaling Group Name", "Launch Configuration Name",
        "Resource Type", "Resource Name", "Status", "Reason"]


class AdvisorRDSUnderUtilized(TrustedAdvisorBase):

    category = "cost_optimizing"
    check_id = "Ti39halfu8"
    check_metadata = [
        "Region", "DB Instance Name", "Multi-AZ",
        "Instance Type", "Storage Provisioned (GB)",
        "Days Since Last Connection", "Estimated Monthly Savings (On Demand)"]


class CloudTrailLogging(TrustedAdvisorBase):

    category = "security"
    check_id = "vjafUGJ9H0"
    check_metadata = [
        "Region", "Trail Name", "Logging Status", "Bucket Name", "Last Delivery Error", "Status"]


class ListenerSecurity(TrustedAdvisorBase):

    category = "security"
    check_id = "a2sEc6ILx"
    check_metadata = [
        "Region", "Load Balancer Name", "Status", "Security Group IDs", "Reason"]


class ELBConnectionDraining(TrustedAdvisorBase):

    category = "fault_tolerance"
    check_id = "7qGXsKIUw"
    check_metadata = ["Region", "Load Balancer Name", "Status", "Reason"]


class EC2VolumePerformance(TrustedAdvisorBase):

    category = "performance"
    check_id = "Bh2xRR2FGH"
    check_metadata = [
        "Region",
        "Instance ID",
        "Instance Type",
        "Status",
        "Time Near Maximum"]


class RedshiftUnderUtilized(TrustedAdvisorBase):

    category = "cost_optimizing"
    check_id = "G31sQ1E9U"
    check_metadata = [
        "Status", "Region", "Cluster",
        "Instance Type", "Reason", "Estimated Monthly Savings"]


class PublicEBSSnapshots(TrustedAdvisorBase):

    category = 'security'
    check_id = 'ePs02jT06w'
    check_metadata = [
        "Region", "Volume ID", "Snapshot ID", "Description"]


class PublicRDSSnapshots(TrustedAdvisorBase):

    category = 'security'
    check_id = 'rSs93HQwa1'
    check_metadata = [
        "Region", "DB Instance or Cluster ID", "Snapshot ID"]


class Route53OrphanHealthChecks(TrustedAdvisorBase):

    category = "fault_tolerance"
    check_id = "Cb877eB72b",
    check_metadata = [
        "Hosted Zone Name",
        "Hosted Zone ID",
        "Resource Record Set Name",
        "Resource Record Set Type",
        "Resource Record Set Identifier"]


class ServiceLimit(TrustedAdvisorBase):

    category = 'service_limit'
    check_metadata = [
        "Region", "Service", "Limit Name",
        "Limit Amount", "Current Usage", "Status"]

    limit_checks = {
        'Autoscaling': {
            'launch-config': 'aW7HH0l7J9',
            'asg': 'fW7HH0l7J9'
        },
        'CloudFormation': {
            'stacks': 'gW7HH0l7J9',
        },
        'Kinesis': {
            'shards': 'bW7HH0l7J9'
        },
        'EC2': {
            'instance-type': '0Xc6LMYG8P',
            'elastic-ip': 'aW9HH0l8J6',
        },
        'EBS': {
            'iops': 'gI7MM0l7J9',
            'volume': 'fH7LL0l7J9',
            'gp2': 'cG7HH0l7J9'
        }
    }


class EC2ElasticIPServiceLimit(ServiceLimit):

    check_id = 'aW9HH0l8J6'


class KinesisShardsServiceLimit(ServiceLimit):

    check_id = 'bW7HH0l7J9'


class CloudFormationStackServiceLimit(ServiceLimit):

    check_id = 'gW7HH0l7J9'


class EBSSnapshotServiceLimit(ServiceLimit):

    check_id = 'eI7KK0l7J9'


class ASGLaunchConfigServiceLimit(ServiceLimit):

    check_id = 'aW7HH0l7J9'


class ASGServiceLimit(ServiceLimit):

    check_id = 'fW7HH0l7J9'


class SESServiceLimit(ServiceLimit):

    check_id = 'hJ7NN0l7J9'
