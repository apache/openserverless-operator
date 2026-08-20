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
import kopf, logging, json
import nuvolaris.kube as kube
import nuvolaris.kustomize as kus
import nuvolaris.config as cfg
import nuvolaris.enterprise_util as cfg_util
import nuvolaris.util as util

def get_zookeeper_pod_name():
    pod_name = kube.kubectl("get", "pods", jsonpath="{.items[?(@.metadata.labels.app == 'zookeeper')].metadata.name}")
    if(pod_name):
        return pod_name[0]

    return None

def get_zookeeper_connect_data():
    pod_name = get_zookeeper_pod_name()
    zoo_container = kube.kubectl("get", f"pods/{pod_name}", jsonpath="{.spec.containers[?(@.name == 'zookeeper')].ports[?(@.name == 'zookeeper')]}")
    if(zoo_container):
        zoo_data = zoo_container[0]
        return f"{pod_name}.{zoo_data['name']}:{zoo_data['containerPort']}"

    return None    

def create(owner=None):
    logging.info("*** configuring zookeeper")

    data = cfg_util.get_zookeeper_config_data()
    
    tplp = ["zookeeper-001-pvc.yaml","zookeeper-002-pvc.yaml"]
    if(data['affinity'] or data['tolerations']):
       tplp.append("affinity-tolerance-sts-core-attach.yaml")      

    kust = kus.patchTemplates("zookeeper", tplp, data)
    spec = kus.kustom_list("zookeeper", kust, templates=[], data=data)

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.zookeeper.spec", spec)


    res = kube.apply(spec)

    # dynamically detect zookeeper pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.app == 'zookeeper')].metadata.name}")    
    cfg.put("nuvolaris.zookeeper.url",get_zookeeper_connect_data())    
    logging.info(f"zookeeper connection string is {cfg.get('nuvolaris.zookeeper.url')}")

    logging.info("*** configured zookeeper")
    return res

def delete():
    spec = cfg.get("state.zookeeper.spec")
    res = False
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete zookeeper: {res}")
    return res

