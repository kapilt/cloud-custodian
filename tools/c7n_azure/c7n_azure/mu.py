import logging
import time

from c7n.mu import PythonPackageArchive
import importlib_metadata as pkgmd

log = logging.getLogger('c7n_azure.mu')


def custodian_archive(packages=None):
    modules = {'c7n', 'c7n_azure'}
    if packages:
        modules = filter(None, modules.union(packages))
    t = time.time()
    archive = PythonPackageArchive(sorted(modules))
    log.debug('Built archive in %0.2f' % (time.time() - t))
    t = time.time()
    archive.add_contents(
        'requirements.txt',
        generate_requirements('c7n_azure', ignore=set((
            'boto3', 'botocore', 'argcomplete', 'distlib',
            'future', 'futures', 'azure-cli-core',
            'jsonpatch', 'jsonschema', 'tabulate', 'PyYAML'))))
    log.debug('Build frozen requirements in %0.2f' % (time.time() - t))
    return archive
    

def generate_requirements(package, ignore=()):
    deps = []
    deps = package_deps(package, ignore=ignore)
    lines = []
    for d in sorted(deps):
        lines.append(
            '%s==%s' % (d, pkgmd.distribution(d).version))
    return '\n'.join(lines)

    
def package_deps(package, deps=None, ignore=()):
    if pkgmd is None:
        raise 
    if deps is None:
        deps = []
    pdeps = pkgmd.requires(package) or ()
    for r in pdeps:
        # skip optional deps
        if ';' in r:
            continue
        for idx, c in enumerate(r):
            if not c.isalnum() and c not in ('-', '_', '.'):
                break
        if idx + 1 == len(r):
            idx += 1
        pkg_name = r[:idx]
        if pkg_name in ignore:
            continue
        if pkg_name not in deps:
            deps.append(pkg_name)
            package_deps(pkg_name, deps, ignore)
    return deps


