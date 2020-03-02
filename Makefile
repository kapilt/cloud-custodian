
PKG_SET = tools/c7n_gcp tools/c7n_azure tools/c7n_kube tools/c7n_mailer tools/c7n_logexporter tools/c7n_policystream tools/c7n_trailcreator

install:
	python3 -m venv .
	. bin/activate && pip install -r requirements-ci.txt \
            -r tools/c7n_mailer/requirements.txt \
	    -r tools/c7n_azure/requirements.txt \
            -r tools/c7n_gcp/requirements.txt \
            -r tools/c7n_kube/requirements.txt \
            -r tools/requirements-dev.txt

pkg-update:
	poetry update
	for pkg in $(PKG_SET); do pushd $$pkg && poetry update && popd; done

pkg-show-update:
	poetry show -o
	for pkg in $(PKG_SET); do pushd $$pkg && poetry show -o && popd; done

pkg-freeze-setup:
	python3 tools/dev/poetrypkg.py gen-frozensetup -p .
	for pkg in $(PKG_SET); do python3 tools/dev/poetrypkg.py gen-frozensetup -p $$pkg; done

pkg-gen-setup:
	python3 tools/dev/poetrypkg.py gen-setup -p .
	for pkg in $(PKG_SET); do python3 tools/dev/poetrypkg.py gen-setup -p $$pkg; done

pkg-gen-requirements:
# we have todo without hashes due to https://github.com/pypa/pip/issues/4995
	poetry export --without-hashes -f requirements.txt > requirements.txt
	poetry export --dev --without-hashes -f requirements.txt > requirements-ci.txt
	for pkg in $(PKG_SET); do pushd $$pkg && poetry export --without-hashes -f requirements.txt > requirements.txt && popd; done

test:
	./bin/tox -e py27

test3:
	./bin/tox -e py37

ftest:
	C7N_FUNCTIONAL=yes AWS_DEFAULT_REGION=us-east-2 ./bin/py.test -m functional tests

sphinx:
	make -f docs/Makefile.sphinx clean && \
	make -f docs/Makefile.sphinx html

ghpages:
	-git checkout gh-pages && \
	mv docs/build/html new-docs && \
	rm -rf docs && \
	mv new-docs docs && \
	git add -u && \
	git add -A && \
	git commit -m "Updated generated Sphinx documentation"

lint:
	flake8 c7n tests tools

clean:
	rm -rf .tox .Python bin include lib pip-selfcheck.json

