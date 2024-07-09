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
import kopf, logging, os
import nuvolaris.util as util
import nuvolaris.openwhisk as openwhisk
import nuvolaris.ceph_cos_ingress as ceph_ingress
import nuvolaris.operator_util as operator_util
import nuvolaris.apihost_util as apihost_util

from nuvolaris.user_config import UserConfig
from nuvolaris.user_metadata import UserMetadata
from nuvolaris.ceph_cos_obc_data import CephObjectBucketClaimData
from nuvolaris.ceph_cos_user_data import CephCosUserData
from nuvolaris.s3_client import S3Client
from nuvolaris.s3_bucket_policy import S3BucketPolicy, S3BucketStatement

def _annotate_nuv_metadata(data):
    """
    annotate nuvolaris configmap with entries for ceph re-using MINIO_ENDPOINT, MINIO_PORT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY    
    for backward compatibility with MINIO based setup.
    """ 
    try:
        logging.info("annotating COS storage for nuvolaris")
        hostname, port = apihost_util.split_hostname_port(data['endpoint'])    

        if hostname:
            openwhisk.annotate(f"minio_host={hostname}")
            openwhisk.annotate(f"s3_host={hostname}")

        if port:    
            openwhisk.annotate(f"minio_port={port}")
            openwhisk.annotate(f"s3_port={port}")

        openwhisk.annotate(f"minio_access_key={data['access_key']}")
        openwhisk.annotate(f"minio_secret_key={data['secret_key']}")
        openwhisk.annotate(f"s3_access_key={data['access_key']}")
        openwhisk.annotate(f"s3_secret_key={data['secret_key']}")
        openwhisk.annotate(f"s3_provider=rook")
    except Exception as e:
        logging.error(f"failed to annotate COS storage for nuvolaris: {e}")
        return None

def _add_cos_metadata(object_user, ucfg: UserConfig, user_metadata:UserMetadata):
    """
    adds entries for COS connectivity STORE_ENDPOINT, STORE_PORT, STORE_ACCESS_KEY, STORE_SECRET_KEY    
    """ 
    try:
        hostname, port = apihost_util.split_hostname_port(util.get_object_storage_rgw_url())        
        if(hostname):
            user_metadata.add_metadata("S3_PROVIDER","rook")
            user_metadata.add_metadata("MINIO_HOST",hostname)
            user_metadata.add_metadata("MINIO_ACCESS_KEY",object_user['access_key'])
            user_metadata.add_metadata("MINIO_SECRET_KEY",object_user['secret_key'])
            user_metadata.add_metadata("S3_HOST",hostname)
            user_metadata.add_metadata("S3_ACCESS_KEY",object_user['access_key'])
            user_metadata.add_metadata("S3_SECRET_KEY",object_user['secret_key'])

        if port:
            user_metadata.add_metadata("MINIO_PORT",port)
            user_metadata.add_metadata("S3_PORT",port)
        return None
    except Exception as e:
        logging.error("failed to add COSI metadara for %s: %s", ucfg.get('namespace'), e)
        return None
    
def find_content_path(filename):
    """extract the absolute path of the given filename

    Args:
        filename (string): filename to be found

    Returns:
        string: absolute path
    """
    absolute_path = os.path.dirname(__file__)
    relative_path = "../deploy/content"
    return os.path.join(absolute_path, relative_path, filename)

def create(owner=None):
    logging.info("*** configuring ceph object store support")

    data = util.get_cosi_config_data()
    res = ceph_ingress.create_cos_ingresses(data, owner)

    create_nuv_storage(data)
    logging.info("*** configured ceph object store")
    return res

def build_rw_bucket_policy(bucket_name, username):
    """
    Builds RW bucket Statement
    """  
    bkt_statement = S3BucketStatement()
    bkt_statement.with_allow()
    bkt_statement.with_aws_principal(f"arn:aws:iam:::user/{username}")
    bkt_statement.with_resource(f"arn:aws:s3:::{bucket_name}/*")
    bkt_statement.with_resource(f"arn:aws:s3:::{bucket_name}")
    return bkt_statement

def build_public_bucket_policy(bucket_name):
    """
    Builds R bucket Statement
    """         
    bkt_statement = S3BucketStatement()
    bkt_statement.with_allow()
    bkt_statement.with_all_principal()
    bkt_statement.with_s3_action("s3:GetObject")
    bkt_statement.with_resource(f"arn:aws:s3:::{bucket_name}/*")
    #bkt_statement.with_resource(f"arn:aws:s3:::{bucket_name}")
    return bkt_statement

def build_public_list_bucket_policy(bucket_name):
    """
    Builds ListBucket bucket Statement to avoid 403 error when bucket resource does not exists and get a 404.
    """     
    bkt_statement = S3BucketStatement()
    bkt_statement.with_allow()
    bkt_statement.with_all_principal()
    bkt_statement.with_s3_action("s3:ListBucket")
    #bkt_statement.with_resource(f"arn:aws:s3:::{bucket_name}/*")
    bkt_statement.with_resource(f"arn:aws:s3:::{bucket_name}")
    return bkt_statement

