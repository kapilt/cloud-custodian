.. _developer-installing:

Installing for Developers
=========================

Installing Prerequisites
------------------------

Cloud Custodian supports Python 3.6, 3.7, 3.8 and above. To develop the
Custodian, you will need to have a make/C toolchain, Python3 and some
basic Python tools.


Install Python 3
~~~~~~~~~~~~~~~~

You'll need to have a Python 3 environment set up.
You may have a preferred way of doing this.
Here are instructions for a way to do it on Ubuntu and Mac OS X.

On Ubuntu
*********

On most recent versions of Ubuntu, Python 3 is included by default.

To get Python 3.8, first add the deadsnakes package repository:

.. code-block:: bash

    $ sudo add-apt-repository ppa:deadsnakes/ppa

Next, install python3.8 and the development headers for it:

.. code-block:: bash

    $ sudo apt-get install python3.8 python3.8-dev

Then, install ``pip``:

.. code-block::

    $ sudo apt-get install python3-pip

When this is complete you should be able to check that you have pip properly installed:

.. code-block::

    $ python3.8 -m pip --version
    pip 9.0.1 from /usr/lib/python3/dist-packages (python 3.8)

(your exact version numbers will likely differ)


On macOS with Homebrew
**********************

.. code-block:: bash

    $ brew install python3

Installing ``python3`` will get you the latest version of Python 3 supported by Homebrew, currently Python 3.7.


Basic Python Tools
~~~~~~~~~~~~~~~~~~

Once your Python installation is squared away, you will need to install ``tox`` and ``virtualenv``:

.. code-block:: bash

    $ python3.7 -m pip install -U pip virtualenv tox

(note that we also updated ``pip`` in order to get the latest version)


Installing Custodian
--------------------

First, clone the repository:

.. code-block:: bash

    $ git clone https://github.com/cloud-custodian/cloud-custodian.git
    $ cd cloud-custodian

Then build the software with `tox <https://tox.readthedocs.io/en/latest/>`_:

.. code-block:: bash

    $ tox

Tox creates a sandboxed "virtual environment" ("virtualenv") for each Python version, 3.6, 3.7, 3.8
These are stored in the ``.tox/`` directory.
It then runs the test suite under all versions of Python, per the ``tox.ini`` file.
If tox is unable to find a Python executable on your system for one of the supported versions, it will fail for that environment.
You can safely ignore these failures when developing locally.

You can run the test suite in a single enviroment with the ``-e`` flag:

.. code-block:: bash

    $ tox -e py38

To access the executables installed in one or the other virtual environment,
source the virtualenv into your current shell, e.g.:

.. code-block:: bash

    $ source .tox/py37/bin/activate

You should then have, e.g., the ``custodian`` command available:

.. code-block:: bash

    (py37)$ custodian -h

You'll also be able to invoke `pytest <https://docs.pytest.org/en/latest/>`_ directly
with the arguments of your choosing, e.g.:

.. code-block:: bash

    (py37) $ pytest tests/test_s3.py -x -k replication

Note you'll have to environment variables setup appropriately per the tox.ini
for provider credentials.


Packaging Custodian
-------------------

Custodian moved to using ``poetry`` https://python-poetry.org/ for
managing dependencies and providing for repeatable installs. Its not
typically required for developers as we maintain setuptools/pip/tox
compatible environments, however familiarity is needed when making
changes to the dependency graph (add/update/remove) dependencies,
as all the setup.py/requirements files are generated artifacts.

The reasoning around the move to poetry was that of needing better
tooling to freeze the custodian dependency graph when publishing
packages to pypi to ensure that releases would be repeatably
installable at a future date inspite of changes to the underlying
dependency graph, some perhaps not obeying semantic versioning
principles. Additionally with the growth of providers and other tools,
we wanted better holistic management for release automation across the
set of packages. After experimenting with a few tools in the
ecosystem, including building our own, the maintainers settled on
poetry as one that offered both a superior ux, was actively
maintained, and had a reasonable python api for additional release
management activities.

Our additional tooling around poetry is to help automate management
across the half-dozen custodian packages as well as to keep
requirements and setup.py files intact. We continue to use
setuptools/pip in our CI infrastructure as it offers significant speed
benefits [0]. To ensure the poetry install is exercised as part of CI,
we do maintain the main docker image via poetry.

Usage
*****

We maintain several makefile targets that can be used to front end
poetry.

  - `make install-poetry` an alternative custodian installation method, assumes
    poetry is already installed.

  - `make pkg-show-update` show available updates to packages in poetry
    lockfiles.

  - `make pkg-update` attempts to update dependencies across the tree,
    should be followed by gen-requirements/gen-setup below.

  - `make pkg-gen-requirements` show available updates to packages in poetry
    lockfiles.

  - `make pkg-gen-setup` generate setup.py files from pyproject.toml
    this will carry over semver constraints.

  - `make pkg-freeze-setup` generate setup.py files from pyproject.toml
    with all dependencies frozen in setup.py. Note this is not currently
    transitive on the dep graph, just direct dependencis.

  - `make pkg-publish-wheel` increments version, builds wheels, lints,
    and publishes build to testpypi via twine.

- [0] poetry will call out to pip as a subprocess per package to
  control the exact versions installed, as pip does not have a public
  api.


Workarounds
***********

To maintain within repo dependencies betweeen packages, we specify all
within intra repo dependencies as dev dependencies with relative
directory source paths. when we generate setup.py files we do so sans
any dev deps, which we resolve in generation to the latest version,
frozen or semver compatible per source dir dev dep). one interesting
consequence of this in addition to the pyproject.toml spec is the
build-system, the invocation of poetry as a build sys is transparently
handled by pip, but the simple resolution of dev dependencies will
cause a failure for an sdist, as installation of an sdist, is actually
a wheel compilation. instead as a publishing limitation we only
publish wheels instead of sdists which avoids the build system entirely,
as a wheel is extractable installation container/format file.
