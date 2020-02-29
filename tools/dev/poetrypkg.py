"""
Supplemental tooling for managing custodian depgraph

Todo
 - [ ] check
 - [ ] ensure sanity across dependency graph
 - [ ] generate a find links directory from a wheel cache

"""
import click
import os
import sys

from collections import defaultdict
from pathlib import Path
from pip._internal.utils import appdirs


@click.group()
def cli():
    """Custodian Python Packaging Utility

    some simple tooling to sync poetry files to setup/pip
    """
    # If there is a global installation of poetry, prefer that.
    poetry_python_lib = os.path.expanduser('~/.poetry/lib')
    sys.path.append(os.path.realpath(poetry_python_lib))


@cli.command()
@click.option('--cache', default=appdirs.user_cache_dir('pip'))
@click.option('--link-dir', type=click.Path())
def gen_links(cache, link_dir):
    # wheel only
    #
    # generate a find links directory to perform an install offline.
    # note there we still need to download any packages needed for
    # an offline install. this is effectively an alternative to
    # pip download -d to utilize already cached wheel resources.
    #
    found = {}
    link_dir = Path(link_dir)
    wrote = 0
    for root, dirs, files in os.walk(cache):
        for f in files:
            if not f.endswith('whl'):
                continue
            found[f] = os.path.join(root, f)
    if not link_dir.exists():
        link_dir.mkdir()
    entries = {f.name for f in link_dir.iterdir()}
    for f, src in found.items():
        if f in entries:
            continue
        os.symlink(src, link_dir / f)
        wrote += 1
    if wrote:
        print('Updated %d Find Links' % wrote)


@cli.command()
@click.option('-p', '--package-dir', type=click.Path())
def gen_setup(package_dir):
    """Generate a setup suitable for dev compatibility with pip.
    """
    from poetry.masonry.builders.sdist import SdistBuilder as BaseBuilder
    from poetry.factory import Factory

    factory = Factory()
    poetry = factory.create_poetry(package_dir)

    class InjectedBuilder(BaseBuilder):
        # to enable poetry with a monorepo, we have internal deps
        # as source path dev dependencies, when we go to generate
        # setup.py we need to ensure that the source deps are
        # recorded faithfully.

        @classmethod
        def convert_dependencies(cls, package, dependencies):
            reqs, default = super().convert_dependencies(package, dependencies)
            inject_deps(package, reqs)
            return reqs, default

    builder = InjectedBuilder(poetry, None, None)
    setup_content = builder.build_setup()

    with open(os.path.join(package_dir, 'setup.py'), 'wb') as fh:
        fh.write(b'# Automatically generated from poetry/pyproject.toml\n')
        fh.write(b'# flake8: noqa\n')
        fh.write(setup_content)


@cli.command()
@click.option('-p', '--package-dir', type=click.Path())
@click.option('-o', '--output', default='setup.py')
def gen_frozensetup(package_dir, output):
    """Generate a frozen setup suitable for distribution.
    """
    from poetry.masonry.builders.sdist import SdistBuilder as BaseBuilder
    from poetry.factory import Factory

    factory = Factory()
    poetry = factory.create_poetry(package_dir)

    class FrozenBuilder(BaseBuilder):

        @classmethod
        def convert_dependencies(cls, package, dependencies):
            return locked_deps(package, poetry)

    builder = FrozenBuilder(poetry, None, None)
    setup_content = builder.build_setup()

    with open(os.path.join(package_dir, output), 'wb') as fh:
        fh.write(b'# Automatically generated from pyproject.toml\n')
        fh.write(b'# flake8: noqa\n')
        fh.write(setup_content)


def inject_deps(package, reqs):
    if package.name not in ('c7n', 'c7n_mailer'):
        from c7n.version import version
        from poetry.packages.dependency import Dependency
        reqs.append(Dependency('c7n', '^{}'.format(version)).to_pep_508())


def locked_deps(package, poetry):
    reqs = []
    packages = poetry.locker.locked_repository(False).packages
    inject_deps(package, reqs)
    for p in packages:
        dep = p.to_dependency()
        line = "{}=={}".format(p.name, p.version)
        requirement = dep.to_pep_508()
        if ';' in requirement:
            line += "; {}".format(requirement.split(";")[1].strip())
        reqs.append(line)

    return reqs, defaultdict(list)


if __name__ == '__main__':
    cli()
