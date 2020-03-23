"""
Azure SDKS are full of generated stuff that no one cares about to the tune of
at least a 100Mb of fluff on an sdk data set size of 300Mb+.
"""

import click
import importlib
import os
import shutil
from c7n.resources import load_resources
from c7n.provider import clouds


@click.command()
@click.option('--remove', default=False, is_flag=True)
def main(remove):
    load_resources('azure.*')
    service_clients = set()
    for k, v in clouds['azure'].resources.items():
        service_clients.add((
            v.resource_type.service,
            v.resource_type.client))

    total_files = 0
    total_size = 0
    for module, klass in sorted(service_clients):
        if not klass:
            continue

        _module = importlib.import_module(module)
        _klass = getattr(_module, klass)
        default_version = getattr(_klass, 'DEFAULT_API_VERSION', None)
        mod_dir = os.path.dirname(_module.__file__)
        versions = [m for m in os.listdir(mod_dir)
                    if m.startswith('v') and m[1].isdigit()]
        if len(versions) < 2:
            continue
        default_version = "v%s" % default_version.replace('.', '_').replace('-', '_')
        versions.remove(default_version)
        size = 0
        fcount = 0
        for v in versions:
            for root, dirs, files in os.walk(os.path.join(mod_dir, v)):
                for f in files:
                    size += os.path.getsize(os.path.join(root, f))
                fcount += 1
            if remove:
                shutil.rmtree(os.path.join(mod_dir, v))
        total_files += fcount
        total_size += size
        human_size = GetHumanSize(size)
        print(f"{module}: {default_version} removed {fcount} files {human_size} saved")

    human_size = GetHumanSize(total_size)
    print(f"removed {total_files} files {human_size} saved")

    

def GetHumanSize(size, precision=2):
    # interesting discussion on 1024 vs 1000 as base
    # https://en.wikipedia.org/wiki/Binary_prefix
    suffixes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    suffixIndex = 0
    while size > 1024:
        suffixIndex += 1
        size = size / 1024.0

    return "%.*f %s" % (precision, size, suffixes[suffixIndex])


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import sys, traceback, pdb
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])

        
