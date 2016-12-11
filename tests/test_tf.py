import os
from c7n.delta import tf

from common import BaseTest


class TerraformSecurityGroup(BaseTest):

    def setup_network(self):
        factory = self.record_flight_data('test_delta_network_base')
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
        return factory, vpc_id, s1

    @staticmethod
    def get_tf_bin():
        for t in os.environ.get('PATH').split(':'):
            tbin = os.path.join(t, 'terraform')
            if os.path.exists(tbin) and os.access(tbin, os.X_OK):
                return tbin
        raise RuntimeError("No terraform binary found")

    def test_tf_state_render(self):
        factory, vpc_id, sg = self.setup_network()
        tform = tf.Terraform(self.get_tf_bin())
        self.maxDiff = None
        self.assertEqual(
            tform.render_state(sg),
            {'outputs': {},
             'path': ['root'],
             'resources': {
                 'aws_security_group.sg_target': {
                     'depends_on': [],
                     'primary': {
                         'attributes': {
                             'description': 'inbound access',
                             'egress.#': '1',
                             'egress.482069346.cidr_blocks.#': '1',
                             'egress.482069346.cidr_blocks.0': '0.0.0.0/0',
                             'egress.482069346.from_port': '0',
                             'egress.482069346.prefix_list_ids.#': '0',
                             'egress.482069346.protocol': '-1',
                             'egress.482069346.security_groups.#': '0',
                             'egress.482069346.self': 'false',
                             'egress.482069346.to_port': '0',
                             'id': sg['GroupId'],
                             'ingress.#': '2',
                             'ingress.1077900546.cidr_blocks.#': '1',
                             'ingress.1077900546.cidr_blocks.0': '10.42.1.0/24',
                             'ingress.1077900546.from_port': '443',
                             'ingress.1077900546.prefix_list_ids.#': '0',
                             'ingress.1077900546.protocol': 'tcp',
                             'ingress.1077900546.security_groups.#': '0',
                             'ingress.1077900546.self': 'false',
                             'ingress.1077900546.to_port': '443',
                             'ingress.516175195.cidr_blocks.#': '1',
                             'ingress.516175195.cidr_blocks.0': '0.0.0.0/0',
                             'ingress.516175195.from_port': '8080',
                             'ingress.516175195.prefix_list_ids.#': '0',
                             'ingress.516175195.protocol': 'tcp',
                             'ingress.516175195.security_groups.#': '0',
                             'ingress.516175195.self': 'false',
                             'ingress.516175195.to_port': '8080',
                             'name': 'allow-access',
                             'owner_id': '644160558196',
                             'tags.%': '2',
                             'tags.App': 'blue-moon',
                             'tags.NetworkLocation': 'DMZ',
                             'vpc_id': vpc_id},
                         'id': sg['GroupId'],
                         'meta': {},
                         'tainted': False},
                     'type': 'aws_security_group'}}})

    def xtest_tf_import_sg(self):
        factory, vpc_id, sg = self.setup_network()
        tform = tf.Terraform(self.get_tf_bin())
        state = tform.import_resource(sg)
        self.assertEqual(state, {
            u'depends_on': [],
            u'deposed': [],
            u'primary': {
                u'attributes': {
                    u'description': u'inbound access',
                    u'egress.#': u'1',
                    u'egress.482069346.cidr_blocks.#': u'1',
                    u'egress.482069346.cidr_blocks.0': u'0.0.0.0/0',
                    u'egress.482069346.from_port': u'0',
                    u'egress.482069346.prefix_list_ids.#': u'0',
                    u'egress.482069346.protocol': u'-1',
                    u'egress.482069346.security_groups.#': u'0',
                    u'egress.482069346.self': u'false',
                    u'egress.482069346.to_port': u'0',
                    u'id': sg['GroupId'],
                    u'ingress.#': u'2',
                    u'ingress.3217066750.cidr_blocks.#': u'1',
                    u'ingress.3217066750.cidr_blocks.0': u'10.42.1.0/24',
                    u'ingress.3217066750.from_port': u'443',
                    u'ingress.3217066750.protocol': u'tcp',
                    u'ingress.3217066750.security_groups.#': u'0',
                    u'ingress.3217066750.self': u'false',
                    u'ingress.3217066750.to_port': u'443',

                    u'ingress.516175195.cidr_blocks.#': u'1',
                    u'ingress.516175195.cidr_blocks.0': u'0.0.0.0/0',
                    u'ingress.516175195.from_port': u'8080',
                    u'ingress.516175195.protocol': u'tcp',
                    u'ingress.516175195.security_groups.#': u'0',
                    u'ingress.516175195.self': u'false',
                    u'ingress.516175195.to_port': u'8080',
                    u'name': u'allow-access',
                    u'owner_id': u'644160558196',
                    u'tags.%': u'2',
                    u'tags.App': u'blue-moon',
                    u'tags.NetworkLocation': u'DMZ',
                    u'vpc_id': vpc_id},
                u'id': sg['GroupId'],
                u'meta': {},
                u'tainted': False},
            u'provider': u'aws',
            u'type': u'aws_security_group'})


class Terraform(BaseTest):
    pass

