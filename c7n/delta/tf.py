"""Terraform Plan/Apply and Resource Adapters
"""

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import zlib


class ResourceTFStateAdapter(object):

    def __init__(self, resource):
        self.resource = resource

    def render_module(self, path='root'):
        raise NotImplementedError()


class ResourceTFResourceAdapter(object):

    def render_resource():
        raise NotImplementedError()


@contextlib.contextmanager
def TemporaryDirectory():
    try:
        tdir = tempfile.mkdtemp()
        yield tdir
    except:
        shutil.rmtree(tdir)
        raise
    else:
        shutil.rmtree(tdir)


class Terraform(object):

    def __init__(self, bin_path, state_import=False):
        self.bin_path = bin_path
        self.state_import = state_import

    def diff(self, goal, state):
        plan = self.run_delta_op(goal, state)
        return plan

    def show(self, goal, state):
        output = self.diff(goal, state)
        with TemporaryDirectory() as tempdir:
            with tempfile.NamedTemporaryFile(dir=tempdir) as plan_fh:
                plan_fh.write(output)
                return subprocess.check_output(
                    self.bin_path, "show", plan_fh.name)

    def apply(self, goal, state):
        output = self.diff(goal, state)
        with TemporaryDirectory() as tempdir:
            with tempfile.NamedTemporaryFile(dir=tempdir) as plan_fh:
                plan_fh.write(output)
                return subprocess.check_output(
                    self.bin_path, "apply", plan_fh.name, cwd=tempdir)

    def import_resource(self, resource):
        resource_type, rname, rid = self.get_resource_info(resource)
        state_id = "%s.%s" % (resource_type, rname)

        with TemporaryDirectory() as tempdir:
            print "tempdir", tempdir
            subprocess.check_output([
                self.bin_path, "import",
                state_id,
                rid, # resource id
            ], cwd=tempdir)

            with open(os.path.join(tempdir, 'terraform.tfstate')) as fh:
                state = json.load(fh)
                return state['modules'][0]['resources'][state_id]

    def get_resource_info(self, resource):
        return "aws_security_group", resource['GroupId'], resource['GroupId']

    def run_delta_op(self, goal, state, refresh=False):
        rendered_goal = self.render_goal(goal)

        if self.state_import is False:
            rendered_state = self.render_state(state)
        elif self.state_import is True:
            rendered_state = self.import_resource(state)
        else:
            rendered_state = self.state_import

        with TemporaryDirectory() as tempdir:
            with tempfile.NamedTemporaryFile(
                    dir=tempdir, suffix='.tf') as goal_fh:
                with tempfile.NamedTemporaryFile(dir=tempdir) as state_fh:
                    json.dump(rendered_state, state_fh, indent=2)
                    json.dump(rendered_goal, goal_fh, indent=2)
                    subprocess.check_output([
                        self.bin_path, "plan"
                        "-state", state_fh.name,
                        '-out', 'tf.plan',
                        '-refresh', str(refresh).lower()
                    ])
                    
    def render_goal(self, goal):
        return TFResourceSecurityGroup(goal).render_resource()

    def render_state(self, state):
        return TFStateSecurityGroup(state).render_module()


class TFSecurityGroupBase(object):

    RULE_ATTRS = (
        ('cidr_blocks', 'IpRanges', 'CidrIp'),
        # terraform doesn't seem to support cross account/vpc sg rules .7.13
        ('prefix_list_ids', 'PrefixListIds', 'PrefixListId'),
        ('security_groups', 'UserIdGroupPairs', 'GroupId'),
    )

    def render_attributes(self):
        attributes = {
            "id": self.resource['GroupId'],
            "name": self.resource['GroupName'],
            "owner_id": self.resource['OwnerId'],
            "description": self.resource['Description'],
            "vpc_id": self.resource['VpcId']
        }
        return attributes

    def format_goal_rule(self, prefix, rule):
        pass

    def format_state_rule(self, prefix, rule):
        code = self.compute_rule_hash(rule)
        f = {}
        for k, a, ke in self.RULE_ATTRS:
            v = rule.get(a, ())
            f["%s.%s.%s.#" % (prefix, code, k)] = str(len(v))
            for idx, e in enumerate(v):
                f["%s.%s.%s.%d" % (prefix, code, k, idx)] = e[ke]
        f["%s.%s.%s" % (prefix, code, 'protocol')] = str(rule['IpProtocol'])
        f["%s.%s.%s" % (prefix, code, 'self')] = 'false'
        f["%s.%s.%s" % (prefix, code, 'from_port')] = str(
            rule.get('FromPort', 0))
        f["%s.%s.%s" % (prefix, code, 'to_port')] = str(rule.get('ToPort', 0))
        return f

    def compute_rule_hash(self, rule):
        p = convert_protocol(rule.get('IpProtocol', "-1"))
        buf = "%d-%d-%s-%s-" % (
            rule.get('FromPort', 0),
            rule.get('ToPort', 0),
            p,
            "false")
        for k, a, ke in self.RULE_ATTRS:
            ev = [e[ke] for e in rule[a]]
            ev.sort()
            for e in ev:
                buf += "%s-" % e
        return abs(zlib.crc32(buf))


# protocolForValue
def convert_protocol(v):
    v = v.lower()
    if v == "-1" or v == "all":
        return "-1"
    d = dict(udp=17, tcp=6, icmp=1, all=-1)
    if v in d:
        return v
    if v.isdigit():
        return v
    for k, vv in d.items():
        if vv == v:
            return k
    return v


class TFStateSecurityGroup(ResourceTFStateAdapter, TFSecurityGroupBase):

    def render_module(self, path='root'):
        module_state = {
            "path": [path],
            "outputs": {},
            "resources": {
                "aws_security_group.sg_target": self.render_resource()
            }
        }
        return module_state

    def render_resource(self):
        attributes = self.render_attributes()
        rendered = {
            "type": "aws_security_group",
            "depends_on": [],
            "primary": {
                "id": self.resource['GroupId'],
                "meta": {},
                "tainted": False,
                "attributes": attributes
                }
        }
        attributes['egress.#'] = "%d" % len(self.resource['IpPermissionsEgress'])
        for rule in self.resource['IpPermissionsEgress']:
            attributes.update(
                self.format_state_rule('egress', rule))
        attributes['ingress.#'] = "%d" % len(self.resource['IpPermissions'])
        for rule in self.resource['IpPermissions']:
            attributes.update(
                self.format_state_rule('ingress', rule))
        attributes['tags.%'] = "%d" % len(self.resource.get('Tags', ()))
        for t in self.resource.get('Tags', []):
            attributes['tags.%s' % t['Key']] = t['Value']
        return rendered


class TFResourceSecurityGroup(ResourceTFResourceAdapter, TFSecurityGroupBase):

    def render_resource(self):
        attributes = self.render_attributes()
        ingress, egress = [], []
        for r in self.resource.get('IpPermissions'):
            ingress.append(self.format_resource_rule('ingress', r))
        for r in self.resource.get('IpPermissions'):
            egress.append(self.format_resource_rule('egress', r))
        resource = {
            "aws_security_group": {
                "sg_target": attributes}}
        return resource

