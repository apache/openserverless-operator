#
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

{% if mode == 'create' %}
etcdctl role add {{username}}_role --user root:$ETCD_ROOT_PASSWORD --write-out="simple"
etcdctl role grant-permission {{username}}_role readwrite {{prefix}}/ --user root:$ETCD_ROOT_PASSWORD --write-out="simple" --prefix=true
etcdctl user add {{username}} --new-user-password {{password}} --user root:$ETCD_ROOT_PASSWORD --write-out="simple"
etcdctl user grant-role {{username}} {{username}}_role --user root:$ETCD_ROOT_PASSWORD --write-out="simple"
{% endif %}

{% if mode == 'delete' %}
etcdctl del {{prefix}}/ --prefix=true --user root:$ETCD_ROOT_PASSWORD --write-out="simple"
etcdctl user revoke-role {{username}} {{username}}_role --user root:$ETCD_ROOT_PASSWORD --write-out="simple"
etcdctl role delete {{username}}_role --user root:$ETCD_ROOT_PASSWORD --write-out="simple"
etcdctl user delete {username}} --user root:$ETCD_ROOT_PASSWORD --write-out="simple"
{% endif %}