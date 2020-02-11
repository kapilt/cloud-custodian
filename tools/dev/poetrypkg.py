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
import zipfile

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
    # generate a find links directory to perform an install offline.
    # note there we still need to download any packages needed for
    # an offline install.
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
    from poetry.masonry.builders.sdist import SdistBuilder
    from poetry.factory import Factory

    factory = Factory()
    poetry = factory.create_poetry(package_dir)

    builder = SdistBuilder(poetry, None, None)
    setup_content = builder.build_setup()
    
    with open(os.path.join(package_dir, 'setup.py'), 'wb') as fh:
        fh.write(b'# Automatically generated from poetry/pyproject.toml\n')
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

    class Builder(BaseBuilder):

        @classmethod
        def convert_dependencies(cls, package, dependencies):
            return locked_deps(poetry)

    builder = Builder(poetry, None, None)
    setup_content = builder.build_setup()
    
    with open(os.path.join(package_dir, output), 'wb') as fh:
        fh.write(b'# Automatically generated from poetry/pyproject.toml\n')
        fh.write(setup_content)


def locked_deps(poetry):
    reqs = []
    packages = poetry.locker.locked_repository(False).packages

    import pdb; pdb.set_trace()
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
