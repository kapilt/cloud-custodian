import functools
import json
import os
import shutil
import subprocess
import sys

import jmespath
import pytest
from py.path import local

from .kv import SqliteKv, KvState


def find_binary(bin_name):
    parts = os.environ['PATH'].split(':')
    for p in parts:
        candidate = os.path.join(p, bin_name)
        if os.path.exists(candidate):
            return candidate


class ModuleNotFound(ValueError):
    """module not found"""


class TerraformRunner(object):

#
#    command_templates = {
#        'init': 'init {input} {color} {plugin_dir}',
#        'apply': 'apply {input} {color} {state} {approve} {plan}',
#        'plan': 'plan {input} {color} {state} {output}',
#        'destroy': 'destroy {input} {color} {state} {approve}'
#    }
#
#    template_defaults = {
#        'input': '-input=false',
#        'color': '-no-color',
#        'approve': '-auto-approve',    
#    }

    def __init__(self, work_dir, state_path=None,
                 plugin_cache=None, stream_output=None, tf_bin=None):

        self.work_dir = work_dir
        self.state_path = state_path or os.path.join(
            work_dir, 'terraform.tfstate')
        self.stream_output = stream_output
        self.plugin_cache = plugin_cache or ''
        self.tf_bin = tf_bin

    def apply(self, plan=True):
        """run terraform apply"""
        apply_args = [
            self.tf_bin, 'apply', '-input=false', '-no-color',
            '-auto-approve', '-state=%s' % self.state_path]
        if plan is True:
            self.plan('tfplan')
            apply_args.append('tfplan')
        elif plan:
            apply_args.append(plan)

        # apply_args = self._get_command_args(state='-state=%s' % self.state_path)
        self._run_cmd(apply_args)
        return TerraformState.load(self.state_path)

    def plan(self, output=None):
        plan_args = [
            self.tf_bin, 'plan', '-input=false', '-no-color',
            '-state=%s' % self.state_path, '-out=tfplan']
        self._run_cmd(plan_args)

    def init(self):
        init_args = [
            self.tf_bin, 'init', '-no-color']
        if self.plugin_cache:
            init_args.append('-plugin-dir=%s' % self.plugin_cache)
        self._run_cmd(init_args)

    def destroy(self):
        destroy_args = [
            self.tf_bin, 'destroy', '-auto-approve', '-no-color']
        self._run_cmd(destroy_args)

    def _get_command_args(self, cmd_name, **kw):
        kw.update(self.template_defaults)
        kw['state']  = self.state_path and '-state=%s' % self.state_path or ''
        return list(
            filter(None,
                   self.command_templates[cmd_name].format(**kw).split(' ')))

    def _run_cmd(self, args):
        print('run cmd', args)
        subprocess.check_output(
            args, cwd=self.work_dir, stderr=subprocess.STDOUT)

    @classmethod
    def install_plugins(cls, plugins, cache_dir, bin_path=None):
        """initialize a shared terraform plugins cache directory.

        returns a runner
        plugins are a list of strings, either as plugin names or
        name with version specification. ie. 'aws ~= 2.2'
        """
        with open(os.path.join(cache_dir, 'providers.tf'), 'w') as fh:
            for p in plugins:
                parts = p.strip().split()
                if len(parts) == 1:
                    name, version = parts[0], None
                else:
                    name, version = parts[0], ' '.join(parts[1:])
                fh.write('provider "%s" {\n' % name)
                if version:
                    fh.write(' version = "%s"\n' % version)
                fh.write('}\n\n')
        tf_bin = bin_path or find_binary('terraform')
        init_args = [tf_bin, 'init', '-input=false', '-no-color']
        subprocess.check_output(
            init_args, cwd=cache_dir, stderr=subprocess.STDOUT)
        arch_dir = local(cache_dir).join(
            '.terraform', 'plugins').listdir()[0].strpath
        return functools.partial(
            cls, plugin_cache=arch_dir, tf_bin=tf_bin)