def build_data_bucket_policy(bucket_name, username):
    """
    Builds bucket policy for the data bucket
    """
    bkt_policy = S3BucketPolicy()
    bkt_policy.with_statement(build_rw_bucket_policy(bucket_name, username))
    return bkt_policy

def build_web_bucket_policy(bucket_name, username):
    """
    Builds bucket policy for the web bucket
    """    
    bkt_policy = S3BucketPolicy()
    bkt_policy.with_statement(build_rw_bucket_policy(bucket_name, username))
    bkt_policy.with_statement(build_public_bucket_policy(bucket_name))
    bkt_policy.with_statement(build_public_list_bucket_policy(bucket_name))
    return bkt_policy    

def create_nuv_storage(data):
    """
    Creates nuvolaris Ceph Object Store custom resources
    """
    logging.info("*** configuring COS storage for nuvolaris")
    try:
        s3_host, s3_port = apihost_util.split_hostname_port(util.get_object_storage_rgw_url())        
        ceph_object_user = CephCosUserData("nuvolaris")
        object_user = ceph_object_user.deploy()

        if object_user:
            logging.debug("created ceph object store user %s with endpoint %s", object_user['username'],object_user['endpoint'])
            _annotate_nuv_metadata(object_user)

        logging.info("*** adding nuvolaris S3 data bucket")
        obc_data = CephObjectBucketClaimData("nuvolaris-data")
        obc_data_result = obc_data.deploy()
        
        if 'bucket_name' in obc_data_result:
            # Set full access on the generated bucket name for the object_user            
            data_policy : S3BucketPolicy = build_data_bucket_policy(obc_data_result['bucket_name'], object_user['username'])
            s3_client = S3Client(s3_host, s3_port,obc_data_result['access_key'],obc_data_result['secret_key'])
            s3_client.set_bucket_policy(obc_data_result['bucket_name'], data_policy)
            logging.info("granted full access to user %s on bucket %s", object_user['username'],obc_data_result['bucket_name'])
            openwhisk.annotate(f"minio_bucket_data={obc_data_result['bucket_name']}")                        
            openwhisk.annotate(f"s3_bucket_data={obc_data_result['bucket_name']}")                        


        logging.info("*** adding nuvolaris S3 static public bucket")
        obc_web = CephObjectBucketClaimData("nuvolaris-web")
        obc_web_result = obc_web.deploy()
        
        if 'bucket_name' in obc_web_result:
            # Set full access on the generated bucket name for the object_user
            web_policy = build_web_bucket_policy(obc_web_result['bucket_name'], object_user['username'] )
            s3_client = S3Client(s3_host, s3_port,obc_web_result['access_key'],obc_web_result['secret_key'])
            s3_client.set_bucket_policy(obc_web_result['bucket_name'], web_policy)
            logging.info("granted full access to user %s on bucket %s", object_user['username'],obc_data_result['bucket_name'])
            openwhisk.annotate(f"minio_bucket_static={obc_web_result['bucket_name']}")
            openwhisk.annotate(f"s3_bucket_static={obc_web_result['bucket_name']}")

            content_path = find_content_path("index.html")

            if(content_path):
                logging.info("uploading example content to %s from %s", obc_web_result['bucket_name'],content_path)
                s3_client.upload_file(content_path,obc_web_result['bucket_name'],"index.html")
                logging.info("uploading example content to nuvolaris-web from %s", content_path)
            else:
                logging.warning("could not find example static content to upload")

        logging.info(f"*** configured COS storage for nuvolaris")
    except Exception as e:
        logging.error("failed to configure COS storage for nuvolarus: %s",e)
        return None

