# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from __future__ import absolute_import

import inspect
import itertools
import logging
import operator
import os


import click
import yaml

from docutils import nodes
from docutils.statemachine import ViewList
from docutils.parsers.rst.directives import unchanged

from jinja2 import Environment, PackageLoader

from sphinx.errors import SphinxError
from sphinx.directives import SphinxDirective as Directive
from sphinx.util.nodes import nested_parse_with_titles

from c7n.filters import ValueFilter
from c7n.schema import resource_vocabulary, generate as generate_schema
from c7n.resources import load_resources
from c7n.provider import clouds

log = logging.getLogger('c7nsphinx')


def template_underline(value, under="="):
    return len(value) * under


def element_name(cls):
    return cls.schema['properties']['type']['enum'][0]


def element_doc(cls):
    if cls.__doc__ is not None:
        return inspect.cleandoc(cls.__doc__)
    for b in cls.__bases__:
        if b in (ValueFilter, object):
            continue
        doc = b.__doc__ or element_doc(b)
        if doc is not None:
            print("{} -> {} for docs".format(cls, b))
            return inspect.cleandoc(doc)
    return ""


def element_permissions(cls):
    if cls.permissions:
        return cls.permissions
    return ()


def elements(cls, registry_attr):
    registry = getattr(cls, registry_attr)
    seen = {}
    for k, v in registry.items():
        if k in ('and', 'or', 'not'):
            continue
        if v in seen:
            continue
        else:
            seen[element_name(v)] = v

    return [seen[k] for k in sorted(seen)]


def get_environment():
    env = Environment(loader=PackageLoader('c7n_sphinxext', '_templates'))
    env.globals['underline'] = template_underline
    env.globals['ename'] = element_name
    env.globals['edoc'] = element_doc
    env.globals['eperm'] = element_permissions
    env.globals['eschema'] = CustodianSchema.render_schema
    env.globals['render_resource'] = CustodianResource.render_resource
    return env


class CustodianDirective(Directive):

    has_content = True
    required_arguments = 1

    vocabulary = None
    env = None

    def _parse(self, rst_text, annotation):
        result = ViewList()
        for line in rst_text.split("\n"):
            result.append(line, annotation)
        node = nodes.paragraph()
        node.document = self.state.document
        nested_parse_with_titles(self.state, result, node)
        return node.children

    def _nodify(self, template_name, annotation, variables):
        return self._parse(
            self._render(template_name, variables), annotation)

    @classmethod
    def _render(cls, template_name, variables):
        t = cls.env.get_template(template_name)
        return t.render(**variables)

    @classmethod
    def resolve(cls, schema_path):
        current = cls.vocabulary
        frag = None
        if schema_path.startswith('.'):
            # The preprended '.' is an odd artifact
            schema_path = schema_path[1:]
        parts = schema_path.split('.')
        while parts:
            k = parts.pop(0)
            if frag:
                k = "%s.%s" % (frag, k)
                frag = None
                parts.insert(0, 'classes')
            elif k in clouds:
                frag = k
                if len(parts) == 1:
                    parts.append('resource')
                continue
            if k not in current:
                raise ValueError("Invalid schema path %s" % schema_path)
            current = current[k]
        return current


class CustodianResource(CustodianDirective):

    @classmethod
    def render_resource(cls, resource_path):
        resource_class = cls.resolve(resource_path)
        provider_name, resource_name = resource_path.split('.', 1)
        return cls._render('resource.rst',
            variables=dict(
                provider_name=provider_name,
                resource_name="%s.%s" % (provider_name, resource_class.type),
                filters=elements(resource_class, 'filter_registry'),
                actions=elements(resource_class, 'action_registry'),
                resource=resource_class))


