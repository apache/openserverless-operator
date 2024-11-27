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

def patchEntries(data: dict):
    kust = kus.patchTemplates("milvus", ["milvus-cfg-base.yaml","milvus.yaml"], data)
    kust += kus.patchGenericEntry("Secret","nuvolaris-milvus-etcd-secret","/data/username",util.b64_encode(data['milvus_etcd_username']))
    kust += kus.patchGenericEntry("Secret","nuvolaris-milvus-etcd-secret","/data/password",util.b64_encode(data['milvus_etcd_password']))

    kust += kus.patchGenericEntry("Secret","nuvolaris-milvus-s3-secret","/stringData/accesskey",data['milvus_s3_username'])
    kust += kus.patchGenericEntry("Secret","nuvolaris-milvus-s3-secret","/stringData/secretkey",data['milvus_s3_password'])

    kust += kus.patchGenericEntry("PersistentVolumeClaim","nuvolaris-milvus","/spec/storageClassName",data['storageClass'])
    kust += kus.patchGenericEntry("PersistentVolumeClaim","nuvolaris-milvus","/spec/resources/requests/storage",f"{data['size']}Gi")

    kust += kus.patchGenericEntry("PersistentVolumeClaim","nuvolaris-milvus-zookeeper","/spec/storageClassName",data['storageClass'])
    kust += kus.patchGenericEntry("PersistentVolumeClaim","nuvolaris-milvus-zookeeper","/spec/resources/requests/storage",f"{data['zookeeper_size']}Gi")        

    kust += kus.patchGenericEntry("PersistentVolumeClaim","nuvolaris-milvus-bookie-journal","/spec/storageClassName",data['storageClass'])
    kust += kus.patchGenericEntry("PersistentVolumeClaim","nuvolaris-milvus-bookie-journal","/spec/resources/requests/storage",f"{data['bookie_journal_size']}Gi")

    kust += kus.patchGenericEntry("PersistentVolumeClaim","nuvolaris-milvus-bookie-ledgers","/spec/storageClassName",data['storageClass'])
    kust += kus.patchGenericEntry("PersistentVolumeClaim","nuvolaris-milvus-bookie-ledgers","/spec/resources/requests/storage",f"{data['bookie_ledgers_size']}Gi")
    return kust 

def create(owner=None):
    """
    Deploys the milvus vector db in standalone mode.
    """
    data = util.get_milvus_config_data()  
    res = create_milvus_accounts(data) 

    if res:
        logging.info("*** creating a milvus standalone instance")
        
        kust = patchEntries(data)
        mspec = kus.kustom_list("milvus", kust, templates=[], data=data)

        if owner:
            kopf.append_owner_reference(mspec['items'], owner)
        else:
            cfg.put("state.milvus.spec", mspec)

        res = kube.apply(mspec)

    return res

def create_milvus_accounts(data:dict):
    """"
    Creates technical accounts for ETCD and MINIO
    """
    try:        
        # currently we use the ETCD root password, so we skip the ETCD user creation.
        #res = util.check(etcd.create_etcd_user(data['milvus_etcd_username'],data['milvus_etcd_password'],data['milvus_etcd_prefix']),"create_etcd_milvus_user",True)

        minioClient = mutil.MinioClient()
        bucket_policy_names = []
        bucket_policy_names.append(f"{data['milvus_bucket_name']}/*")

        res = util.check(minioClient.add_user(data["milvus_s3_username"], data["milvus_s3_password"]),"create_milvus_s3_user",True)
        res = util.check(minioClient.make_bucket(data["milvus_bucket_name"]),"create_milvus_s3_bucket",res)
        return util.check(minioClient.assign_rw_bucket_policy_to_user(data["milvus_s3_username"], bucket_policy_names),"assign_milvus_s3_bucket_policy",res)
    except Exception as ex:
        logging.error("Could not create milvus ETCD and MINIO accounts",ex)
        return False

def delete_by_owner():
    spec = kus.build("milvus")
    res = kube.delete(spec)
    logging.info(f"delete milvus: {res}")    
    return res

def delete_by_spec():
    spec = cfg.get("state.milvus.spec")    
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete milvus: {res}")

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