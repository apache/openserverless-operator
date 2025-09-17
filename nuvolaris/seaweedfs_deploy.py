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
import kopf, logging, time, os
import nuvolaris.kube as kube
import nuvolaris.kustomize as kus
import nuvolaris.config as cfg
import nuvolaris.util as util
import nuvolaris.openwhisk as openwhisk
import nuvolaris.seaweedfs_ingress as seaweedfs_ingress
import nuvolaris.operator_util as operator_util

from nuvolaris.user_config import UserConfig
from nuvolaris.user_metadata import UserMetadata
from nuvolaris.seaweedfs_util import SeaweedfsClient

def _get_seaweedfs_service():
    return util.get_service("{.items[?(@.spec.selector.app == 'seaweedfs')]}")

def _add_seaweedfs_user_metadata(ucfg: UserConfig, user_metadata:UserMetadata):
    """
    adds entries for seaweedfs connectivity S3_HOST, S3_PORT, S3_ACCESS_KEY, S3_SECRET_KEY    
    """ 

    try:
        seaweed_service =  _get_seaweedfs_service()
        if(seaweed_service):
            seaweedfs_host = f"{seaweed_service['metadata']['name']}.{seaweed_service['metadata']['namespace']}.svc.cluster.local"
            access_key = ucfg.get('namespace')
            secret_key = ucfg.get("object-storage.password")
            user_metadata.add_metadata("S3_PROVIDER","seaweedfs")
            user_metadata.add_metadata("S3_HOST",seaweedfs_host)
            user_metadata.add_metadata("S3_ACCESS_KEY",access_key)
            user_metadata.add_metadata("S3_SECRET_KEY",secret_key)

            user_metadata.add_safely_from_cm("S3_API_URL", '{.metadata.annotations.s3_api_url}')
            user_metadata.add_safely_from_cm("S3_CONSOLE_URL", '{.metadata.annotations.s3_console_url}')

            ports = list(seaweed_service['spec']['ports'])
            for port in ports:
                if(port['name']=='s3-api'):
                    user_metadata.add_metadata("S3_PORT",port['port'])

        return None
    except Exception as e:
        logging.error(f"failed to build SEAWEEDFS metadata for {ucfg.get('namespace')}: {e}")
        return None 

def create(owner=None):
    logging.info("*** configuring seaweedfs standalone")

    data = util.get_seaweedfs_config_data()

    tplp = ["pvc-attach.yaml"]

    if(data['affinity'] or data['tolerations']):
       tplp.append("affinity-tolerance-sts-core-attach.yaml")    

    kust = kus.patchTemplates("seaweedfs", tplp, data)
    spec = kus.kustom_list("seaweedfs", kust, templates=[], data=data)

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.seaweedfs.spec", spec)

    res = kube.apply(spec)

    # dynamically detect seaweedfs pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.app == 'seaweedfs')].metadata.name}")
    seaweedfs_ingress.create_seaweedfs_ingresses(data, owner)

    logging.info("*** waiting for seaweedfs filer api to be available")    
    util.wait_for_http(util.get_seaweedds_filer_host(), up_statuses=[200,401], timeout=30)

    create_seaweedfs_nuv_storage(data)  

    logging.info("*** configured seaweedfs standalone")
    return res

def _annotate_nuv_metadata(data):
    """
    annotate nuvolaris configmap with entries for minio connectivity S3_ENDPOINT, S3_PORT, S3_ACCESS_KEY, S3_SECRET_KEY
    this is becasue MINIO
    """ 
    try:
        seaweed_service =  _get_seaweedfs_service()
        if(seaweed_service):
            seaweed_host = f"{seaweed_service['metadata']['name']}.{seaweed_service['metadata']['namespace']}.svc.cluster.local"
            access_key = data["seaweedfs_nuv_user"]
            secret_key = data["seaweedfs_nuv_password"]
            openwhisk.annotate(f"s3_host={seaweed_host}")
            openwhisk.annotate(f"s3_access_key={access_key}")
            openwhisk.annotate(f"s3_secret_key={secret_key}")
            openwhisk.annotate("s3_provider=seaweedfs")

            ports = list(seaweed_service['spec']['ports'])
            for port in ports:
                if(port['name']=='s3-api'):
                    openwhisk.annotate(f"s3_port={port['port']}")                  
        return None
    except Exception as e:
        logging.error(f"failed to build minio_host for nuvolaris: {e}")
        return None      

def create_seaweedfs_nuv_storage(data):
    """
    Creates nuvolaris SEAWEEDFS custom resources
    """
    logging.info("*** configuring SEAWEEDFS storage for nuvolaris")
    seaweedsfsClient = SeaweedfsClient()
    
    res = seaweedsfsClient.make_bucket("nuvolaris-data",data["default_bucket_quota"])
    if res:
        openwhisk.annotate("s3_bucket_data=nuvolaris-data")

    res = seaweedsfsClient.add_anonymous_access()
    res = seaweedsfsClient.make_bucket("nuvolaris-web",data["default_bucket_quota"])
    res = seaweedsfsClient.make_public_bucket("nuvolaris-web")
    
    if res:
        openwhisk.annotate("s3_bucket_static=nuvolaris-web")
        content_path = util.find_content_path("index.html")

        if(content_path):
            logging.info(f"uploading example content to nuvolaris-web from {content_path}")
            res = seaweedsfsClient.upload_folder_content(content_path,"nuvolaris-web")
        else:
            logging.warn("could not find example static content to upload")

    res = seaweedsfsClient.add_user(data["seaweedfs_nuv_user"],data["seaweedfs_nuv_user"],data["seaweedfs_nuv_password"],"nuvolaris-web,nuvolaris-data")   
    
    if(res):        
        _annotate_nuv_metadata(data)
        logging.info("*** configured SEAWEEDFS storage for nuvolaris")

