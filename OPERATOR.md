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

## Redis graceful shutdown

The Redis command uses `exec` so the server is process 1 and receives the
container stop signal. With RDB save points configured, this permits Redis to
complete its final snapshot during an ordinary pod replacement. The termination
grace period must still be sufficient for the dataset being saved.

Existing installations must apply the updated Redis StatefulSet command through
their component deployment procedure; updating only the operator image does not
rewrite an existing StatefulSet. During the first rollout from the old shell
command, arrange an authenticated `SHUTDOWN SAVE` for the old Redis process before
it can be forcibly terminated. Subsequent ordinary replacements use the corrected
signal path. This does not change RDB/AOF policy or preserve unsaved RDB writes
after a hard crash or `SIGKILL`. ACL identity persistence is a separate concern.

## Customization notes

OpenServerless operator is normally deployed using a `whisk.yaml` configuration file which is applied via the installer. 
Typically, the customization file contains something like:

```
apiVersion: openserverless.org/v1
kind: Whisk
metadata:
  name: controller
  namespace: openserverless
spec:
  openserverless:
      apihost: <ip address or hostname to be assigned to openserverless controller ingress>
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
    # seaweedfs enabled or not
    seaweedfs: true
    # start kafka
    kafka: true
    # start openwhisk invoker
    invoker: true 
    # zookeeper enabled or not
    zookeeper: true               
  openwhisk:
    namespaces:
      whisk-system: xxxx:yyyyyy
      openserverless: ccccc:zzzzz
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
    openserverless:
      user: <mongodb_db_openserverless_user>
      password: <mongodb_db_openserverless_pwd>    
    useOperator: False
  scheduler:
    schedule: "* * * * *"
  tls:
    acme-registered-email: xxxxx@youremailserver.com
    acme-server-url: https://acme-staging-v02.api.letsencrypt.org/directory
  seaweedfs:
    volume-size: 2
    openserverless:
      user: <seaweedfs_admin_user>
      password: <seaweedfs_admin_pwd>
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
kubectl -n openserverless apply -f whisk.yaml
```

## Deploying the controller in lean-mode

The enterprise operator supports also the deployment of the sole controller in lean mode, by simply applying a `whisk.yaml` containing

```
apiVersion: openserverless.org/v1
kind: Whisk
metadata:
  name: controller
  namespace: openserverless
spec:
  openserverless:
      apihost: <ip address or hostname to be assigned to openserverless controller ingress>
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
    # seaweedfs enabled or not
    seaweedfs: true
    # start kafka
    kafka: false
    # start openwhisk invoker
    invoker: false 
    # zookeeper enabled or not
    zookeeper: false 
...
```

In lean mode it is recommended to set at least `configs.controller.javaOpts=-Xmx2048M`

## Redis ACL persistence

With `redis.persistence-enabled: true`, Redis stores its ACLs in
`/bitnami/redis/data/users.acl` on the existing Redis data PVC. Account creation,
reconciliation, quota permission changes and successful revocation save the
current authorized state. An RDB data snapshot alone does not contain ACL users.

On a fresh installation an init container creates the initial default-user ACL
with the configured administrator password hash. It never overwrites an existing
ACL file and refuses an empty existing file. The system and tenant accounts are
then provisioned and saved through the normal operator lifecycle.

On operator resume, an existing persistent Redis first saves its live ACL state,
then updates the managed ConfigMap to load that file on the next Redis restart.
Because `aclfile` is immutable at runtime, account changes made before that
first restart also update the file atomically through protected stdin. This
preparation does not restart Redis or replay old ACL exports. Credentials,
key/channel grants, read-only state and successful revocations are preserved.
A failed save stops configuration migration rather than enabling a missing file.
Existing explicitly configured ACL files retain their configured storage path.

When data persistence is disabled, this change does not introduce an ACL volume
or enable file persistence; ephemeral storage retains its existing semantics.
This fix concerns identity persistence, not the independent RDB snapshot schedule
or recovery of data that was never saved.
