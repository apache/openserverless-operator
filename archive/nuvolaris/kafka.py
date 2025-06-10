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
import nuvolaris.enterprise_util as cfg_util
import nuvolaris.util as util

def get_kafka_pod_name():
    pod_name = kube.kubectl("get", "pods", jsonpath="{.items[?(@.metadata.labels.app == 'kafka')].metadata.name}")
    if(pod_name):
        return pod_name[0]

    return None

def get_kafka_connect_data():
    pod_name = get_kafka_pod_name()
    kafka_container = kube.kubectl("get", f"pods/{pod_name}", jsonpath="{.spec.containers[?(@.name == 'kafka')].ports[?(@.name == 'kafka')]}")
    if(kafka_container):
        kafka_data = kafka_container[0]
        return f"{kafka_data['name']}:{kafka_data['containerPort']}"

    return None    

def create(owner=None):
    logging.info(f"*** configuring kafka")
    zookeeper_url = cfg.get("nuvolaris.zookeeper.url") or "zookeeper-0.zookeeper:2181"
    zookeper_data = zookeeper_url.split(":")

    data = cfg_util.get_kafka_config_data()
    data["zookeeper_url"] = zookeeper_url
    data["zookeeper_host"] = zookeper_data[0]
    data["zookeeper_port"] = zookeper_data[1]
    
    tplp = ["kafka-000-pvc.yaml","kafka-001-sts.yaml"]
    if(data['affinity'] or data['tolerations']):
       tplp.append("affinity-tolerance-sts-core-attach.yaml")  
    
    kust = kus.patchTemplates("kafka",tplp, data)
    spec = kus.kustom_list("kafka", kust, templates=[], data=data)

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.kafka.spec", spec)


    res = kube.apply(spec)

    # dynamically detect kafka pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.app == 'kafka')].metadata.name}")
    cfg.put("nuvolaris.kafka.url",get_kafka_connect_data())    
    logging.info(f"kafka connection string is {cfg.get('nuvolaris.kafka.url')}")    

    logging.info("*** configured kafka")
    return res

def delete():
    spec = cfg.get("state.kafka.spec")
    res = False
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete kafka: {res}")
    return res