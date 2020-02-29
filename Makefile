
install:
	python3 -m venv .
	. bin/activate && pip install -r requirements-dev.txt
	. bin/activate && pip install -e .
	. bin/activate && pip install -r tools/c7n_mailer/requirements.txt
	. bin/activate && pip install -r tools/c7n_azure/requirements.txt
	. bin/activate && pip install -r tools/c7n_gcp/requirements.txt
	. bin/activate && pip install -r tools/c7n_kube/requirements.txt

sync-requirements:
	poetry export --without-hashes -f requirements.txt > requirements.txt
	poetry export --dev --without-hashes -f requirements.txt > requirements-ci.txt
	# ci uses requirements-dev.txt to install all of tools
	# poetry export --dev -f requirements.txt > requirements-dev.txt
	cd tools/c7n_gcp && poetry export --without-hashes -f requirements.txt > requirements.txt
	cd tools/c7n_azure && poetry export --without-hashes -f requirements.txt > requirements.txt
	cd tools/c7n_kube && poetry export --without-hashes -f requirements.txt > requirements.txt
	cd tools/c7n_org && poetry export --without-hashes -f requirements.txt > requirements.txt
	cd tools/c7n_mailer && poetry export --without-hashes -f requirements.txt > requirements.txt
	cd tools/c7n_logexporter && poetry export --without-hashes -f requirements.txt > requirements.txt
	cd tools/c7n_policystream && poetry export --without-hashes -f requirements.txt > requirements.txt
	cd tools/c7n_trailcreator && poetry export --without-hashes -f requirements.txt > requirements.txt

sync-update:
	poetry update
	cd tools/c7n_gcp && poetry update
	cd tools/c7n_azure && poetry update
	cd tools/c7n_kube && poetry update
	cd tools/c7n_org && poetry update
	cd tools/c7n_mailer && poetry update
	cd tools/c7n_logexporter && poetry update
	cd tools/c7n_policystream && poetry update
	cd tools/c7n_trailcreator && poetry update

sync-show:
	poetry show -o
	cd tools/c7n_gcp && poetry show -o
	cd tools/c7n_azure && poetry show -o
	cd tools/c7n_kube && poetry show -o
	cd tools/c7n_org && poetry show -o
	cd tools/c7n_mailer && poetry show -o
	cd tools/c7n_logexporter && poetry show -o
	cd tools/c7n_policystream && poetry show -o
	cd tools/c7n_trailcreator && poetry show -o

sync-frozen-setup:
	python3 tools/dev/poetrypkg.py gen-frozensetup -p .
	python3 tools/dev/poetrypkg.py gen-frozensetup -p tools/c7n_gcp
	python3 tools/dev/poetrypkg.py gen-frozensetup -p tools/c7n_azure
	python3 tools/dev/poetrypkg.py gen-frozensetup -p tools/c7n_kube
	python3 tools/dev/poetrypkg.py gen-frozensetup -p tools/c7n_org
	python3 tools/dev/poetrypkg.py gen-frozensetup -p tools/c7n_mailer
	python3 tools/dev/poetrypkg.py gen-frozensetup -p tools/c7n_logexporter
	python3 tools/dev/poetrypkg.py gen-frozensetup -p tools/c7n_policystream
	python3 tools/dev/poetrypkg.py gen-frozensetup -p tools/c7n_trailcreator

sync-setup:
	python3 tools/dev/poetrypkg.py gen-setup -p .
	python3 tools/dev/poetrypkg.py gen-setup -p tools/c7n_gcp
	python3 tools/dev/poetrypkg.py gen-setup -p tools/c7n_azure
	python3 tools/dev/poetrypkg.py gen-setup -p tools/c7n_kube
	python3 tools/dev/poetrypkg.py gen-setup -p tools/c7n_org
	python3 tools/dev/poetrypkg.py gen-setup -p tools/c7n_mailer
	python3 tools/dev/poetrypkg.py gen-setup -p tools/c7n_logexporter
	python3 tools/dev/poetrypkg.py gen-setup -p tools/c7n_policystream
	python3 tools/dev/poetrypkg.py gen-setup -p tools/c7n_trailcreator

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

