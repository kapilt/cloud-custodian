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

import pprint
from common import BaseTest


class DiffLibTest(BaseTest):

    def compare_diffs(self, s1, s2):
        print

        import dictdiffer
        diff = list(dictdiffer.diff(s1, s2))
        pprint.pprint(diff)
        print

        from deepdiff import DeepDiff
        diff = DeepDiff(s1, s2, ignore_order=True)
        pprint.pprint(diff)
        print

        from jsonpatch import make_patch
        pprint.pprint(list(make_patch(s1, s2)))
        print

    def test_sg_mods(self):
        factory = self.record_flight_data('test_security_group_revisions_delta')
        client = factory().client('ec2')
        vpc_id = client.create_vpc(CidrBlock="10.42.0.0/16")['Vpc']['VpcId']
        self.addCleanup(client.delete_vpc, VpcId=vpc_id)
        sg_id = client.create_security_group(
            GroupName="allow-access",
            VpcId=vpc_id,
            Description="inbound access")['GroupId']
        self.addCleanup(client.delete_security_group, GroupId=sg_id)

        client.create_tags(
            Resources=[sg_id],
            Tags=[
                {'Key': 'NetworkLocation', 'Value': 'DMZ'},
                {'Key': 'App', 'Value': 'blue-moon'}
            ])
        client.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {'IpProtocol': 'tcp',
                 'FromPort': 443,
                 'ToPort': 443,
                 'IpRanges': [{'CidrIp': '10.42.1.0/24'}]},
                {'IpProtocol': 'tcp',
                 'FromPort': 8080,
                 'ToPort': 8080,
                 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                ])

        s1 = client.describe_security_groups(GroupIds=[sg_id])[
            'SecurityGroups'][0]

        client.create_tags(
            Resources=[sg_id],
            Tags=[
                {'Key': 'App', 'Value': 'red-moon'},
                {'Key': 'Stage', 'Value': 'production'}])
        client.revoke_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {'IpProtocol': 'tcp',
                 'FromPort': 8080,
                 'ToPort': 8080,
                 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}])
        client.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {'IpProtocol': 'tcp',
                 'FromPort': 80,
                 'ToPort': 80,
                 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                ])
        s2 = client.describe_security_groups(GroupIds=[sg_id])[
            'SecurityGroups'][0]

        t_state_sg = TFStateSecurityGroup(s1)
        t_goal_sg = TFResourceSecurityGroup(s2)

        self.compare_diffs(s1, s2)

    def xtest_list_mods(self):

        s1 = {'Description': 'Typical Internet-Facing Security Group',
              'GroupId': 'sg-abcd1234',
              'GroupName': 'TestInternetSG',
              'IpPermissions': [{'FromPort': 53,
                                 'IpProtocol': 'tcp',
                                 'IpRanges': ['10.0.0.0/8'],
                                 'PrefixListIds': [],
                                 'ToPort': 53,
                                 'UserIdGroupPairs': []}],
              'IpPermissionsEgress': [],
              'OwnerId': '123456789012',
              'Tags': [{'Key': 'Value',
                        'Value': 'InternetSecurityGroup'},
                       {'Key': 'Origin', 'Value': 'Name'}],
              'VpcId': 'vpc-1234abcd'}

        s2 = {'Description': 'Typical Internet-Facing Security Group',
                     'GroupId': 'sg-abcd1234',
                     'GroupName': 'TestInternetSG',
                     'IpPermissions': [{'FromPort': 53,
                                        'IpProtocol': 'tcp',
                                        'IpRanges': ['10.0.0.0/8'],
                                        'PrefixListIds': [],
                                        'ToPort': 53,
                                        'UserIdGroupPairs': []}],
                     'IpPermissionsEgress': [],
                     'OwnerId': '123456789012',
                     'Tags': [{'Key': 'Value',
                               'Value': 'InternetSecurityGroup'},
                              {'Key': 'AppId',
                               'Value': 'SomethingGood'},
                              {'Key': 'Origin', 'Value': 'Name'}],
                     'VpcId': 'vpc-1234abcd'}

    def test_list_changes(self):

        s1 = {'Description': 'Typical Internet-Facing Security Group',
              'GroupId': 'sg-abcd1234',
              'GroupName': 'TestInternetSG',
              'IpPermissions': [{'FromPort': 53,
                                 'IpProtocol': 'tcp',
                                 'IpRanges': ['10.0.0.0/8'],
                                 'PrefixListIds': [],
                                 'ToPort': 53,
                                 'UserIdGroupPairs': []}],
              'IpPermissionsEgress': [],
              'OwnerId': '123456789012',
              'Tags': [{'Key': 'Value',
                        'Value': 'InternetSecurityGroup'},
                       {'Key': 'Origin', 'Value': 'Name'}],
              'VpcId': 'vpc-1234abcd'}

        s2 = {'Description': 'Typical Internet-Facing Security Group',
                     'GroupId': 'sg-abcd1234',
                     'GroupName': 'TestInternetSG',
                     'IpPermissions': [{'FromPort': 53,
                                        'IpProtocol': 'tcp',
                                        'IpRanges': ['10.0.0.0/8'],
                                        'PrefixListIds': [],
                                        'ToPort': 80,
                                        'UserIdGroupPairs': []}],
                     'IpPermissionsEgress': [],
                     'OwnerId': '123456789012',
                     'Tags': [{'Key': 'Value',
                               'Value': 'InternetSecurityGroup'},
                              {'Key': 'AppId',
                               'Value': 'SomethingGood'},
                              {'Key': 'Origin', 'Value': 'Name'}],
                     'VpcId': 'vpc-1234abcd'}

