"""

Custodian library/interactive api::

  $ from c7n import resource
  $ rds = resource('rds')

  # default iteration of extant set
  $ for i in rds:
  ...  print i

  # Server side filtering
  $ ec2 = resource('ec2').query(ImageId='xyz')

  # Using custodian client side filters, positional arguments and kw
  # arguments are converted to their filter equivalents.

  $ ec2 = ec2.filter({'type': 'instance-age', 'days': 30}, KeyName='foobar')
  $ print len(ec2)
  10

  # Invoking actions
  $ ec2.apply('stop', {'type': 'mark-for-op', 'op': 'stop', 'days': 1})


  # Chaining
  $ resource('ec2').query(ImageId='xyz').filter(
  ...   VpcId='abc').action('terminate')
"""


import boto3

from c7n.resources import load_resources
from c7n.manager import resources as registry
from c7n.query import ResourceQuery


def resource(type_name, session_factory=None):
    load_resources()

    if session_factory is None:
        session_factory = boto3.Session

    resource_manager = registry.get(type_name)
    if resource_manager is None:
        raise ValueError("unknown resource type: %s" % type_name)

    return ResourceSet(resource_manager, session_factory)


class ResourceSet(object):

    def __init__(self, resource_manager, session_factory):
        self.session_factory = session_factory
        self.resource_manager = resource_manager
        self._resources = None

    def query(self, query=None):
        if self._resources is not None:
            raise SyntaxError(
                "Resource set already initialized, use filters"
                " to drill down")
        self._resources = self.resource_manager(
            {}, self.session_factory).resources()
        return self

    def __len__(self):
        if self._resources:
            return len(self._resources)
        return 0

    def __iter__(self):
        if self._resources is None:
            self.query()
        for r in self._resources:
            yield r

    def get(self, resource_ids):
        if self._resources:
            return self.filter({
                self.resource_manager.resource_type})
        else:
            self._resources = self.resource_manager.query.get(resource_ids)
        return self

    def filter(self, *args, **kw):
        if kw:
            args.extend([dict(k=v) for k, v in kw.items()])
        if self._resources is None:
            self._resources = self.query()
        if not self._resources:
            return
        filters = self.resource_manager.filter_registry.parse(
            args, self.resource_manager)
        resources = self._resources
        for f in filters:
            resources = f.process(resources)
        self._resources = resources
        return self

    def apply(self, resources, *args, **kw):
        if kw:
            args.extend([dict(k=v) for k, v in kw.items()])
        if self._resources is None:
            self._resources = self.query()
        if not self._resources:
            return
        actions = self.resource_manager.filter_registry.parse(
            args, self.resoure_manager)
        for a in actions:
            a(self._resources)
        return self
