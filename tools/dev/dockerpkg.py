# Copyright 2020 Kapil Thangavelu
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# flake8: noqa
# just want to disable E501 long lines on this file.

"""
Generate Cloud Custodian Dockerfiles
"""
import click

from pathlib import Path


BUILD_STAGE = """\
# Dockerfiles are generated from tools/dev/dockerpkg.py

FROM {base_build_image} as build-env

# pre-requisite distro deps, and build env setup
RUN adduser --disabled-login custodian
RUN apt-get --yes update
RUN apt-get --yes install build-essential curl python3-venv python3-dev --no-install-recommends
RUN python3 -m venv /usr/local
RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3

WORKDIR /src

# Add core & aws packages
ADD pyproject.toml poetry.lock README.md /src/
ADD c7n /src/c7n/
RUN . /usr/local/bin/activate && $HOME/.poetry/bin/poetry install --no-dev
RUN . /usr/local/bin/activate && pip install -q aws-xray-sdk psutil jsonpatch

# Add provider packagees
ADD tools/c7n_gcp /src/tools/c7n_gcp
RUN rm -R tools/c7n_gcp/tests
ADD tools/c7n_azure /src/tools/c7n_azure
RUN rm -R tools/c7n_azure/tests_azure
ADD tools/c7n_kube /src/tools/c7n_kube
RUN rm -R tools/c7n_kube/tests

# Install requested providers
ARG providers="azure gcp kube"
RUN . /usr/local/bin/activate && for pkg in $providers; do cd tools/c7n_$pkg && $HOME/.poetry/bin/poetry install && cd ../../; done


RUN mkdir /output
"""

TARGET_UBUNTU_STAGE = """\
FROM {base_target_image}

LABEL name="{name}" \\
      description="{description}" \\
      repository="http://github.com/cloud-custodian/cloud-custodian" \\
      homepage="http://github.com/cloud-custodian/cloud-custodian" \\
      maintainer="Custodian Community <https://cloudcustodian.io>"

COPY --from=build-env /src /src
COPY --from=build-env /usr/local /usr/local
COPY --from=build-env /etc/passwd /etc/passwd
COPY --from=build-env /etc/group /etc/group
COPY --from=build-env /output /output

RUN apt-get --yes update \\
        && apt-get --yes install python3 python3-venv --no-install-recommends \\
        && rm -Rf /var/cache/apt \\
        && rm -Rf /var/lib/apt/lists/* \\
        && rm -Rf /var/log/*

USER custodian
WORKDIR /home/custodian
ENV LC_ALL="C.UTF-8" LANG="C.UTF-8"
VOLUME ["/home/custodian"]
ENTRYPOINT ["{entrypoint}"]
CMD ["--help"]
"""


TARGET_DISTROLESS_STAGE = """\
FROM {base_target_image}

LABEL name="{name}" \\
      description="{description}" \\
      repository="http://github.com/cloud-custodian/cloud-custodian" \\
      homepage="http://github.com/cloud-custodian/cloud-custodian" \\
      maintainer="Custodian Community <https://cloudcustodian.io>"

COPY --from=build-env /src /src
COPY --from=build-env /usr/local /usr/local
COPY --from=build-env /etc/passwd /etc/passwd
COPY --from=build-env /etc/group /etc/group
COPY --from=build-env /output /output

USER custodian
WORKDIR /home/custodian
ENV LC_ALL="C.UTF-8" LANG="C.UTF-8"
VOLUME ["/home/custodian"]
ENTRYPOINT ["{entrypoint}"]
CMD ["--help"]
"""


BUILD_ORG = """\
# Install c7n-org
ADD tools/c7n_org /src/tools/c7n_org
RUN . /usr/local/bin/activate && cd tools/c7n_org && $HOME/.poetry/bin/poetry install
"""

BUILD_MAILER = """\
# Install c7n-mailer
ADD tools/c7n_mailer /src/tools/c7n_mailer
RUN . /usr/local/bin/activate && cd tools/c7n_mailer && $HOME/.poetry/bin/poetry install
"""

BUILD_POLICYSTREAM = """\
# Compile libgit2
RUN apt-get -y install wget cmake libssl-dev libffi-dev git
RUN mkdir build && \\
        wget -q https://github.com/libgit2/libgit2/releases/download/v1.0.0/libgit2-1.0.0.tar.gz && \\
        cd build && \\
        tar xzf ../libgit2-1.0.0.tar.gz && \\
        cd libgit2-1.0.0 && \\
        mkdir build && cd build && \\
        cmake .. && \\
        make install && \\
        rm -Rf /src/build

# Install c7n-policystream
ADD tools/c7n_policystream /src/tools/c7n_policystream
RUN . /usr/local/bin/activate && cd tools/c7n_policystream && $HOME/.poetry/bin/poetry install

# Verify the install
#  - policystream is not in ci due to libgit2 compilation needed
#  - as a sanity check to distributing known good assets / we test here
RUN . /usr/local/bin/activate && pytest tools/c7n_policystream
"""


class Image:

    defaults = dict(
        base_build_image="ubuntu:20.04",
        base_target_image="ubuntu:20.04")

    def __init__(self, metadata, build, target):
        self.metadata = metadata
        self.build = build
        self.target = target

    def render(self):
        output = []
        output.extend(self.build)
        output.extend(self.target)
        template_vars = dict(self.defaults)
        template_vars.update(self.metadata)
        return "\n".join(output).format(**template_vars)

    def clone(self, metadata, target=None):
        d = dict(self.metadata)
        d.update(metadata)
        return Image(d, self.build, target or self.target)


ImageMap = {
    'docker/cli': Image(
        dict(name='custodian',
             description='Cloud Management Rules Engine',
             entrypoint='/usr/local/bin/custodian'),
        build=[BUILD_STAGE],
        target=[TARGET_UBUNTU_STAGE]),
    'docker/org': Image(
        dict(name='c7n-org',
             description="Cloud Custodian Organization Runner",
             entrypoint='/usr/local/bin/c7n-org'),
        build=[BUILD_STAGE, BUILD_ORG],
        target=[TARGET_UBUNTU_STAGE]),
    'docker/mailer': Image(
        dict(name='mailer',
             description="Cloud Custodian Notification Delivery",
             entrypoint='/usr/local/bin/c7n-mailer'),
        build=[BUILD_STAGE, BUILD_MAILER],
        target=[TARGET_UBUNTU_STAGE]
    ),
    'docker/policystream': Image(
        dict(name='policystream',
             description="Custodian policy changes streamed from Git",
             entrypoint='/usr/local/bin/c7n-policystream'),
        build=[BUILD_STAGE, BUILD_POLICYSTREAM],
        target=[TARGET_UBUNTU_STAGE]
    )
}


for name, image in list(ImageMap.items()):
    ImageMap[name + '-distroless'] = image.clone(
        dict(
            base_build_image='debian:10-slim',
            base_target_image='gcr.io/distroless/python3-debian10'),
        target=[TARGET_DISTROLESS_STAGE])


@click.command()
def main():
    for df_path, image in ImageMap.items():
        p = Path(df_path)
        p.write_text(image.render())


if __name__ == '__main__':
    main()
