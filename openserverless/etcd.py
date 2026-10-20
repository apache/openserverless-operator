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

import openserverless.kustomize as kus
import openserverless.kube as kube
import openserverless.config as cfg
import openserverless.template as ntp
import openserverless.util as util
from openserverless import datastore_security
from openserverless.etcd_admin import create_etcd_user, delete_db_user
import os.path
import logging
import kopf

from openserverless.util import get_etcd_replica


def create(owner=None):
    logging.info("create etcd")
    data = util.get_etcd_config_data()
    
    tplp = ["resources-sts-attach.yaml","etcd-sts.yaml"]

    if(data['affinity'] or data['tolerations']):
       tplp.append("affinity-tolerance-sts-core-attach.yaml")

    spec_templates = []
    replicas = get_etcd_replica()
    if replicas > 1:
        spec_templates.append("etcd-policy.yaml")

    kust = kus.patchTemplates("etcd",tplp , data)
    kust += kus.patchGenericEntry("Secret","openserverless-etcd-secret","/data/rootPassword",util.b64_encode(data['root_password']))   
    datastore_security.ensure_jwt_key(owner)
    spec = kus.restricted_kustom_list("etcd", kust, templates=spec_templates, data=data,
        templates_filter=["etcd-secret.yaml", "etcd-sts.yaml", "etcd-svc.yaml"])
    spec["items"].append(datastore_security.policy("etcd"))

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.etcd.spec", spec)
    res = datastore_security.apply(spec)

    kube.kubectl("rollout", "status", "statefulset/openserverless-etcd", "--timeout=300s")
    wait_for_etcd_ready()
    kube.kubectl("delete", "secret", "openserverless-etcd-jwt-token", "--ignore-not-found")

    logging.info(f"create etcd: {res}")
    return res

def wait_for_etcd_ready():
    # dynamically detect etcd pod and wait for readiness
    util.wait_for_pod_ready(r"{.items[?(@.metadata.labels.app\.kubernetes\.io\/name == 'openserverless-etcd')].metadata.name}")

def delete_by_owner():
    spec = kus.build("etcd")
    res = kube.delete(spec)
    logging.info(f"delete etcd: {res}")
    return res

def delete_by_spec():
    spec = cfg.get("state.etcd.spec")
    res = False
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete etcd: {res}")
        return res

def delete(owner=None):
    if owner:        
        return delete_by_owner()
    else:
        return delete_by_spec()    

def patch(status, action, owner=None):
    """
    Called the the operator patcher to create/delete etcd
    """
    try:
        logging.info(f"*** handling request to {action} etcd")  
        if  action == 'create':
            msg = create(owner)
            status['whisk_create']['etcd']='on'
        else:
            msg = delete(owner)
            status['whisk_create']['etcd']='off'

        logging.info(msg)        
        logging.info(f"*** handled request to {action} etcd") 
    except Exception as e:
        logging.error('*** failed to update etcd: %s' % e)
        if  action == 'create':
            status['whisk_create']['etcd']='error'
        else:            
            status['whisk_create']['etcd']='error'