def create_ow_storage(state, ucfg: UserConfig, user_metadata: UserMetadata, owner=None):    
    seaweedfsClient = SeaweedfsClient()    
    namespace = ucfg.get("namespace")
    secretkey = ucfg.get("object-storage.password")

    # assign default quota set for the user is not available
    if not ucfg.exists('object-storage.quota'):
        ucfg.put('object-storage.quota',cfg.get('seaweedfs.default-bucket-quota') or "1024")
        logging.info(f"assigned bucket quota of {ucfg.get('object-storage.quota')}MB for namespace {namespace}")

    logging.info(f"*** configuring storage for namespace {namespace}")
    buckets = []

    if(ucfg.get('object-storage.data.enabled')):
        bucket_name = ucfg.get('object-storage.data.bucket')
        logging.info(f"*** adding private bucket {bucket_name} for {namespace}")
        res = seaweedfsClient.make_bucket(bucket_name, ucfg.get('object-storage.quota'))                       
        state['storage_data']=res        

        if(res):
            user_metadata.add_metadata("S3_BUCKET_DATA",bucket_name)
            ucfg.put("S3_BUCKET_DATA",bucket_name)
            buckets.append(bucket_name)

    if(ucfg.get('object-storage.route.enabled')):
        bucket_name = ucfg.get("object-storage.route.bucket")
        logging.info(f"*** adding public bucket {bucket_name} for {namespace}")
        res = seaweedfsClient.make_bucket(bucket_name, ucfg.get('object-storage.quota'))  
        res = seaweedfsClient.make_public_bucket(bucket_name)

        if(res):
            user_metadata.add_metadata("S3_BUCKET_STATIC",bucket_name)
            ucfg.put("S3_BUCKET_STATIC",bucket_name)
            buckets.append(bucket_name)
        
        content_path = util.find_content_path("index.html")

        if(content_path):
            logging.info(f"uploading example content to {bucket_name} from {content_path}")
            res = seaweedfsClient.upload_folder_content(content_path,bucket_name)
        else:
            logging.warn("could not find example static content to upload")

        state['storage_route']=res            


    res = seaweedfsClient.add_user(namespace,namespace, secretkey, ",".join(buckets))
    state['storage_user']=res

    if(res):
        _add_seaweedfs_user_metadata(ucfg, user_metadata)

    return state

def delete_ow_storage(ucfg):
    seaweedfsClient = SeaweedfsClient()    
    namespace = ucfg.get("namespace")

    if(ucfg.get('object-storage.data.enabled')):
        bucket_name = ucfg.get('object-storage.data.bucket')
        logging.info(f"*** removing private bucket {bucket_name} for {namespace}")
        seaweedfsClient.force_bucket_remove(bucket_name)

    if(ucfg.get('object-storage.route.enabled')):
        bucket_name = ucfg.get("object-storage.route.bucket")
        logging.info(f"*** removing public bucket {bucket_name} for {namespace}")
        seaweedfsClient.force_bucket_remove(bucket_name)

    return seaweedfsClient.delete_user(namespace)

def delete_by_owner():
    spec = kus.build("seaweedfs")
    res = kube.delete(spec)
    logging.info(f"delete seaweedfs: {res}")
    return res

def delete_by_spec():
    spec = cfg.get("state.seaweedfs.spec")
    res = False
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete seaweedfs: {res}")
    return res

def delete(owner=None):
    data = util.get_seaweedfs_config_data()
    seaweedfs_ingress.delete_seaweedfs_ingresses(data, owner)

    if owner:        
        return delete_by_owner()
    else:
        return delete_by_spec()

def patch(status, action, owner=None):
    """
    Called by the operator patcher to create/delete seaweedfs component
    """
    try:
        logging.info(f"*** handling request to {action} seaweedfs")  
        if  action == 'create':
            msg = create(owner)
            operator_util.patch_operator_status(status,'seaweedfs','on') 
        else:
            msg = delete(owner)
            operator_util.patch_operator_status(status,'seaweedfs','off')

        logging.info(msg)        
        logging.info(f"*** hanlded request to {action} seaweedfs") 
    except Exception as e:
        logging.error('*** failed to update minio: %s' % e)
        operator_util.patch_operator_status(status,'seaweedfs','error')

def patch_ingresses(status, action, owner=None):
    """
    Called by the operator patcher to create/delete seaweedfs component
    """
    try:
        logging.info(f"*** handling request to {action} seaweedfs ingresses")
        data = util.get_minio_config_data()
        if action == 'update':
            msg = seaweedfs_ingress.create_seaweedfs_ingresses(data, owner)
            operator_util.patch_operator_status(status,'seaweedfs-ingresses','on')

        logging.info(msg)        
        logging.info(f"*** hanlded request to {action} seaweedfs ingresses") 
    except Exception as e:
        logging.error('*** failed to update minio seaweedfs: %s' % e)    
        operator_util.patch_operator_status(status,'seaweedfs-ingresses','error')        
