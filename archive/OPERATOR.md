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

This is the Kubernetes Operator of the [Apache OpenServerless (incubating) project](https://openserverless.apache.org).

## Publishing the operator

Once the operator is ready, you can build and test it against a kubernetes cluster.
First, generate a new image tag with `task image-tag`.
You can test locally using the kind cluster (provided by default by the development environment) with `build-and-load`.

To test it against other clusters, you need to publish it to the Apache OpenServerless private repository on 
[Docker Hub](https://hub.docker.com/r/apache/openserverless-operator).

To do this, add to your `.env` the following variables:

```
MY_CONTROLLER_IMAGE=<your-user>/<your-name>
DOCKER_HUB_USER=<docker.hub user>
DOCKER_HUB_TOKEN=<docker hub token>
```

To override the tag of the operator you have to generate a git tag: `task image-tag`. Note the tag is unique for the 
current hour (it embeds: YYMMDDhh).

If you set those variables you can use 
- `task docker-login` to log to the current docker.hub registry
- `task build-and-push` to build for one single architecture (faster but limited to your architecture)
- `task buildx-and-push` to build for all the architectures (slower, used by the GitHub action)
- `task docker-hub-authorize` to upload to the current kubernetes runtime a secret to give the possibility to download 
   the operator enterprise image

## Customization notes

OpenServerless operator is normally deployed using a `whisk.yaml` configuration file which is applied via the installer. 
Typically, the customization file contains something like:

```
apiVersion: nuvolaris.org/v1
kind: Whisk
metadata:
  name: controller
  namespace: nuvolaris
spec:
  nuvolaris:
      apihost: <ip address or hostname to be assigned to nuvolaris controller ingress>
  components:
    # start openwhisk controller
    openwhisk: true   
    # start couchdb
    couchdb: true
    # start mongodb
    mongodb: true
    # start redis
    redis: true  
    # start simple internal cron     
    cron: true 
    # tls enabled or not
    tls: false
    # minio enabled or not
    minio: true
    # start kafka
    kafka: true
    # start openwhisk invoker
    invoker: true 
    # zookeeper enabled or not
    zookeeper: true               
  openwhisk:
    namespaces:
      whisk-system: xxxx:yyyyyy
      nuvolaris: ccccc:zzzzz
  couchdb:
    host: couchdb
    port: 5984
    volume-size: 10
    admin:
      user: <couch_db_admin_user>
      password: <couch_db_admin_pwd>
    controller:
      user: <couch_db_controller_user>
      password: <couch_db_controller_user>
  mongodb:
    host: mongodb
    volume-size: 10
    admin: 
      user: <mongodb_db_admin_user>
      password: <mongodb_db_admin_pwd>
    nuvolaris:
      user: <mongodb_db_nuvolaris_user>
      password: <mongodb_db_nuvolaris_pwd>    
    useOperator: False
  scheduler:
    schedule: "* * * * *"
  tls:
    acme-registered-email: xxxxx@youremailserver.com
    acme-server-url: https://acme-staging-v02.api.letsencrypt.org/directory
  minio:
    volume-size: 2
    nuvolaris:
      root-user: <minio_admin_user>
      root-password: <minio_admin_pwd>
  configs:    
    limits:
      actions:
        sequence-maxLength: 50
        invokes-perMinute: 999
        invokes-concurrent: 250
      triggers: 
        fires-perMinute: 999
      time:
        limit-min: "100ms"  
        limit-std: "1min"
        limit-max: "5min"
      memory:
        limit-min: "128m"
        limit-std: "256m"
        limit-max: "512m" 
    controller:
      javaOpts: "-Xmx2048M"
    invoker:
      javaOpts: "-Xmx2048M"
      containerPool:
        userMemory: "4096m"             
```

## Default configs values
If the provided `whisk.yaml` does not specify any dynamic configuration parameters under `configs` item, the Enterprise 
operators defaults to these values:

- `configs.limit.actions.sequence-maxLength=50`
- `configs.limit.actions.invokes-perMinute=60`
- `configs.limit.actions.invokes-concurrent=30`
- `configs.limit.actions.triggers.fires-perMinute=60`
- `configs.limits.time.limit-min=100ms`
- `configs.limits.time.limit-std=1min`
- `configs.limits.time.limit-max=5min`
- `configs.limits.memory.limit-min=128m`
- `configs.limits.memory.limit-std=256m`
- `configs.limits.memory.limit-max=512m`
- `configs.controller.javaOpts=-Xmx1024M`
- `configs.controller.loggingLevel=INFO`
- `configs.invoker.javaOpts=-Xmx1024M`
- `configs.invoker.loggingLevel=INFO`
- `configs.invoker.containerPool.userMemory=2048m`

## Openwhisk Enterprise hot deployment

The enterprise operator supports hot deployment for both Openwhisk Controller & Invoker, i.e. it is possible to modify 
some specific part of the configuration inside the `whisk.yaml` file and apply it again. The operator will automatically 
stop and redeploy controller & invoker to take into account the new settings.

```
  configs:    
    limits:
      actions:
        sequence-maxLength: 50
        invokes-perMinute: 999
        invokes-concurrent: 250
      triggers: 
        fires-perMinute: 999
      time:
        limit-min: "100ms"  
        limit-std: "1min"
        limit-max: "5min"
      memory:
        limit-min: "128m"
        limit-std: "256m"
        limit-max: "512m" 
    controller:
      javaOpts: "-Xmx2048M"
      loggingLevel: "INFO"
    invoker:
      javaOpts: "-Xmx2048M"
      loggingLevel: "INFO"
      containerPool:
        userMemory: "4096m"       
```

As an example, using the above configuration and taking into account the standard 256m memory size limit per action, 
gives the possibility to execute around 16 action concurrently 
[`As a general rule consider it as the result of controller.javaOpts/256m`]. To increase the number of estimated action 
that can be executed modify for example `controller.javaOpts:"-Xmx8192M"` and redeploy the modified `whisk.yaml`.

To apply the new customization execute:

```shell
kubectl -n nuvolaris apply -f whisk.yaml
```

## Deploying the controller in lean-mode

The enterprise operator supports also the deployment of the sole controller in lean mode, by simply applying a `whisk.yaml` containing

```
apiVersion: nuvolaris.org/v1
kind: Whisk
metadata:
  name: controller
  namespace: nuvolaris
spec:
  nuvolaris:
      apihost: <ip address or hostname to be assigned to nuvolaris controller ingress>
  components:
    # start openwhisk controller
    openwhisk: true   
    # start couchdb
    couchdb: true
    # start mongodb
    mongodb: true
    # start redis
    redis: true  
    # start simple internal cron     
    cron: true 
    # tls enabled or not
    tls: false
    # minio enabled or not
    minio: true
    # start kafka
    kafka: false
    # start openwhisk invoker
    invoker: false 
    # zookeeper enabled or not
    zookeeper: false 
...
```

In lean mode it is recommended to set at least `configs.controller.javaOpts=-Xmx2048M`