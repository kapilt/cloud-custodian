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

class Reachable(Filter):
    """Determine a resource's ability to reach another cidr, ip address,
    or resource on a given set of ports, within or across accounts.

    This filter walks the resource's security groups and subnet associated
    nacls, route tables, and peers.

    The traversal of network infrastructure can be controlled on a fine
    grained basis, with a default of all.

    ```yaml
    policies:
      - name: ec2-reach-dns
        filters:
        - type: connectivity
          target:
            type: cidr
            value: 8.8.8.8/32
            ports: [53]
        - type: connectivity
          target:
            type: rds
            value: [arn, endpoint, name]
            ports: 6543
        - type: connectivity
          target:
            type: ec2
            # check the targets in another account.
            role-assume: %s
            value: [arn, endpoint, name]
            ports: 6543
    ```
    """

    def get_subnets(self, resources):
        self.subnet

    def get_security_groups(self, resources):
        groups = self.sg_filter.get_related(resources)

    def get_route_tables(self, subnets):
        pass

    def get_peers(self, peer_ids):
        pass

    def get_nacls(self, subnets):
        pass

    def initialize(self):
        self.subnet_filter = self.manager.filter_registry.get(
            'subnet')(self.manager.ctx, {})
        self.sg_filter = self.manager.filter_registry.get(
            'security-group')(self.manager.ctx, {})

        from c7n.resources.vpc import (
            NetworkAcl, RouteTable, PeeringConnection)

        self.acls = NetworkAcl(self.manager.ctx, {})
        self.peers = PeeringConnection(self.manager.ctx, {})
        self.routes = RouteTable(self.manager.ctx, {})

    def process(self, resources, event=None):
        self.initialize()
        for r in resources:
            network_blocks = {}
            for k, check in (
                    ('source-security-groups', ''):
                    pass
            self.scan_source_groups(r)

