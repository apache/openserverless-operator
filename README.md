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

In this readme there are information for developers.

We describe how to build and test the operator in our development environment

Please refer to the [website](https://openserverless.apache.org) for user information.

## How to build and use an operator image

Ensure you have satisfied the prerequisites below. Most notably, you need to use our development virtual machine and you
need write access to a GitHub repository.

Once you have satisfied the prerequisites, you can build an image you can use in the development machine.

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

## Prerequisites

1. Please set up and use a development VM [as described here](https://github.com/apache/openserverless)

2. With VSCode, access the development VM, open the workspace `openserverless/openserverless.code-workspace` and then
   open a terminal with `operator` subproject: this will enable the `nix` environment with direnv (provided by the VM).

3. Create a fork of `github.com/apache/openserverless-operator`

4. Copy .env.dist in .env and put your GitHub username in it

5. Since the build requires you push your sources in your repo, you need the credentials to access it. The fastest way
   is
   to [create a personal token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

6. Now set up a remote to access your repo and set it as your default upstream branch.

```
git remote add fork https://<GITHUB_USERNAME>:<GITHUB_TOKEN>@github.com/<GITHUB_USERNAME>/openserverless-operator
git branch -u https://github.com/<GITHUB_USERNAME>/openserverless-operator
```

That's it. Now you can use `task build` to build the image.

7. Deploy the operator

To deploy a testing configuration of the Apache OpenServerless operator execute the command

```shell
task all
```

The operator instance will be configured applying the `test/k3s/whisk.yaml` template.
All the components are activated except TLS and MONITORING.

