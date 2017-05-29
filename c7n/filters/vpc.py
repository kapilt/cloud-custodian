# Copyright 2016 Capital One Services, LLC
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

from c7n.utils import local_session, type_schema

from .core import Filter, ValueFilter, FilterValidationError
from .related import RelatedResourceFilter


class SecurityGroupFilter(RelatedResourceFilter):
    """Filter a resource by its associated security groups."""
    schema = type_schema(
        'security-group', rinherit=ValueFilter.schema,
        **{'match-resource':{'type': 'boolean'},
           'operator': {'enum': ['and', 'or']}})

    RelatedResource = "c7n.resources.vpc.SecurityGroup"
    AnnotationKey = "matched-security-groups"


class SubnetFilter(RelatedResourceFilter):
    """Filter a resource by its associated subnets."""
    schema = type_schema(
        'subnet', rinherit=ValueFilter.schema,
        **{'match-resource':{'type': 'boolean'},
           'operator': {'enum': ['and', 'or']}})

    RelatedResource = "c7n.resources.vpc.Subnet"
    AnnotationKey = "matched-subnets"


class DefaultVpcBase(Filter):
    """Filter to resources in a default vpc."""
    vpcs = None
    default_vpc = None
    permissions = ('ec2:DescribeVpcs',)

    def match(self, vpc_id):
        if self.default_vpc is None:
            self.log.debug("querying default vpc %s" % vpc_id)
            client = local_session(self.manager.session_factory).client('ec2')
            vpcs = [v['VpcId'] for v
                    in client.describe_vpcs()['Vpcs']
                    if v['IsDefault']]
            if vpcs:
                self.default_vpc = vpcs.pop()
        return vpc_id == self.default_vpc and True or False


class NetworkLocation(Filter):
    """On a network attached resource, determine intersection of
       security-group attributes to subnet attributes.
    """
    schema = type_schema(
        'network-location', key={'type': 'string'}, required=['key'])

    permissions = ('ec2:DescribeSecurityGroups', 'ec2:DescribeSubnets')

    def validate(self):
        rfilters = self.manager.filter_registry.keys()
        if 'subnet' not in rfilters:
            raise FilterValidationError(
                "network-location requires resource subnet filter")
        if 'security-group' not in rfilters:
            raise FilterValidationError(
                "network-location requires resource security-group filter")
        return self

    def process(self, resources, event=None):
        sg_model = self.manager.get_resource_manager('security-group').get_model()
        sg = self.manager.filter_registry.get('security-group')({}, self.manager)
        related_sg = sg.get_related(resources)

        subnet_model = self.manager.get_resource_manager('subnet').get_model()
        subnet = self.manager.filter_registry.get('subnet')({}, self.manager)
        related_subnet = subnet.get_related(resources)

        vf = self.manager.filter_registry.get('value')({}, self.manager)
        key = self.data.get('key')
        results = []

        for r in resources:
            resource_sgs = [related_sg[sid] for sid in sg.get_related_ids([r])]
            resource_subnets = [
                related_subnet[sid] for sid in subnet.get_related_ids([r])]

            subnet_values = {
                rsub[subnet_model.id]: subnet.get_resource_value(key, rsub)
                for rsub in resource_subnets}

            if None in subnet_values.values():
                r.setdefault('c7n:NetworkLocation', []).append({
                    'reason': 'SubnetLocationAbsent',
                    'subnets': subnet_values})
            subnet_space = set(filter(None, subnet_values.values()))

            if len(subnet_space) > 1:
                r.setdefault('c7n:NetworkLocation', []).append({
                    'reason': 'SubnetLocationCardinality',
                    'subnets': subnet_values})

            sg_values = {
                rsg[sg_model.id]: sg.get_resource_value(key, rsg)
                for rsg in resource_sgs}
            if None in sg_values.values():
                r.setdefault('c7n:NetworkLocation', []).append({
                    'reason': 'SecurityGroupLocationAbsent',
                    'security-groups': sg_values})
    
            sg_space = set(filter(None, sg_values.values()))
            if len(sg_space) > 1:
                r.setdefault('c7n:NetworkLocation', []).append({
                    'reason': 'SecurityGroupLocationCardinality',
                    'security-groups': sg_values})

            if sg_space != subnet_space:
                r.setdefault('c7n:NetworkLocation', []).append({
                    'reason': 'LocationMismatch',
                    'subnets': subnet_values,
                    'security-groups': sg_values})

            r_value = vf.get_resource_value(key, r)
            if r_value is None:
                r.setdefault('c7n:NetworkLocation', []).append({
                    'reason': 'ResourceLocationAbsent',
                    'resource': r_value})
            elif r_value not in sg_space:
                r.setdefault('c7n:NetworkLocation', []).append({
                    'reason': 'ResourceLocationMismatch',
                    'subnets': subnet_values,
                    'resource': r_value,
                    'security-groups': sg_values})

            if 'c7n:NetworkLocation' in r:
                results.append(r)

        return results
