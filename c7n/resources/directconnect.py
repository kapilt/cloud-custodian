# Copyright 2015-2017 Capital One Services, LLC
# SPDX-License-Identifier: Apache-2.0
from c7n.manager import resources
from c7n.query import QueryResourceManager, TypeInfo
from c7n.tags import universal_augment


@resources.register('directconnect')
class DirectConnect(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'directconnect'
        enum_spec = ('describe_connections', 'connections', None)
        id = 'connectionId'
        name = 'connectionName'
        filter_name = 'connectionId'
        arn_type = "dxcon"
        universal_taggable = object()

    augment = universal_augment
