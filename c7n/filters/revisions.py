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
"""
Custodian support for diffing and patching across multiple versions
of a resource.
"""

import json
from pprint import pprint
import zlib

from botocore.exceptions import ClientError
from botocore.parsers import BaseJSONParser
#from concurrent.futures import as_completed
#from datetime import datetime, timedelta

import functools
#import jmespath

#from c7n.actions import Action
from c7n.filters import Filter
#from c7n.mu import ConfigRule
from c7n.utils import local_session, type_schema, camelResource


DEVELOPER_NOTES = """
Three python diff libraries were evaluated for comparing resource revisions.

 - jsonpatch
 - dictdiffer
 - DeepDiff

Additional a consideration of rolling our own thats specific to custodian's
needs.

# jsonpatch

On a whole it does a good job of producing a minimal diff that matches the
semantic changes. There are some bugs on the repo that need investigation.

- Url https://github.com/stefankoegl/python-json-patch
- License BSD

```python
[{u'op': u'replace', u'path': u'/IpPermissions/0/ToPort', u'value': 80},
 {u'op': u'add',
  u'path': u'/Tags/1',
  u'value': {'Key': 'AppId', 'Value': 'SomethingGood'}}]
```

# dictdiffer

- Url https://github.com/inveniosoftware/dictdiffer
- License MIT

[('change', ['IpPermissions', 0, 'ToPort'], (53, 80)),
 ('change', ['Tags', 1, 'Value'], ('Name', 'SomethingGood')),
 ('change', ['Tags', 1, 'Key'], ('Origin', 'AppId')),
 ('add', 'Tags', [(2, {'Key': 'Origin', 'Value': 'Name'})])]

The change here is correct, but requires a bit of semantic interpretation, it
ends up mutating elements in position as it considers position within a list
a strict diff, where as in all circumstances we want the semantic delta
on a list rather than a mutation in place.

# DeepDiff

- Url https://github.com/seperman/deepdiff
- License MIT

{'iterable_item_added': {"root['IpPermissions'][0]": {'FromPort': 53,
                                                      'IpProtocol': 'tcp',
                                                      'IpRanges': ['10.0.0.0/8'],
                                                      'PrefixListIds': [],
                                                      'ToPort': 80,
                                                      'UserIdGroupPairs': []},
                         "root['Tags'][1]": {'Key': 'AppId',
                                             'Value': 'SomethingGood'}},
 'iterable_item_removed': {"root['IpPermissions'][0]": {'FromPort': 53,
                                                        'IpProtocol': 'tcp',
                                                        'IpRanges': ['10.0.0.0/8'],
                                                        'PrefixListIds': [],
                                                        'ToPort': 53,
                                                        'UserIdGroupPairs': []}}}

Deep diff is fairly configurable, the only non default param here is
ignore_order.

The returned semantic structure of the diff is quite obtuse, and idiosyncratic.

# Rolling our own

The issue with most of the diff libraries, is that they require
significant interpretation to line up with the api call semantics
around any given resource.  Ie. a security group rule is effectively
immutable, and modification which might be represented by a diff
library as a 'change', requires removal of original and addition of
modified.
"""


class Revisions(Filter):
    """Get previous revisions of a resource from config.

    Default operation mode is bit different than other filters
    in that it returns additional.
    """

ErrNotFound = "ResourceNotDiscoveredException"


