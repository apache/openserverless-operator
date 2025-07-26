# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
#------------------------------------------------------------------------------
# Sources
FROM python:3.12-slim-bullseye AS sources

RUN groupadd --gid 1001 nuvolaris && \
    useradd -m nuvolaris -s /bin/bash --uid 1001 --gid 1001 --groups root

USER nuvolaris
WORKDIR /home/nuvolaris
# install the operator
ADD --chown=nuvolaris:nuvolaris nuvolaris/*.py /home/nuvolaris/nuvolaris/
ADD --chown=nuvolaris:nuvolaris nuvolaris/files /home/nuvolaris/nuvolaris/files
ADD --chown=nuvolaris:nuvolaris nuvolaris/templates /home/nuvolaris/nuvolaris/templates
ADD --chown=nuvolaris:nuvolaris nuvolaris/policies /home/nuvolaris/nuvolaris/policies
ADD --chown=nuvolaris:nuvolaris deploy/nuvolaris-operator /home/nuvolaris/deploy/nuvolaris-operator
ADD --chown=nuvolaris:nuvolaris deploy/nuvolaris-permissions /home/nuvolaris/deploy/nuvolaris-permissions
ADD --chown=nuvolaris:nuvolaris deploy/openwhisk-standalone /home/nuvolaris/deploy/openwhisk-standalone
ADD --chown=nuvolaris:nuvolaris deploy/openwhisk-endpoint /home/nuvolaris/deploy/openwhisk-endpoint
ADD --chown=nuvolaris:nuvolaris deploy/couchdb /home/nuvolaris/deploy/couchdb
ADD --chown=nuvolaris:nuvolaris deploy/redis /home/nuvolaris/deploy/redis
ADD --chown=nuvolaris:nuvolaris deploy/scheduler /home/nuvolaris/deploy/scheduler
ADD --chown=nuvolaris:nuvolaris deploy/mongodb-operator /home/nuvolaris/deploy/mongodb-operator
ADD --chown=nuvolaris:nuvolaris deploy/mongodb-operator-deploy /home/nuvolaris/deploy/mongodb-operator-deploy
ADD --chown=nuvolaris:nuvolaris deploy/mongodb-standalone /home/nuvolaris/deploy/mongodb-standalone
ADD --chown=nuvolaris:nuvolaris deploy/cert-manager /home/nuvolaris/deploy/cert-manager
ADD --chown=nuvolaris:nuvolaris deploy/ingress-nginx /home/nuvolaris/deploy/ingress-nginx
ADD --chown=nuvolaris:nuvolaris deploy/issuer /home/nuvolaris/deploy/issuer
ADD --chown=nuvolaris:nuvolaris deploy/minio /home/nuvolaris/deploy/minio
ADD --chown=nuvolaris:nuvolaris deploy/kafka /home/nuvolaris/deploy/kafka
ADD --chown=nuvolaris:nuvolaris deploy/zookeeper /home/nuvolaris/deploy/zookeeper
ADD --chown=nuvolaris:nuvolaris deploy/nginx-static /home/nuvolaris/deploy/nginx-static
ADD --chown=nuvolaris:nuvolaris deploy/content /home/nuvolaris/deploy/content
ADD --chown=nuvolaris:nuvolaris deploy/postgres-operator /home/nuvolaris/deploy/postgres-operator
ADD --chown=nuvolaris:nuvolaris deploy/postgres-operator-deploy /home/nuvolaris/deploy/postgres-operator-deploy
ADD --chown=nuvolaris:nuvolaris deploy/ferretdb /home/nuvolaris/deploy/ferretdb
ADD --chown=nuvolaris:nuvolaris deploy/runtimes /home/nuvolaris/deploy/runtimes
ADD --chown=nuvolaris:nuvolaris deploy/postgres-backup /home/nuvolaris/deploy/postgres-backup
ADD --chown=nuvolaris:nuvolaris run.sh dbinit.sh cron.sh pyproject.toml poetry.lock whisk-system.sh /home/nuvolaris/

# prepares the required folders to deploy the whisk-system actions
RUN mkdir /home/nuvolaris/deploy/whisk-system
ADD --chown=nuvolaris:nuvolaris actions /home/nuvolaris/actions

# enterprise specific
ADD --chown=nuvolaris:nuvolaris deploy/openwhisk-enterprise /home/nuvolaris/deploy/openwhisk-enterprise
ADD --chown=nuvolaris:nuvolaris deploy/openwhisk-invoker /home/nuvolaris/deploy/openwhisk-invoker
ADD --chown=nuvolaris:nuvolaris deploy/monitoring /home/nuvolaris/deploy/monitoring
ADD --chown=nuvolaris:nuvolaris deploy/alert-manager /home/nuvolaris/deploy/alert-manager
ADD --chown=nuvolaris:nuvolaris deploy/quota /home/nuvolaris/deploy/quota
ADD --chown=nuvolaris:nuvolaris deploy/kvrocks /home/nuvolaris/deploy/kvrocks
ADD --chown=nuvolaris:nuvolaris deploy/etcd /home/nuvolaris/deploy/etcd
ADD --chown=nuvolaris:nuvolaris deploy/milvus-operator /home/nuvolaris/deploy/milvus-operator
ADD --chown=nuvolaris:nuvolaris deploy/milvus /home/nuvolaris/deploy/milvus
ADD --chown=nuvolaris:nuvolaris deploy/milvus-slim /home/nuvolaris/deploy/milvus-slim
ADD --chown=nuvolaris:nuvolaris deploy/registry /home/nuvolaris/deploy/registry
ADD --chown=nuvolaris:nuvolaris quota.sh /home/nuvolaris/

#------------------------------------------------------------------------------
# Python dependencies
FROM python:3.12-slim-bullseye AS deps

# --- Install Poetry ---
ARG POETRY_VERSION=1.8.5
ENV POETRY_HOME=/opt/poetry
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=1
ENV POETRY_VIRTUALENVS_CREATE=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_CACHE_DIR=/opt/.cache
ENV PATH=${POETRY_HOME}/bin:$PATH

WORKDIR /home/nuvolaris
COPY --chown=nuvolaris:nuvolaris pyproject.toml poetry.lock /home/nuvolaris/
RUN echo "Installing poetry" && \
    # Install minimal dependencies
    echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg zip unzip && \
    curl -sSL https://install.python-poetry.org | python - && \
    cd /home/nuvolaris && poetry install --no-root --no-interaction --no-ansi && rm -rf $POETRY_CACHE_DIR

#------------------------------------------------------------------------------
# Final stage
FROM python:3.12-slim-bullseye

ARG OPERATOR_IMAGE_DEFAULT=registry.hub.docker.com/apache/openserverless-operator
ARG OPERATOR_TAG_DEFAULT=0.1.0-testing.2309191654
ENV CONTROLLER_IMAGE=ghcr.io/nuvolaris/openwhisk-controller
ENV CONTROLLER_TAG=3.1.0-mastrogpt.2402101445
ENV INVOKER_IMAGE=ghcr.io/nuvolaris/openwhisk-invoker
ENV INVOKER_TAG=3.1.0-mastrogpt.2402101445
ENV OPERATOR_IMAGE=${OPERATOR_IMAGE_DEFAULT}
ENV OPERATOR_TAG=${OPERATOR_TAG_DEFAULT}
ENV TZ=Europe/London
ENV HOME=/home/nuvolaris
ENV VIRTUAL_ENV=/home/nuvolaris/.venv
ENV POETRY_HOME=/opt/poetry
ENV POETRY_CACHE_DIR=/opt/.cache
ENV PATH=$POETRY_HOME/bin:$HOME/.venv/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/sbin:/bin:/usr/sbin/
# configure dpkg && timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    # add nuvolaris user
    groupadd --gid 1001 nuvolaris && \
    useradd -m nuvolaris -s /bin/bash --uid 1001 --gid 1001 --groups root && \
    echo "nuvolaris ALL=(ALL:ALL) NOPASSWD: ALL" >>/etc/sudoers && \
    # Install minimal dependencies
    echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg zip unzip && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    # install kubectl
    KVER="v1.23.0" && \
    ARCH="$(dpkg --print-architecture)" && \
    curl -sL "https://dl.k8s.io/release/$KVER/bin/linux/$ARCH/kubectl" -o /usr/bin/kubectl && chmod +x /usr/bin/kubectl && \
    VER="v4.5.7" && \
    curl -sL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F$VER/kustomize_${VER}_linux_${ARCH}.tar.gz" | tar xzvf - -C /usr/bin && \
    # openwhisk cli
    WSK_VERSION=1.2.0 && \
    WSK_BASE=https://github.com/apache/openwhisk-cli/releases/download && \
    curl -sL "$WSK_BASE/$WSK_VERSION/OpenWhisk_CLI-$WSK_VERSION-linux-$ARCH.tgz" | tar xzvf - -C /usr/bin/ && \
    # install minio
    MINIO_BASE=https://dl.min.io/client/mc/release/linux && \
    MC_VER=RELEASE.2025-05-21T01-59-54Z && \
    curl -sL "$MINIO_BASE-$ARCH/archive/mc.${MC_VER}" -o /usr/bin/mc && chmod +x /usr/bin/mc && \
    # install taskfile
    curl -sL https://taskfile.dev/install.sh | sh -s -- -d -b /usr/bin

USER nuvolaris
WORKDIR /home/nuvolaris
# Copy virtualenv
COPY --from=deps --chown=nuvolaris:nuvolaris ${VIRTUAL_ENV} ${VIRTUAL_ENV}
# Copy poetry
COPY --from=deps --chown=nuvolaris:nuvolaris ${POETRY_HOME} ${POETRY_HOME}
# Copy the home
COPY --from=sources --chown=nuvolaris:nuvolaris ${HOME} ${HOME}
RUN poetry install --only main --no-interaction --no-ansi && rm -rf ${POETRY_CACHE_DIR}
# prepares the required folders to deploy the whisk-system actions
RUN mkdir -p /home/nuvolaris/deploy/whisk-system && \
    ./whisk-system.sh && \
    cd deploy && tar cvf ../deploy.tar *
CMD ["./run.sh"]