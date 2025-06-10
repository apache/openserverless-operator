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
import nuvolaris.operator_util as operator_util

def create(owner=None):
    logging.info("creating quota cheker scheduled job")
   
    img = cfg.get('operator.image') or "missing-operator-image"
    tag = cfg.get('operator.tag') or "missing-operator-tag"

    image = f"{img}:{tag}"
    logging.info("quota job using image %s", image)

    #default to every minutes if not configured
    schedule = cfg.get('quota.schedule') or "*/10 * * * *"
    password = cfg.get("redis.default.password") or "s0meP@ass3"
 
    data = {
        "image": image,
        "schedule": schedule,
        "name": "quota-checker",
        "redis_password": password
    }
    
    try: 
        kust = kus.patchTemplate("quota", "quota-cronjob-attach.yaml", data)
        spec = kus.kustom_list("quota", kust, templates=[], data=data)

        if owner:
            kopf.append_owner_reference(spec['items'], owner)
        else:
            cfg.put("state.quota.spec", spec)

        res = kube.apply(spec)
        logging.info(f"create quota: {res}")
        return res
    except Exception as ex:
       logging.error('*** failed to create quota: %s' % ex)
       return None      

def delete_by_owner():
    try:
        spec = kus.build("quota")
        res = kube.delete(spec)
        logging.info(f"delete quota: {res}")
        return res
    except Exception as ex:
       logging.error('*** failed to delete quota by owner: %s' % ex)
       return None     

def delete_by_spec():
    try:
        spec = cfg.get("state.quota.spec")
        res = False
        if spec:
            res = kube.delete(spec)
            logging.info(f"delete quota: {res}")
        return res
    except Exception as ex:
       logging.error('*** failed to delete quota by spec: %s' % ex)
       return None 

def delete(owner=None):
    if owner:        
        return delete_by_owner()
    else:
        return delete_by_spec()

def patch(status, action, owner=None):
    """
    Called by the operator patcher to create/delete quota component
    """
    try:
        logging.info(f"*** handling request to {action} quota")  
        if  action == 'create':
            msg = create(owner)
            operator_util.patch_operator_status(status,'quota','on') 
        else:
            msg = delete(owner)
            operator_util.patch_operator_status(status,'quota','off')

        logging.info(msg)        
        logging.info(f"*** hanlded request to {action} quota") 
    except Exception as e:
        logging.error('*** failed to update quota: %s' % e)
        operator_util.patch_operator_status(status,'quota','error')       