class Diff(Revisions):
    """Compute the diff from the current revision to its previous."""

    SELECTOR_PREVIOUS = 'previous'

    schema = type_schema('diff')

    parser = resource_shape = None

    def initialize(self):
        pass

    def process(self, resources, event=None):
        model = self.manager.get_model()
        session = local_session(self.manager.session_factory)
        config = session.client('config')
        parser = ConfigResourceParser()
        resource_shape = self.get_resource_shape(session)

        # previous, locked, date
        selector = self.data.get('selector', self.SELECTOR_PREVIOUS)
        limit = selector == self.SELECTOR_PREVIOUS and 4
        results = []

        for res in resources:
            res = dict(res)
            res.pop('MatchedFilters')
            try:
                revisions = config.get_resource_config_history(
                    resourceType=model.config_type,
                    resourceId=res[model.id],
                    limit=limit)['configurationItems']
            except ClientError as e:
                raise
                if e.response['Error']['Code'] != ErrNotFound:
                    self.log.debug(
                        "config - resource %s:%s not found" % (
                            model.config_type, res[model.id]))
                    raise
                continue

            cur = res

            for rev in revisions:
                previous = parser.parse(
                    camelResource(json.loads(rev['configuration'])),
                    resource_shape)
                # print rev.keys()
                # print rev['relatedEvents'],
                # rev['configurationItemStatus'],
                # rev['supplementaryConfiguration'],
                # rev['configurationItemCaptureTime']
                from dictdiffer import diff
                diff = list(diff(previous, cur))
                pprint(diff)
                if diff:
                    res['c7n.Diff'] = diff
                    results.append(res)
                    break
                #from deepdiff import DeepDiff
                #pprint(DeepDiff(previous, cur, ignore_order=True))

                cur = previous
            res['c7n.Revisions'] = revisions

        return results

    def process_resource(self, r):
        pass

    def get_revisions(self, i):
        pass

    def process_revisions(self, i):
        for r in self.get_revisions(i):
            return any(self.process_revision(i, r))

    def process_revision(self, i, r):
        pass

    def get_resource_shape(self, session):
        resource_model = self.manager.get_model()
        service = session.client(resource_model.service)
        shape_name = resource_model.config_type.split('::')[-1]
        return service.meta.service_model.shape_for(shape_name)


class ConfigResourceParser(BaseJSONParser):

    def parse(self, data, shape):
        return self._do_parse(data, shape)

    def _do_parse(self, data, shape):
        return self._parse_shape(shape, data)


Action = object


class ApplyReverseDiff(object):

    def process(self, resources):
        pass

    def apply_delta(self, resource, delta):
        handler_names = [h for h in dir(self) if h.startswith('handle_')]
        for hn in handler_names:
            h = getattr(self, hn)
            h(resource, delta)


def delta_selector(expr):
    def decorator(f):
        functools.wrap(f)

        def delta_handler(client, resource, change_set):
            changes = [c for c in change_set if c['path'].startswith(expr)]
            return f(client, resource, changes)


class ResourceTFStateAdapter(object):

    def __init__(self, resource):
        self.resource = resource

    def render_module(self, path='root'):
        raise NotImplementedError()


class ResourceTFResourceAdapter(object):

    def render_resource()
        raise NotImplementedError()


class TerraForm(object):
    # Todo handle importing state
    def __init__(self, bin_path):
        self.bin_path = bin_path

    def diff(self, goal, state):
        plan = self.run_delta_op()
        return plan

    def show(self, goal, state):
        output = self.diff(goal, state)
        with temp_dir:
            with tempfile.NamedTemporaryFile() as plan_fh:
                plan_fh.write(output)
                return subprocess.check_output(
                    self.bin_path, "show", plan_fh.name)

    def apply(self, goal, state):
        output = self.diff(goal, state)
        with temp_dir:
            with tempfile.NamedTemporaryFile() as plan_fh:
                plan_fh.write(output)
                return subprocess.check_output(
                    self.bin_path, "apply", plan_fh.name)

    def run_delta_op(self, goal, state):
        rendered_goal = self.render_goal(goal)
        rendered_state = self.render_state(state)
        with temp_dir:
            with tempfile.NamedTemporaryFile() as goal_fh:
                with tempfile.NamedTemporaryFile() as state_fh:
                    json.dump(rendered_state, state_fh, indent=2)
                    json.dump(rendered_goal, goal_fh, indent=2)
                    subprocess.check_output([
                        self.bin_path, "plan"
                    ])

    def render_goal(self, goal):
        return TFResourceSecurityGroup(goal).render_resource()

    def render_state(self, state):
        return TFStateSecurityGroup(state).render_module()


