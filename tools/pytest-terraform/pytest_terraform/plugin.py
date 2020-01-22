import sys
import os
# import pytest

from pytest_terraform.kv import SqliteKv
from pytest_terraform import tf


def pytest_configure(config):
    print('pytest configure loaded', file=sys.stderr)

    # Create and initialize db early in setup process
    tf_db = SqliteKv(os.path.join(os.getcwd(), 'tf.db'))  # noqa
    tf.LazyDb.value = tf_db
    tf.LazyTfBin.value = tf.find_binary('terraform')

    if config.pluginmanager.hasplugin("xdist"):
        config.pluginmanager.register(XDistTerraform())
        return


class XDistTerraform(object):

    # Hooks
    # https://github.com/pytest-dev/pytest-xdist/blob/master/src/xdist/newhooks.py
    
    def pytest_xdist_setupnodes(config, specs):
        print("setup nodes", file=sys.stderr)


def pytest_addoption(parser):
    group = parser.getgroup('terraform')
    group.addoption(
        '--tf-binary',
        action='store',
        dest='dest_tf_binary',
        help=('Configure the path to the terraform binary. '
              'Default is to search PATH')
    )
    group.addoption(
        '--tf-db',
        action='store',
        dest='dest_tf_db',
        help=('Configure the path to the plugins state file. '
              'Default is to use an auto-gcd path')
    )    
    group.addoption(
        '--tf-mod-dir',
        action='store',
        dest='dest_tf_mod_dir',
        help=('Configue the parent directory to look '
              'for terraform modules')
    )

    parser.addini('terraform-plugins', 'Terraform provider plugins')
    parser.addini('terraform-mod-dir', 'Parent Directory for terraform modules')