class CustodianSchema(CustodianDirective):

    option_spec = {'module': unchanged}

    @staticmethod
    def schema_present(schema):
        s = dict(schema)
        s.pop('type', None)
        s.pop('additionalProperties', None)
        return s

    @classmethod
    def render_schema(cls, el):
        return cls._render(
            'schema.rst',
            {'schema_yaml': yaml.safe_dump(
                cls.schema_present(el.schema),
                default_flow_style=False)})

    def run(self):
        schema_path = self.arguments[0]
        schema = self.resolve(schema_path).schema
        if schema is None:
            raise SphinxError(
                "Unable to generate reference docs for %s, no schema found" % (
                    schema_path))
        schema_yaml = yaml.safe_dump(
            self.schema_present(schema), default_flow_style=False)
        return self._nodify(
            'schema.rst', '<c7n-schema>',
            dict(name=schema_path, schema_yaml=schema_yaml))


INITIALIZED = False


def init():
    global INITIALIZED
    if INITIALIZED:
        return
    load_resources()
    CustodianDirective.vocabulary = resource_vocabulary()
    CustodianDirective.definitions = generate_schema()['definitions']
    CustodianDirective.env = env = get_environment()
    INITIALIZED = True
    return env


def setup(app):
    init()

    app.add_directive_to_domain(
        'py', 'c7n-schema', CustodianSchema)

    app.add_directive_to_domain(
        'py', 'c7n-resource', CustodianResource)

    return {'version': '0.1',
            'parallel_read_safe': True,
            'parallel_write_safe': True}


@click.command()
@click.option('--provider', required=True)
@click.option('--output-dir', type=click.Path(), required=True)
@click.option('--group-by')
def main(provider, output_dir, group_by):
    try:
        _main(provider, output_dir, group_by)
    except Exception:
        import traceback, pdb, sys
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])


def _main(provider, output_dir, group_by):
    """Generate RST docs for a given cloud provider's resources
    """
    env = init()

    logging.basicConfig(level=logging.INFO)
    output_dir = os.path.abspath(output_dir)
    provider_class = clouds[provider]

    # group by will be provider specific, supports nested attributes
    group_by = operator.attrgetter(group_by or "type")

    # Write out resources by grouped page
    for key, group in itertools.groupby(
            sorted(provider_class.resources.values(), key=group_by), key=group_by):
        rpath = os.path.join(output_dir, "%s.rst" % key)
        with open(rpath, 'w') as fh:
            log.info("Writing ResourceGroup:%s.%s to %s", provider, key, rpath)
            t = env.get_template('provider-resource.rst')
            fh.write(t.render(
                provider_name=provider,
                key=key,
                resources=sorted(group, key=operator.attrgetter('type'))))

    # Write out common provider filters & actions
    common_actions = {}
    common_filters = {}
    for r in provider_class.resources.values():
        for f in elements(r, 'filter_registry'):
            if not f.schema_alias:
                continue
            common_filters[element_name(f)] = (f, r)
        fpath = os.path.join(
            output_dir, "%s-common-filters.rst" % provider_class.type.lower())
        with open(fpath, 'w') as fh:
            t = env.get_template('provider-common-elements.rst')
            fh.write(t.render(
                provider_name=provider,
                element_type='filters',
                elements=[common_filters[k] for k in sorted(common_filters)]))

        for a in elements(r, 'action_registry'):
            if not a.schema_alias:
                continue
            common_actions[element_name(a)] = (a, r)
        fpath = os.path.join(
            output_dir, "%s-common-actions.rst" % provider_class.type.lower())
        with open(fpath, 'w') as fh:
            t = env.get_template('provider-common-elements.rst')
            fh.write(t.render(
                provider_name=provider,
                element_type='actions',
                elements=[common_actions[k] for k in sorted(common_actions)]))

    # Write out the provider index
    provider_path = os.path.join(output_dir, 'index.rst')
    with open(provider_path, 'w') as fh:
        log.info("Writing Provider Index to %s", provider_path)
        t = env.get_template('provider-index.rst')
        fh.write(t.render(provider_name=provider))