class TerraformState(object):
    """Abstraction over a terrafrom state file with helpers.

    resources dict contains a minimal representation of a terraform
    state file with enough identity information to query a resource
    from the api.
    
    resources dict is a nested data structure corresponding to
       resource_type -> resource name -> resource attributes.

    by default all resources will have an 'id' attribute, additional
    attributes which contain the key 'name' will also be present.
    """

    Missing = None
    Pending = 'pending'
    Provisioned = 'provisioned'
    Deleting = 'deleting'
    Deleted = 'deleted'
    ErrorPending = 'error-pending'
    ErrorDeleting = 'error-deleting'
    
    def __init__(self, resources, outputs):
        self.outputs = outputs
        self.resources = resources

    def get(self, k, default=None):
        """accessor to resource attributes.

        supports a few shortcuts for ease of use.
        
        key can be a jmespath expression in which case the evaluation
        is returned. 

        if key is a unique resource name, then its data is returned, if
        the data is a singleton key dictionary with 'id', then just then
        the string value of 'id' is returned.
        """
        if '.' in k:
            return jmespath.search(k, self.resources)
        found = False
        for rtype in self.resources:
            for rname in self.resources[rtype]:
                if rname == k:
                    assert found is False, "Ambigious resource name %s" % k
                    found = self.resources[rtype][rname]
        if found:
            if len(found) == 1:
                return found['id']
            return found
        return default

    @classmethod
    def load(cls, state_file):
        resources = {}
        outputs = {}
        with open(state_file) as fh:
            data = json.load(fh)
            if 'pytest-terraform' in data:
                return cls(data['resources'], data['outputs'])

            for m in data.get('modules', ()):
                for k, r in m.get('resources', {}).items():
                    if k.startswith('data'):
                        continue
                    module, rname = k.split('.', 1)
                    rmap = resources.setdefault(module, {})
                    rattrs = {'id': r['primary']['id']}
                    for kattr, vattr in r['primary']['attributes'].items():
                        if 'name' in kattr and vattr != rattrs['id']:
                            rattrs[kattr] = vattr
                    rmap[rname] = rattrs
        return cls(resources, outputs)

    def save(self, state_path):
        with open(state_path, 'w') as fh:
            json.dump({
                'pytest-terraform': 1,
                'outputs': self.outputs,
                'resources': self.resources},
                fh)


class TerraformTestApi(TerraformState):
    """public api to tests as fixture value."""

    def get_runner(self, test_dir):
        return LazyRunner.resolve()


class PlaceHolderValue(object):
    """Lazy / Late resolved named values.

    many of our instantiations are at module import time, to support
    runtime configuration from cli/ini options we utilize a lazy
    loaded value set which is configured for final values via hooks
    (early, post conf, pre collection).)
    """
    def __init__(self, name):
        self.name = name
        self.value = None

    def resolve(self, default=None):
        if not self.value and default:
            raise ValueError("PlaceHolderValue %s not resolved" % self.name)
        return self.value or default


class PlaceHolderRunner(object):

    def __init__(self, name):
        self.name = name
        self.value = None

    def resolve(self):
        return self.value


LazyDb = PlaceHolderValue("db")
LazyRunner = PlaceHolderRunner('runner')

#
LazyPluginCacheDir = PlaceHolderValue('plugin_cache')
LazyDbPath = PlaceHolderValue('tf_db_path')
LazyTfBin = PlaceHolderValue('tf_bin_path')


class TerraformController(object):
    """Singleton entry point.

    In distributed testing scenarios only instantiated
    once for the master node. Note this plugin only
    supports multi-process distributed testing on a
    single host.
    """

    def __init__(self, config):
        self.config = config
        self.tf = self.config.getplugin('terminalreporter')

    @staticmethod
    def parse_providers(providers_config):
        providers = {}
        for p in providers_config.split('\n'):
            parts = p.strip().strip(' ')
            providers[parts.pop(0)] = (' '.join(parts)).strip()
        providers.split('\n').strip()
        
    def initialize(self):
        # we merge configured values with any specified to
        # decorator factories.
        providers = self.parse_providers(
            self.config.getinit('terraform-plugins', ''))

        LazyTfBin.value = self.config.getoption(
            'dest_tf_binary', None) or find_binary('terraform')
        LazyPluginCacheDir.value = self.config.getoption(
            'dest_tf_plugin', None)
        LazyDbPath.value = self.config.getoption(
            'dest_tf_db', None) or os.path.join(os.getcwd(), 'tf.db')

        self.tr.write_line(
            'terraform - initialize plugin cache %s')


