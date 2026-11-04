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
import kopf, logging, time, os, json
import openserverless.kube as kube
import openserverless.kustomize as kus
import openserverless.config as cfg
import openserverless.util as util
import openserverless.openwhisk as openwhisk
import openserverless.seaweedfs_ingress as seaweedfs_ingress
import openserverless.operator_util as operator_util
import openserverless.datastore_security as datastore_security

from openserverless.datastore_connection import service_endpoint
from openserverless.user_config import UserConfig
from openserverless.user_metadata import UserMetadata
from openserverless.seaweedfs_util import SeaweedfsClient

def _get_seaweedfs_service():
    return util.get_service("{.items[?(@.spec.selector.app == 'seaweedfs')]}")

def _render_seaweedfs_spec(data):
    tplp = ["pvc-attach.yaml"]
    if data['affinity'] or data['tolerations']:
        tplp.append("affinity-tolerance-sts-core-attach.yaml")
    kust = kus.patchTemplates("seaweedfs", tplp, data)
    return kus.kustom_list("seaweedfs", kust, templates=[], data=data)

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

def _bootstrap_private_filer(data, timeout=30):
    """Wait for the private filer, recreating a tunnel lost during startup."""
    deadline = time.monotonic() + timeout
    last_error = None

    while time.monotonic() < deadline:
        ready = False
        try:
            with service_endpoint(data['name'], 9090) as (host, port):
                filer_url = f"http://{host}:{port}"
                try:
                    # A port-forward can exit after its first connection if the
                    # target socket is not listening yet. Keep each probe short
                    # so the next attempt can establish a fresh tunnel.
                    util.wait_for_http(filer_url, up_statuses=[200, 401], timeout=3)
                except TimeoutError as error:
                    last_error = error
                else:
                    ready = True
                    create_seaweedfs_nuv_storage(data, filer_url)
                    return
        except RuntimeError as error:
            if ready:
                raise
            last_error = error

        if time.monotonic() < deadline:
            time.sleep(1)

    raise TimeoutError("SeaweedFS filer did not become ready before timeout") from last_error

def create(owner=None):
    logging.info("*** configuring seaweedfs standalone")

    data = util.get_seaweedfs_config_data()

    spec = _render_seaweedfs_spec(data)
    policy = datastore_security.policy('seaweedfs')
    spec['items'].append(policy)

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.seaweedfs.spec", spec)

    # Establish the deny-by-default boundary before creating any listener.
    datastore_security.apply(policy)
    res = kube.apply(spec)

    # dynamically detect seaweedfs pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.app == 'seaweedfs')].metadata.name}")
    seaweedfs_ingress.create_seaweedfs_ingresses(data, owner)

    # The filer API is private. In-cluster this resolves to the Service;
    # integration runs use an authenticated, loopback-only port-forward.
    logging.info("*** waiting for seaweedfs filer api to be available")
    _bootstrap_private_filer(data)

    logging.info("*** configured seaweedfs standalone")
    return res

def reconcile(owner=None):
    """Secure an existing SeaweedFS deployment without recreating tenant data."""
    if not cfg.get('components.seaweedfs'):
        return None
    if not owner or not owner.get('metadata', {}).get('uid'):
        raise RuntimeError('Whisk owner is required to reconcile SeaweedFS isolation')

    data = util.get_seaweedfs_config_data()
    rendered = _render_seaweedfs_spec(data)
    services = [item for item in rendered['items']
                if item['kind'] == 'Service' and item['metadata']['name'] == 'seaweedfs']
    if len(services) != 1:
        raise RuntimeError('Could not render the SeaweedFS service')

    policy = datastore_security.policy('seaweedfs')
    resources = [policy, services[0]]
    kopf.append_owner_reference(resources, owner)
    datastore_security.apply(policy)
    result = kube.apply(services[0])
    # Existing deployments and restored filer data can still carry global Read.
    # Normalize IAM before publishing ingress, without bootstrapping buckets.
    with service_endpoint(data['name'], 9090) as (host, port):
        reconcile_anonymous_web_access(SeaweedfsClient(f"http://{host}:{port}"))
    seaweedfs_ingress.create_seaweedfs_ingresses(data, owner)
    return result

