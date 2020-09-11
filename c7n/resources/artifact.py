# Copyright Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from c7n.actions import Action
from c7n.filters.iamaccess import CrossAccountAccessFilter
from c7n.manager import resources
from c7n.query import QueryResourceManager, TypeInfo, RetryPageIterator
from c7n.utils import local_session, type_schema


@resources.register('artifact-domain')
class ArtifactDomain(QueryResourceManager):
    class resource_type(TypeInfo):
        service = 'codeartifact'
        enum_spec = ('list_domains', 'domains', None)
        id = name = 'name'
        arn = 'arn'


@ArtifactDomain.action_registry.register('delete')
class DeleteDomain(Action):

    schema = type_schema('delete', force={'type': 'boolean'})
    permissions = ('codeartifact:DeleteDomain',
                   'codeartifact:DeleteRepository',
                   'codeartifact:ListRepositoriesInDomain')

    def process(self, resources):
        client = local_session(self.manager.session_factory).client('codeartifact')
        force = self.data.get('force', False)
        for r in resources:
            if force:
                self._remove_repositories(client, r)
            client.delete_domain(domain=r['name'])

    def _remove_repositories(self, client, domain):
        repos = []
        paginator = client.get_paginator('list_repositories_in_domain')
        paginator.PAGE_ITERATOR_CLS = RetryPageIterator

        try:
            results = paginator.paginate(domain=domain['name'])
            repos.extend(results.build_full_result().get('repositories'))
        except client.exceptions.ResourceNotFoundException:
            return False

        for r in repos:
            try:
                client.delete_repository(domain=domain['name'], repository=r['name'])
            except client.exceptions.ResourceNotFoundException:
                continue


@resources.register('artifact-repo')
class ArtifactRepo(QueryResourceManager):
    class resource_type(TypeInfo):
        service = 'codeartifact'
        enum_spec = ('list_repositories', 'repositories', None)
        id = name = 'name'
        arn = 'arn'


@ArtifactRepo.filter_registry.register('cross-account')
class CrossAccountRepo(CrossAccountAccessFilter):

    policy_attribute = 'c7n:Policy'
    permissions = ('codeartifact:GetRepositoryPermissionsPolicy',)

    def process(self, resources, event=None):
        client = local_session(self.manager.session_factory).client('codeartifact')

        for r in resources:
            try:
                result = client.get_repository_permissions_policy(
                    domain=r['domainName'], repository=r['name']
                )
                r[self.policy_attribute] = result['policy']['document']
            except client.exceptions.ResourceNotFoundException:
                pass

        return super().process(resources)


@ArtifactRepo.action_registry.register('delete')
class DeleteRepo(Action):

    schema = type_schema('delete')
    permissions = ('codeartifact:DeleteRepository',)

    def process(self, resources):
        client = local_session(self.manager.session_factory).client('codeartifact')

        for r in resources:
            try:
                client.delete_repository(domain=r['domainName'], repository=r['name'])
            except client.exceptions.ResourceNotFoundException:
                continue