class TerraformFixture(object):

    def __init__(self, tf_bin, tf_db, plugin_cache, scope,
                 tf_root_module, test_dir, recording):
        self.tf_bin = tf_bin
        self.tf_db = tf_db
        self.tf_root_module = tf_root_module
        self.test_dir = test_dir
        self.scope = scope
        self.recording = True

    @property
    def __name__(self):
        return "Terraform %s" % self.tf_root_module

    def resolve_module_dir(self, request):
        for candidate in [
                self.test_dir.join(self.tf_root_module),
                self.test_dir.join(
                    'terraform', self.tf_root_module),                
                self.test_dir.dirpath().join(
                    self.tf_root_module),
                self.test_dir.dirpath().join(
                    'terraform', self.tf_root_module)
        ]:
            print(candidate)
            if not candidate.check(exists=1, dir=1):
                continue
            return candidate
        raise ModuleNotFound(self.tf_root_module)

    def __call__(self, request, tmpdir_factory, worker_id):
        print('setup %s' % self.tf_root_module)

        if not self.recording:
            return TerraformTestApi.load('tf_resources.json')

        module_dir = self.resolve_module_dir(request)
        work_dir = tmpdir_factory.mktemp(
            self.tf_root_module, numbered=True).join('work')
        runner = TerraformRunner(
            str(work_dir), plugin_cache=None, tf_bin=LazyTfBin.resolve())

        # potentially problematic to do this, all notions of referencing.
        # between module definitions get broken.
        shutil.copytree(str(module_dir), work_dir)

        db = self.tf_db.resolve()
        db.set("%s" % self.tf_root_module,
               {'status': TerraformState.Pending, 'scope': self.scope},
               expected={'status': TerraformState.Missing,
                             'scope': self.scope})

        runner.init()
        try:
            test_api = runner.apply()
            db.set("%s" % self.tf_root_module,
                   {'status': TerraformState.Pending, 'scope': self.scope},
                   expected={'status': TerraformState.Provisioned,
                             'scope': self.scope})
            test_api.save(module_dir.join('tf_resources.json'))
        except Exception:
            # TODO: print sys.stderr/log error
            raise
        finally:
            # config behavor on runner
            print('teardown %s' % self.tf_root_module)
            db.set("%s" % self.tf_root_module,
                   {'status': TerraformState.Deleting, 'scope': self.scope},
                   expected={
                       'status': TerraformState.Provisioned,
                       'scope': self.scope})
            runner.destroy()
            db.set("%s" % self.tf_root_module,
                   {'status': TerraformState.Deleted, 'scope': self.scope},
                   expected={'status': TerraformState.Deleting,
                             'scope': self.scope})            


class FixtureDecoratorFactory(object):
    """Generate fixture decorators on the fly.
    """

    def __init__(self, providers=()):
        self.providers = providers

    def __call__(self, terraform_dir, scope='function', recording=False):        


        # We're have to hook into where fixture discovery will find
        # it, the easiest option is to store on the module that
        # originated the call, all test modules get scanned for
        # fixtures. The alternative is to try and keep a set and
        # store. this particular setup is support decorator usage.
        # ie. its gross on one hand and very pratical for consumers
        # on the other. tron style ftw.

        # We can remove this with aggregation of values here and
        # a reference to extant factory instances.

        f = sys._getframe(1)

        test_dir = local(f.f_locals['__file__']).dirpath()
        tfix = TerraformFixture(
            LazyTfBin,
            LazyDb,
            LazyPluginCacheDir,
            scope,        
            terraform_dir,
            test_dir,
            recording)

        marker = pytest.fixture(scope=scope, name=terraform_dir)
        f.f_locals[terraform_dir] = marker(tfix)

        return self.nonce_decorator

    @staticmethod
    def nonce_decorator(func):
        return func


terraform = FixtureDecoratorFactory()
aws_terraform = FixtureDecoratorFactory(['aws'])
gcp_terraform = FixtureDecoratorFactory(['gcp'])
azure_terraform = FixtureDecoratorFactory(['azure'])
k8s_terraform = FixtureDecoratorFactory(['k8s'])


def xterraform(request, tmpdir, worker_id, scope='session'):
    runner = TerraformRunner(str(tmpdir), tf_bin=find_binary('terraform'))
    tf_db = SqliteKv(os.path.join(os.getcwd(), 'tf.db'), worker_id)

#    print("worker id: %s" % worker_id, file=sys.stderr)
#    print(
#      "worker id: %s request:%s" % (worker_id, dir(request)), file=sys.stderr)
#    print(
#      'worker id: %s cls:%s scope:%s session:%s config:%s instance:%s' % (
#        worker_id, request.cls, request.scope, request.session,
#        request.config, request.instance),
#       file=sys.stderr)
#    print('worker id: %s path:%s function:%s args:%s node:%s'  % (
#        worker_id, request.fspath, request.function,
#        request.funcargnames, request.node),
#          file=sys.stderr)
    assert KvState.Success == tf_db.set(worker_id, 'abc')
    if worker_id == 'gw0':
        print('worker id: %s config:%s' % (worker_id, dir(request.config)))
    yield runner
    # with state_lock(tf_db) as lock:
    #    with TerraformRunner(params) as tf:
    #       tf.init(ttf.work_dir)
    #       tf.apply()
    runner.destroy()

    