def create_ow_storage(state, ucfg: UserConfig, user_metadata: UserMetadata, owner=None):
    namespace = ucfg.get("namespace")
    s3_host, s3_port = apihost_util.split_hostname_port(util.get_object_storage_rgw_url())
    ceph_object_user = CephCosUserData(namespace)
    
    if ucfg.exists('object-storage.quota') and ucfg.get('object-storage.quota') not in ['auto']:
        ceph_object_user.with_quota_enabled(True)
        ceph_object_user.with_quota_limit(ucfg.get('object-storage.quota'))

    object_user = ceph_object_user.deploy()

    if object_user:
            logging.debug(f"created ceph object store user {object_user['username']} with endpoint {object_user['endpoint']}")
            _add_cos_metadata(object_user, ucfg, user_metadata)
            state['storage_user']='on'

    logging.info(f"*** configuring COSI storage for namespace {namespace}")        

    if(ucfg.get('object-storage.data.enabled')) and 'username' in object_user:
        bucket_name = ucfg.get('object-storage.data.bucket')
        logging.info(f"*** adding private bucket {bucket_name} for {namespace}")

        obc_data = CephObjectBucketClaimData(bucket_name)
        obc_data_result = obc_data.deploy()

        if 'bucket_name' in obc_data_result:
            # Set full access on the generated bucket name for the object_user            
            data_policy : S3BucketPolicy = build_data_bucket_policy(obc_data_result['bucket_name'], object_user['username'])
            s3_client = S3Client(s3_host, s3_port,obc_data_result['access_key'],obc_data_result['secret_key'])
            s3_client.set_bucket_policy(obc_data_result['bucket_name'], data_policy)
            user_metadata.add_metadata("MINIO_DATA_BUCKET",obc_data_result['bucket_name'])
            user_metadata.add_metadata("S3_DATA_BUCKET",obc_data_result['bucket_name'])
            logging.info("granted full access to user %s on bucket %s", object_user['username'],obc_data_result['bucket_name'])
    
    if(ucfg.get('object-storage.route.enabled')) and 'username' in object_user:
        bucket_name = ucfg.get("object-storage.route.bucket")
        logging.info("*** adding public bucket %s for %s", bucket_name, namespace)

        obc_web = CephObjectBucketClaimData(bucket_name)
        obc_web_result = obc_web.deploy()
        
        if 'bucket_name' in obc_web_result:
            # Set full access on the generated bucket name for the object_user
            web_policy = build_web_bucket_policy(obc_web_result['bucket_name'], object_user['username'] )
            s3_client = S3Client(s3_host, s3_port,obc_web_result['access_key'],obc_web_result['secret_key'])
            s3_client.set_bucket_policy(obc_web_result['bucket_name'], web_policy)
            user_metadata.add_metadata("MINIO_BUCKET_STATIC",obc_web_result['bucket_name'])
            user_metadata.add_metadata("S3_BUCKET_STATIC",obc_web_result['bucket_name'])
            ucfg.put("S3_BUCKET_STATIC",obc_web_result['bucket_name'])
            logging.info("granted full access to user %s on bucket %s",object_user['username'],obc_data_result['bucket_name'])

            content_path = find_content_path("index.html")

            if(content_path):
                logging.info("uploading example content to %s from %s",obc_web_result['bucket_name'],content_path)
                s3_client.upload_file(content_path,obc_web_result['bucket_name'],"index.html")
                logging.info("uploaded example content to %s from %s",obc_web_result['bucket_name'],content_path)
            else:
                logging.error("could not find example static content to upload")       

        state['storage_resource']='on'
    return state

def delete_ow_storage(ucfg: UserConfig):
    """Delete COSI based bucket resources for the gien wsku user

    Args:
        ucfg (UserConfig): User Configuration Data

    Returns:
        bool: True if the deletion is completed
    """
    try:
        namespace = ucfg.get("namespace")
        ceph_object_user = CephCosUserData(namespace)
        ceph_object_user.undeploy()

        if(ucfg.get('object-storage.data.enabled')):
            bucket_name = ucfg.get('object-storage.data.bucket')
            logging.info("*** removing private bucket %s for %s", bucket_name, namespace)
            obc = CephObjectBucketClaimData(bucket_name)
            obc.undeploy()        

        if(ucfg.get('object-storage.route.enabled')):
            bucket_name = ucfg.get("object-storage.route.bucket")
            logging.info("*** removing public bucket %s for %s", bucket_name, namespace)
            obc = CephObjectBucketClaimData(bucket_name)
            obc.undeploy()
        return True
    except Exception as e:
        logging.error("error deleting user for namespace %s, %s", ucfg.get("namespace"), e)
        return False

def delete(owner=None):
    try:
        data = util.get_cosi_config_data()
        ceph_ingress.delete_cos_ingresses(data, owner)
    except Exception as e:    
        logging.error('*** failed to delete cosi: %s' % e)

def patch(status, action, owner=None):
    """
    Called by the operator patcher to create/delete minio component
    """
    try:
        logging.info(f"*** handling request to {action} cosi")  
        if  action == 'create':
            msg = create(owner)
            operator_util.patch_operator_status(status,'cosi','on') 
        else:
            delete(owner)
            operator_util.patch_operator_status(status,'cosi','off')

        logging.info(msg)        
        logging.info(f"*** hanlded request to {action} cosi") 
    except Exception as e:
        logging.error('*** failed to update cosi: %s' % e)
        operator_util.patch_operator_status(status,'cosi','error')

def patch_ingresses(status, action, owner=None):
    """
    Called by the operator patcher to create/delete minio component
    """
    try:
        logging.info(f"*** handling request to {action} cosi ingresses")
        data = util.get_cosi_config_data()
        if action == 'update':
            msg = ceph_ingress.create_cos_ingresses(data, owner)
            operator_util.patch_operator_status(status,'cosi-ingresses','on')

        logging.info(msg)        
        logging.info(f"*** handled request to {action} cosi ingresses") 
    except Exception as e:
        logging.error('*** failed to update cosi ingresses: %s' % e)    
        operator_util.patch_operator_status(status,'cosi-ingresses','error')