def _annotate_nuv_metadata(data):
    """
    annotate openserverless configmap with entries for S3 connectivity S3_ENDPOINT, S3_PORT, S3_ACCESS_KEY, S3_SECRET_KEY
    this is because SEAWEEDFS is the S3 provider
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
        logging.error(f"failed to build seaweedfs host for openserverless: {e}")
        return None      

def _configured_storage_buckets():
    """Read public and private bucket names from tenant configuration."""
    users = json.loads(kube.kubectl("get", "whisksusers", "-o", "json"))
    web_buckets = {"openserverless-web"}
    private_buckets = {"openserverless-data"}
    for user in users.get("items", []):
        storage = user.get("spec", {}).get("object-storage", {})
        if storage.get("data", {}).get("enabled"):
            private_buckets.add(storage["data"]["bucket"])
        route = storage.get("route", {})
        if route.get("enabled") and not user.get("metadata", {}).get("deletionTimestamp"):
            web_buckets.add(route["bucket"])
    return web_buckets, private_buckets

def reconcile_anonymous_web_access(client):
    """Replace all legacy anonymous grants with configured public buckets."""
    web_buckets, private_buckets = _configured_storage_buckets()
    # Delete the identity before adding grants: legacy configurations may
    # contain both an unscoped grant and stale bucket-scoped grants.
    if not client.delete_user("anonymous"):
        raise RuntimeError("Could not revoke existing anonymous S3 grants")
    safe_web_buckets = web_buckets - private_buckets
    if not client.add_anonymous_access(safe_web_buckets):
        raise RuntimeError("Could not grant public access to web buckets")
    if web_buckets & private_buckets:
        raise ValueError("Public and private S3 bucket names overlap")
    # Native shell commands may return success even when an operation failed.
    # Read back the persisted policy before accepting reconciliation.
    client.verify_anonymous_access(safe_web_buckets)

def create_seaweedfs_nuv_storage(data, filer_url=None):
    """
    Creates openserverless SEAWEEDFS custom resources
    """
    logging.info("*** configuring SEAWEEDFS storage for openserverless")
    seaweedsfsClient = SeaweedfsClient(filer_url)

    res = seaweedsfsClient.make_bucket("openserverless-data",data["default_bucket_quota"])
    if res:
        openwhisk.annotate("s3_bucket_data=openserverless-data")

    res = seaweedsfsClient.make_bucket("openserverless-web",data["default_bucket_quota"])
    res = seaweedsfsClient.make_public_bucket("openserverless-web")
    reconcile_anonymous_web_access(seaweedsfsClient)
    
    if res:
        openwhisk.annotate("s3_bucket_static=openserverless-web")
        content_path = util.find_content_path("index.html")

        if(content_path):
            logging.info(f"uploading example content to openserverless-web from {content_path}")
            res = seaweedsfsClient.upload_folder_content(content_path,"openserverless-web")
        else:
            logging.warn("could not find example static content to upload")

    res = seaweedsfsClient.add_user(data["seaweedfs_nuv_user"],data["seaweedfs_nuv_user"],data["seaweedfs_nuv_password"],"openserverless-web,openserverless-data")   
    
    if(res):        
        _annotate_nuv_metadata(data)
        logging.info("*** configured SEAWEEDFS storage for openserverless")

def create_ow_storage(state, ucfg: UserConfig, user_metadata: UserMetadata, owner=None):    
    seaweedfsClient = SeaweedfsClient()    
    namespace = ucfg.get("namespace")
    secretkey = ucfg.get("object-storage.password")

    if ucfg.get('object-storage.route.enabled') or ucfg.get('object-storage.data.enabled'):
        web_buckets, private_buckets = _configured_storage_buckets()
        if ucfg.get('object-storage.route.enabled'):
            web_buckets.add(ucfg.get('object-storage.route.bucket'))
        if ucfg.get('object-storage.data.enabled'):
            private_buckets.add(ucfg.get('object-storage.data.bucket'))
        if web_buckets & private_buckets:
            raise ValueError("Public and private S3 bucket names overlap")

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
        res = res and seaweedfsClient.add_anonymous_access([bucket_name])

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
    data_bucket = ucfg.get('object-storage.data.bucket') if ucfg.get('object-storage.data.enabled') else None
    route_bucket = ucfg.get('object-storage.route.bucket') if ucfg.get('object-storage.route.enabled') else None

    # Revoke the public grant before deleting any bucket. A legacy
    # configuration may use the same name for data and route storage.
    if route_bucket:
        logging.info(f"*** removing public bucket {route_bucket} for {namespace}")
        if not seaweedfsClient.remove_anonymous_access(route_bucket):
            raise RuntimeError(f"Could not revoke anonymous S3 access to bucket {route_bucket}; deletion stopped")

    if data_bucket:
        logging.info(f"*** removing private bucket {data_bucket} for {namespace}")
        seaweedfsClient.force_bucket_remove(data_bucket)

    if route_bucket and route_bucket != data_bucket:
        seaweedfsClient.force_bucket_remove(route_bucket)

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
        logging.error('*** failed to update seaweedfs: %s' % e)
        operator_util.patch_operator_status(status,'seaweedfs','error')

def patch_ingresses(status, action, owner=None):
    """
    Called by the operator patcher to create/delete seaweedfs component
    """
    try:
        logging.info(f"*** handling request to {action} seaweedfs ingresses")
        data = util.get_seaweedfs_config_data()
        if action == 'update':
            msg = seaweedfs_ingress.create_seaweedfs_ingresses(data, owner)
            operator_util.patch_operator_status(status,'seaweedfs-ingresses','on')

        logging.info(msg)        
        logging.info(f"*** hanlded request to {action} seaweedfs ingresses") 
    except Exception as e:
        logging.error('*** failed to update seaweedfs ingresses: %s' % e)
        operator_util.patch_operator_status(status,'seaweedfs-ingresses','error')        
