FROM python:3.6

LABEL name="mailer" \
      description="Cloud Custodian Notification Delivery" \
      repository="http://github.com/cloud-custodian/cloud-custodian" \
      homepage="https://cloudcustodian.io" \
      maintainer="Custodian Community <https://cloudcustodian.io>"

# Note this must be run from the root directory of the checkout
# as we install custodian w/ aws, azure, and gcp support from the same
# repo.

ADD . /src

# Install Custodian Core & AWS
WORKDIR /src
RUN pip3 install -r requirements.txt -e .

# Install Custodian Azure
WORKDIR /src/tools/c7n_azure
RUN pip3 install -r requirements.txt -e .

# Install Custodian Mailer
WORKDIR /src/tools/c7n_mailer
RUN pip3 install -r requirements.txt -e .
ENV LC_ALL="C.UTF-8" LANG="C.UTF-8"

ENTRYPOINT ["c7n-mailer"]
