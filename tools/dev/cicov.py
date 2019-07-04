#!/usr/bin/env python2

import subprocess
import os
import logging

log = logging.getLogger('cicov')

# https://docs.microsoft.com/en-us/azure/devops/pipelines/build/variables?view=vsts


def main():
    logging.basicConfig(level=logging.INFO)

    for k in os.environ.keys():
        if k.startswith('BUILD') or k.startswith('SYSTEM'):
            v = os.environ[k]
            log.info("Env var %s=%s" % (k, v))

if __name__ == '__main__':
    main()