class TFSecurityGroupBase(object):

    RULE_ATTRS = (
        ('cidr_blocks', 'IpRanges', 'CidrIp'),
        # terraform doesn't seem to support cross account/vpc sg rules .7.13
        ('security_groups', 'UserIdGroupPairs', 'GroupId'),
        ('prefix_list_ids', 'PrefixListIds', 'PrefixListId'))

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
            f["%s.%s.%s" % (prefix, code, k)] = len(v)
            for idx, e in enumerate(v):
                f["%s.%s.%s.%d" % (prefix, code, k, idx)] = e[ke]
        f["%s.%s.%s" % (prefix, code, 'protocol')] = rule['IpProtocol']
        # f["%s.%s.%s" % (prefix, code, 'self')] = rule  # Todo
        f["%s.%s.%s" % (prefix, code, 'from_port')] = rule['FromPort']
        f["%s.%s.%s" % (prefix, code, 'to_port')] = rule['ToPort']
        return f

    def compute_rule_hash(self, rule):
        buf = "%d-%d-%d-%d" % (
            rule['FromPort'],
            rule['ToPort'],
            rule['Protocol'],
            False)
        for k, a, ke in self.RULE_ATTRS:
            ev = [e[ke] for e in rule[a]]
            ev.sorted()
            for e in ev:
                buf += "%s" % e
        return abs(zlib.crc32(buf))


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
        attributes['egress.#'] = len(self.resource['IpPermissionsEgress'])
        for rule in self.resource['IpPermissionsEgress']:
            attributes.update(
                self.format_state_rule('egress', rule))
        attributes['ingress.#'] = len(self.resource['IpPermissions'])
        for rule in self.resource['IpPermissions']:
            attributes.update(
                self.format_state_rule('ingress', rule))
        attributes['tags.%'] = len(self.resource.get('Tags', ()))
        for t in self.resource.get('Tags', []):
            attributes['tags.%s' % t['Key']] = t['Value']
        return rendered


class TFResourceSecurityGroup(ResourceTFResourceAdapter, TFSecurityGroupBase):

    def render_resource(self):
        attributes = self.render_attributes()
        ingress, egress = [], []
        for r in self.resource.get('IpPermissions'):
            pass
        resource = {
            "aws_security_group": {
                "sg_target": attributes}}
        return resource


class TF(object):
    pass


class SecurityGroupPatch(object):

    @delta_selector("/Tags")
    def handle_tags(self, client, source, target, change_set):
        """
        """
        source_tags = {t['Key']: t['Value'] for t in source['Tags']}
        target_tags = {t['Key']: t['Value'] for t in target['Tags']}

        target_keys = set(target_tags.keys())
        source_keys = set(source_tags.keys())

        removed = source_keys.difference(target_keys)
        added = target_keys.difference(source_keys)
        changed = set()

        for k in target_keys.intersection(source_keys):
            if source_tags[k] != target_tags[k]:
                changed.add(k)

        client.create_tags(
            Resources=target['GroupId'],
            Tags=[{'Key': k, 'Value': v} for k, v in target_tags.items() if
                  k in added or k in changed])
        client.remove_tags(
            Resources=target['GroupId'],
            Tags=[{'Key': k, 'Value': v} for k, v in source_tags.items() if
                  k in removed])

    def group_rule_changes(self, source, target, change_set, prefix):
        """
        """
        source_rules = source.get(prefix, ())
        target_rules = target.get(prefix, ())

        changed_items = [
            resource['Tags'][idx] for idx
            in set([c[1][1] for c in change_set if c[0] == 'change'])]
        removed_items = [
            resource['Tags'][idx] for idx
            in set([c[1][1] for c in change_set if c[0] == 'remove'])]

    @delta_selector("/IpPermissionsEgress")
    def handle_ingress(self, client, resource, change_set):
        """
        handle ingress rule changes
        """
        added, removed = self.group_rule_changes(
            resource, change_set, 'IpPermissionsEgress')
        return added, removed

    @delta_selector("/IpPermissions")
    def handle_egress(self, client, resource, change_set):
        """
        handle egress rule changes
        """
        added, removed = self.group_rule_changes(
            resource, change_set, 'IpPermissionsEgress')
        return added, removed


# TODO List

class Locked(Filter):
    """Has the resource been locked."""


class Lock(Action):
    """Lock a resource from further modifications.

    Get current revision of given object. We may have an inflight
    snapshotDelivery coming.
    """


class Unlock(Action):
    """Unlock a resource for further modifications."""

    
class Revert(Action):
    """Restore a resource to a previous version."""
    
    
