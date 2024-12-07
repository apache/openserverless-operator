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

import kopf, logging
import nuvolaris.kube as kube
import nuvolaris.kustomize as kus
import nuvolaris.config as cfg
import nuvolaris.util as util
import nuvolaris.operator_util as operator_util
import nuvolaris.minio_util as mutil
import nuvolaris.etcd as etcd

from nuvolaris.opaque_secret import OpaqueSecret
from nuvolaris.minio_util import MinioClient

def create(owner=None):
    """
    Deploys the milvus vector db using milvus operator and wait for the operator to be ready.
    """
    logging.info("*** creating milvus-operator")        
    mv_cm_data = util.milvus_manager_affinity_tolerations_data()
    mv_op_kust = kus.patchTemplates("milvus-operator",templates=["affinity-tolerance-dep-core-attach.yaml"], data=mv_cm_data)
    spec = kus.kustom_list("milvus-operator",mv_op_kust, templates=[], data={})

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.milvus-operator.spec", spec)

    res = kube.apply(spec)    
    #wait for milvus_operator to be ready
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.app\.kubernetes\.io\/instance == 'milvus-operator')].metadata.name}")
    logging.info("*** created milvus operator")

    return res

def delete_by_owner():
    spec = kus.build("milvus-operator")
    res = kube.delete(spec)    
    logging.info(f"delete milvus-operator: {res}") 
    return res

def delete_by_spec():
    spec = cfg.get("state.milvus-operator.spec")
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete milvus-operator: {res}")        
    return res

def delete(owner=None):
    if owner:        
        return delete_by_owner()
    else:
        return delete_by_spec()

def patch(status, action, owner=None):
    """
    Called by the operator patcher to create/delete milvus component
    """
    try:
        logging.info(f"*** handling request to {action} milvus")  
        if  action == 'create':
            msg = create(owner)
            operator_util.patch_operator_status(status,'milvus','on')            
        else:
            msg = delete(owner)            
            operator_util.patch_operator_status(status,'milvus','off')

        logging.info(msg)        
        logging.info(f"*** handled request to {action} milvus") 
    except Exception as e:
        logging.error('*** failed to update milvus: %s' % e)        
        operator_util.patch_operator_status(status,'milvus','error')