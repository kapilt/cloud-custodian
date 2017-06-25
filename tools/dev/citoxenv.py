#!/usr/bin/env python
import os
pyenv = "%s-cov" % (os.environ.get(
    'TRAVIS_PYTHON_VERSION', '').replace('python', 'py').replace('.', ''))
toxenv = [pyenv, 'lint']
if pyenv == 'py27-cov':
    toxenv.append('docs')
print ",".join(toxenv)
