<!--
  ~ Licensed to the Apache Software Foundation (ASF) under one
  ~ or more contributor license agreements.  See the NOTICE file
  ~ distributed with this work for additional information
  ~ regarding copyright ownership.  The ASF licenses this file
  ~ to you under the Apache License, Version 2.0 (the
  ~ "License"); you may not use this file except in compliance
  ~ with the License.  You may obtain a copy of the License at
  ~
  ~   http://www.apache.org/licenses/LICENSE-2.0
  ~
  ~ Unless required by applicable law or agreed to in writing,
  ~ software distributed under the License is distributed on an
  ~ "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
  ~ KIND, either express or implied.  See the License for the
  ~ specific language governing permissions and limitations
  ~ under the License.
  ~
-->

# Apache OpenServerless Operator

In this README we explain how to do development with the Operator

The operator is a collection of modules managed with ops. 

The operator itself is an ops plugin to invoke some of functions from the command line.

To work with it, install ops and clone the source code from the top level, so you get the operator code under `openserverless/operator-op`

```
curl -sL bit.ly/get-ops | bash
git clone https://github.com/apache/openserverless --recurse-submodules
cd openserverless
```

To be able to work with the operator you need a Kubernetes cluster and a Working configuration. 

You can easily create one with kind:

```
# destroy the old one
ops op clu kind destroy
# create a new cluster
ops op clu kind create
```

If you want to use kubectl directory use `ops util kubeconfig` 
to export the kind configurat to `~/.kube/config`. WARNING it overwrites yout existing one.

## Configuration

You need a full configuration to be able to work with the operator. 

You can create an actual configuration on the cluster skipping the launch of the operator:

For example this is a config of slim mode:

```
# configure slim mode for example 
ops config slim
# configure
ops setup kubernetes configure
```

## Execute the operator as a cli plugin

Many modules are now executable as `ops op nuvolaris`  commands.

For example: `ops op nuv etcd`

It shows the subcommand with `create [<replicas>]` and `delete` 

## Working on the cli

You can also test and work on the cli. Try this:

```
ops op cli
```

Initialize the configuration:

```
import nuvolaris.operator_util as operator_util
owner = kube.get("wsk/controller")
operator_util.config_from_spec(owner['spec'])
```

Create the components:

```
import nuvolaris.etcd as etcd
msg = etcd.create(owner)
```

## How to publish the operator image

When you are satisfied with your development you can publish the image.

First, install [task](http://taskfile.dev/docs/installation).

You need to setup some environment variables. Copy .env.dist in .env and put your GitHub username in it

Since the build requires you push your sources in your repo, you need the credentials to access it. The fastest way is
to [create a personal token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

Build an image with:

```shell
task build
```

Please note that it will build the image locally and push in an internal registry, even if it is name is
`ghcr.io/${GITHUB_USER}/openserverless-operator`.

To be able to build, the task `build` will commit and push all your changes and then build the operator from the public
sources in your local k3s.

It will also show the logs for the latest build.

You can then deploy it with:

```shell
task deploy
```

Once you have finished with development you can create a public image with `task publish` that will publish the tag and
trigger a creation of the image.

Once the image is publicly available you have to put in in `opsroot.json` to use it:

```
https://github.com/apache/openserverless-task/blob/9d2227b87196be9b487673d4d1f8202c2ec354f2/opsroot.json#L8
```