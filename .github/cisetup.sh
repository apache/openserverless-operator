#!/bin/bash
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
sudo sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin
sudo apt-get -y install python3.11 python3.11-venv curl wget jq
WSK_VERSION=1.2.0
WSK_BASE=https://github.com/apache/openwhisk-cli/releases/download
ARCH=amd64
WSK_URL="$WSK_BASE/$WSK_VERSION/OpenWhisk_CLI-$WSK_VERSION-linux-$ARCH.tgz"
curl -sSL https://install.python-poetry.org | python3.11 -
curl -sSL "$WSK_URL" | tar xzvf - -C ~/.local/bin/
VER="v4.5.4"
ARCH="$(dpkg --print-architecture)"
URL="https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F$VER/kustomize_${VER}_linux_${ARCH}.tar.gz"
curl -sL $URL | tar tzvf - -C ~/.local/bin
YQ_VER=v4.27.2
YQ_BIN=yq_linux_amd64
sudo wget https://github.com/mikefarah/yq/releases/download/${YQ_VER}/${YQ_BIN} -O /usr/bin/yq && sudo chmod +x /usr/bin/yq
MC_VER=RELEASE.2023-03-23T20-03-04Z
sudo wget https://dl.min.io/client/mc/release/linux-${ARCH}/archive/mc.${MC_VER} -O /usr/bin/mc && sudo chmod +x /usr/bin/mc
#URL="https://dl.k8s.io/release/$VER/bin/linux/$ARCH/kubectl"
#curl -sSL "$URL" | sudo tee /usr/local/bin/kubectl && sudo chmod +x /usr/bin/kubectl
#kubectl version
