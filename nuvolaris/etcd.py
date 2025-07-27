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

import nuvolaris.kustomize as kus
import nuvolaris.kube as kube
import nuvolaris.config as cfg
import nuvolaris.template as ntp
import nuvolaris.util as util
import os.path
import logging
import kopf

from nuvolaris.util import get_etcd_replica


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
    kust += kus.patchGenericEntry("Secret","nuvolaris-etcd-secret","/data/rootPassword",util.b64_encode(data['root_password']))   
    spec = kus.kustom_list("etcd", kust, templates=spec_templates, data=data)

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.etcd.spec", spec)
    res = kube.apply(spec)

    wait_for_etcd_ready()

    logging.info(f"create etcd: {res}")
    return res

def wait_for_etcd_ready():
    # dynamically detect etcd pod and wait for readiness
    util.wait_for_pod_ready(r"{.items[?(@.metadata.labels.app\.kubernetes\.io\/name == 'nuvolaris-etcd')].metadata.name}")

def render_etcd_script(namespace,template,data):
    """
    uses the given template to render a sh script to execute via bash shell.
    """  
    out = f"/tmp/__{namespace}_{template}"
    file = ntp.spool_template(template, out, data)
    return os.path.abspath(file)

def exec_etcd_script(pod_name,path_to_etcd_script):
    logging.info(f"passing script {path_to_etcd_script} to pod {pod_name}")
    res = kube.kubectl("cp",path_to_etcd_script,f"{pod_name}:{path_to_etcd_script}")
    res = kube.kubectl("exec","-i",pod_name,"--","/bin/bash","-c",f"chmod +x {path_to_etcd_script}")
    res = kube.kubectl("exec","-i",pod_name,"--","/bin/bash","-c",path_to_etcd_script)
    os.remove(path_to_etcd_script)    
    return res
    

def create_etcd_user(username:str, password:str, prefix:str):
    """
    Creates a new ETCD username with the given password and assign redwrite permission on the given prefix
    return: True if operation succeed, False otherwise.
    """
    logging.info(f"authorizing new ETCD user {username} on prefix {prefix}")

    try:
        data = {}
        data["username"]=username
        data["password"]=password
        data["prefix"]=prefix
        data["mode"]="create"       

        path_to_etcd_script = render_etcd_script(username,"etcd_manage_user_tpl.sh",data)        
        pod_name = util.get_pod_name_by_selector("name=nuvolaris-etcd","{.items[0].metadata.name}")

        if(pod_name):
            res = exec_etcd_script(pod_name,path_to_etcd_script)  
            if res:
                return True
            else:
                logging.error(f"failed to add ETCD username {username}") 
                return False

        return False
    except Exception as e:
        logging.error(f"failed to add ETCD username {username}: {e}")
        return False

def delete_db_user(username):
    """
    Reomves the specified user from the ETCD instance.
    """
    logging.info(f"removing ETCD user {username}")
    try:
        data = {}
        data["username"]=username
        data["mode"]="delete"

        path_to_etcd_script = render_etcd_script(username,"etcd_manager_user_tpl.sh",data)        
        pod_name = util.get_pod_name_by_selector("name=nuvolaris-etcd","{.items[0].metadata.name}")

        if(pod_name):
            res = exec_etcd_script(pod_name,path_to_etcd_script)  
            if res:
                return res
            else:
                logging.error(f"failed to remove ETCD username {username}") 

        return None
    except Exception as e:
        logging.error(f"failed to remove ETCD username {username} authorization id and key: {e}")
        return None        

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