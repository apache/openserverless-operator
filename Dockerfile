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

RUN groupadd --gid 1001 openserverless && \
    useradd -m openserverless -s /bin/bash --uid 1001 --gid 1001 --groups root

USER openserverless
WORKDIR /home/openserverless
# install the operator
ADD --chown=openserverless:openserverless openserverless/*.py /home/openserverless/openserverless/
ADD --chown=openserverless:openserverless openserverless/files /home/openserverless/openserverless/files
ADD --chown=openserverless:openserverless openserverless/templates /home/openserverless/openserverless/templates
ADD --chown=openserverless:openserverless openserverless/policies /home/openserverless/openserverless/policies
ADD --chown=openserverless:openserverless deploy/openserverless-operator /home/openserverless/deploy/openserverless-operator
ADD --chown=openserverless:openserverless deploy/openserverless-permissions /home/openserverless/deploy/openserverless-permissions
ADD --chown=openserverless:openserverless deploy/openwhisk-standalone /home/openserverless/deploy/openwhisk-standalone
ADD --chown=openserverless:openserverless deploy/openwhisk-endpoint /home/openserverless/deploy/openwhisk-endpoint
ADD --chown=openserverless:openserverless deploy/couchdb /home/openserverless/deploy/couchdb
ADD --chown=openserverless:openserverless deploy/redis /home/openserverless/deploy/redis
ADD --chown=openserverless:openserverless deploy/scheduler /home/openserverless/deploy/scheduler
ADD --chown=openserverless:openserverless deploy/mongodb-operator /home/openserverless/deploy/mongodb-operator
ADD --chown=openserverless:openserverless deploy/mongodb-operator-deploy /home/openserverless/deploy/mongodb-operator-deploy
ADD --chown=openserverless:openserverless deploy/mongodb-standalone /home/openserverless/deploy/mongodb-standalone
ADD --chown=openserverless:openserverless deploy/cert-manager /home/openserverless/deploy/cert-manager
ADD --chown=openserverless:openserverless deploy/ingress-nginx /home/openserverless/deploy/ingress-nginx
ADD --chown=openserverless:openserverless deploy/issuer /home/openserverless/deploy/issuer
ADD --chown=openserverless:openserverless deploy/minio /home/openserverless/deploy/minio
ADD --chown=openserverless:openserverless deploy/kafka /home/openserverless/deploy/kafka
ADD --chown=openserverless:openserverless deploy/zookeeper /home/openserverless/deploy/zookeeper
ADD --chown=openserverless:openserverless deploy/nginx-static /home/openserverless/deploy/nginx-static
ADD --chown=openserverless:openserverless deploy/content /home/openserverless/deploy/content
ADD --chown=openserverless:openserverless deploy/postgres-operator /home/openserverless/deploy/postgres-operator
ADD --chown=openserverless:openserverless deploy/postgres-operator-deploy /home/openserverless/deploy/postgres-operator-deploy
ADD --chown=openserverless:openserverless deploy/ferretdb /home/openserverless/deploy/ferretdb
ADD --chown=openserverless:openserverless deploy/runtimes /home/openserverless/deploy/runtimes
ADD --chown=openserverless:openserverless deploy/postgres-backup /home/openserverless/deploy/postgres-backup
ADD --chown=openserverless:openserverless run.sh dbinit.sh cron.sh pyproject.toml poetry.lock whisk-system.sh /home/openserverless/

# prepares the required folders to deploy the whisk-system actions
RUN mkdir /home/openserverless/deploy/whisk-system
ADD --chown=openserverless:openserverless actions /home/openserverless/actions

# enterprise specific
ADD --chown=openserverless:openserverless deploy/openwhisk-enterprise /home/openserverless/deploy/openwhisk-enterprise
ADD --chown=openserverless:openserverless deploy/openwhisk-invoker /home/openserverless/deploy/openwhisk-invoker
ADD --chown=openserverless:openserverless deploy/monitoring /home/openserverless/deploy/monitoring
ADD --chown=openserverless:openserverless deploy/alert-manager /home/openserverless/deploy/alert-manager
ADD --chown=openserverless:openserverless deploy/quota /home/openserverless/deploy/quota
ADD --chown=openserverless:openserverless deploy/kvrocks /home/openserverless/deploy/kvrocks
ADD --chown=openserverless:openserverless deploy/etcd /home/openserverless/deploy/etcd
ADD --chown=openserverless:openserverless deploy/milvus-operator /home/openserverless/deploy/milvus-operator
ADD --chown=openserverless:openserverless deploy/milvus /home/openserverless/deploy/milvus
ADD --chown=openserverless:openserverless deploy/milvus-slim /home/openserverless/deploy/milvus-slim
ADD --chown=openserverless:openserverless deploy/registry /home/openserverless/deploy/registry
ADD --chown=openserverless:openserverless deploy/seaweedfs /home/openserverless/deploy/seaweedfs
ADD --chown=openserverless:openserverless quota.sh /home/openserverless/

#------------------------------------------------------------------------------
# Python dependencies
FROM python:3.12-slim-bullseye AS deps

# --- Install Poetry ---
ARG POETRY_VERSION=2.3.2
ENV POETRY_HOME=/opt/poetry
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=1
ENV POETRY_VIRTUALENVS_CREATE=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_CACHE_DIR=/opt/.cache
ENV PATH=${POETRY_HOME}/bin:$PATH

WORKDIR /home/openserverless
COPY --chown=openserverless:openserverless pyproject.toml poetry.lock /home/openserverless/
RUN echo "Installing poetry" && \
    # Install minimal dependencies
    echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg zip unzip && \
    curl -sSL https://install.python-poetry.org | python - && \
    cd /home/openserverless && poetry install --no-root --no-interaction --no-ansi && rm -rf $POETRY_CACHE_DIR

#------------------------------------------------------------------------------
# Final stage
FROM python:3.12-slim-bullseye

ARG OPERATOR_IMAGE_DEFAULT=docker.io/apache/openserverless-operator
ARG OPERATOR_TAG_DEFAULT=0.1.0-testing.2309191654
ENV CONTROLLER_IMAGE=ghcr.io/nuvolaris/openwhisk-controller
ENV CONTROLLER_TAG=3.1.0-mastrogpt.2402101445
ENV INVOKER_IMAGE=ghcr.io/nuvolaris/openwhisk-invoker
ENV INVOKER_TAG=3.1.0-mastrogpt.2402101445
ENV OPERATOR_IMAGE=${OPERATOR_IMAGE_DEFAULT}
ENV OPERATOR_TAG=${OPERATOR_TAG_DEFAULT}
ENV TZ=Europe/London
ENV HOME=/home/openserverless
ENV VIRTUAL_ENV=/home/openserverless/.venv
ENV POETRY_HOME=/opt/poetry
ENV POETRY_CACHE_DIR=/opt/.cache
ENV PATH=$POETRY_HOME/bin:$HOME/.venv/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/sbin:/bin:/usr/sbin/
# configure dpkg && timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    # add openserverless user
    groupadd --gid 1001 openserverless && \
    useradd -m openserverless -s /bin/bash --uid 1001 --gid 1001 --groups root && \
    echo "openserverless ALL=(ALL:ALL) NOPASSWD: ALL" >>/etc/sudoers && \
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

USER openserverless
WORKDIR /home/openserverless
# Copy virtualenv
COPY --from=deps --chown=openserverless:openserverless ${VIRTUAL_ENV} ${VIRTUAL_ENV}
# Copy poetry
COPY --from=deps --chown=openserverless:openserverless ${POETRY_HOME} ${POETRY_HOME}
# Copy the home
COPY --from=sources --chown=openserverless:openserverless ${HOME} ${HOME}
RUN poetry install --only main --no-interaction --no-ansi && rm -rf ${POETRY_CACHE_DIR}
# prepares the required folders to deploy the whisk-system actions
RUN mkdir -p /home/openserverless/deploy/whisk-system && \
    ./whisk-system.sh && \
    cd deploy && tar cvf ../deploy.tar *
CMD ["./run.sh"]