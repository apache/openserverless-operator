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
#
# Deploys a standalone mongodb
#

import kopf
import json, time
import nuvolaris.kube as kube
import nuvolaris.kustomize as kus
import nuvolaris.config as cfg
import nuvolaris.enterprise_util as ent_util
import nuvolaris.util as util
import logging

def create(owner=None):
    """
    Configuring the operator monitoring via prometheus.
    """
    logging.info("*** creating prometheus based monitoring")
    alert_manager = cfg.get("monitoring.alert-manager.enabled") or False

    if alert_manager:        
        logging.info("*** enabling prometheus alert-manager")
        data = ent_util.get_am_config_data()
        kus.renderTemplate("alert-manager","pvc-create.yaml",data,"alertmanager-01-pvc_generated.yaml")

        tplp = ["alert-manager-02-cm.yaml"]
        if(data['affinity'] or data['tolerations']):
            tplp.append("affinity-tolerance-dep-core-attach.yaml") 

        kust = kus.patchTemplates("alert-manager", tplp, data)
        am_spec = kus.kustom_list("alert-manager", kust, templates=[], data=data)

        if owner:
            kopf.append_owner_reference(am_spec['items'], owner)
        else:
            cfg.put("state.alertmanager.spec", am_spec)

        res = kube.apply(am_spec)
        # dynamically detect alert manager pod and wait for readiness
        util.wait_for_pod_ready("{.items[?(@.metadata.labels.app\.kubernetes\.io\/name == 'alertmanager')].metadata.name}")   
    
    what = []
    spec = ""
    prometheus_data = ent_util.get_prometheus_config_data()    
    kus.renderTemplate("monitoring","pvc-create.yaml",prometheus_data,"prometheus-01-pvc_generated.yaml")
    p_tplp = []

    if prometheus_data['applypodsecurity']:
        logging.info("*** enabling prometheus pod security")
        prometheus_data["kind"]="Deployment"
        prometheus_data["fs_group"]=65534
        prometheus_data["run_as_user"]=65534
        p_tplp.append("security-global-attach.yaml")

    if(data['affinity'] or data['tolerations']):
       p_tplp.append("affinity-tolerance-dep-core-attach.yaml")         

    if len(p_tplp) > 0 :
        kust = kus.patchTemplates("monitoring",p_tplp,prometheus_data)
        spec = kus.kustom_list("monitoring", kust,templates=[], data={})
    else:    
        spec = kus.kustom_list("monitoring", *what) 

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.prometheus.spec", spec)

    res = kube.apply(spec)

    # dynamically detect prometheus pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.app\.kubernetes\.io\/name == 'prometheus')].metadata.name}")
 
    logging.info("*** created prometheus based monitoring")    
    return res 

def delete_by_owner():
    alert_manager = cfg.get("monitoring.alert-manager.enabled") or False

    spec = kus.build("monitoring")
    res = kube.delete(spec)
    logging.info(f"delete prometheus: {res}")

    if alert_manager:
         spec = kus.build("alert-manager")
         res = kube.delete(spec)
         logging.info(f"delete alert-manager: {res}")

    return res

def delete_by_spec():
    prometheus_spec = cfg.get("state.prometheus.spec")
    alert_manager_spec = cfg.get("state.alertmanager.spec")
    res = False
    if prometheus_spec:
        res = kube.delete(prometheus_spec)
        logging.info(f"delete prometheus: {res}")
            
    if alert_manager_spec:
        res = kube.delete(alert_manager_spec)
        logging.info(f"delete alert manager: {res}")

    return res

def delete(owner=None):
    if owner:       
        return delete_by_owner()
    else:
        return delete_by_spec()

def patch(status, action, owner=None):
    """
    Called the the operator patcher to create/delete monitoring
    """
    try:
        logging.info(f"*** handling request to {action} monitoring")  
        if  action == 'create':
            msg = create(owner)
            status['whisk_create']['monitoring']='on'
        else:
            msg = delete(owner)
            status['whisk_create']['monitoring']='off'

        logging.info(msg)        
        logging.info(f"*** handled request to {action} monitoring") 
    except Exception as e:
        logging.error('*** failed to update monitoring: %s' % e)
        status['whisk_create']['monitoring']='error'           