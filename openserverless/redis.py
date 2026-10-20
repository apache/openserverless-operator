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
import openserverless.openwhisk as openwhisk
import urllib.parse
import hashlib
import contextlib
import redis as redislib
from openserverless.redis_acl import tenant_rules
from openserverless.datastore_connection import service_endpoint
import os, os.path
import logging, json
import kopf
import openserverless.operator_util as operator_util

from openserverless.user_config import UserConfig
from openserverless.user_metadata import UserMetadata


def _add_redis_user_metadata(ucfg: UserConfig, user_metadata:UserMetadata):
    """
    adds an entry for the redis connectivity, i.e
    something like "redis://{namespace}:{auth}@redis"}
    """ 

    try:
        redis_service =  util.get_service("{.items[?(@.spec.selector.name == 'redis')]}")
        if(redis_service):
            redis_service_name = redis_service['metadata']['name']
            redis_service_port = redis_service['spec']['ports'][0]['port']            
            username = urllib.parse.quote(ucfg.get('namespace'), safe='')
            password = urllib.parse.quote(ucfg.get('redis.password'), safe='')
            auth = f"{username}:{password}"
            redis_url = f"redis://{auth}@{redis_service_name}:{redis_service_port}"
            redis_alt_url = f"redis://{password}@{redis_service_name}:{redis_service_port}"
            user_metadata.add_metadata("REDIS_URL",redis_url)
            user_metadata.add_metadata("REDIS_ALT_URL",redis_alt_url)
            user_metadata.add_metadata("REDIS_SERVICE",redis_service_name)
            user_metadata.add_metadata("REDIS_PORT",redis_service_port)
            user_metadata.add_metadata("REDIS_PROVIDER","valkey")
            user_metadata.add_metadata("REDIS_PASSWORD",ucfg.get('redis.password'))           
        return None
    except Exception as e:
        logging.error(f"failed to build redis_url for {ucfg.get('namespace')}: {e}")
        return None 

def create(owner=None):
    logging.info("create redis")
    data = util.get_redis_config_data()
    
    tplp = ["security-set-attach.yaml","redis-set.yaml"]

    if data['persistence']:
       tplp.append("set-attach.yaml")

    if(data['affinity'] or data['tolerations']):
       tplp.append("affinity-tolerance-sts-core-attach.yaml")

    kust = kus.patchTemplates("redis",tplp , data)    
    spec = kus.kustom_list("redis", kust, templates=["redis-conf.yaml"], data=data)

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.redis.spec", spec)
    res = kube.apply(spec)

    wait_for_redis_ready()
    create_openserverless_db_user(data)

    logging.info(f"create redis: {res}")
    return res

def wait_for_redis_ready():
    # dynamically detect redis pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.name == 'redis')].metadata.name}")

def restore_openserverless_db_user():
    data = util.get_redis_config_data()
    create_openserverless_db_user(data)

def create_openserverless_db_user(data):
    logging.info(f"authorizing redis for namespace openserverless")
    try:        
        data['mode']="create"
        data['redis_system_account']=True
        path_to_script = render_redis_script(data['namespace'],"redis_manage_user_tpl.txt",data)
        pod_name = util.get_pod_name("{.items[?(@.metadata.labels.name == 'redis')].metadata.name}")

        if(pod_name):
            res = exec_redis_command(pod_name,path_to_script)

            if(res):
                redis_service =  util.get_service("{.items[?(@.spec.selector.name == 'redis')]}")
                if(redis_service):
                    redis_service_name = redis_service['metadata']['name']
                    redis_service_port = redis_service['spec']['ports'][0]['port']
                    username = urllib.parse.quote(data['namespace'])
                    password = urllib.parse.quote(data['password'])
                    auth = f"{username}:{password}"
                    redis_url = f"redis://{auth}@{redis_service_name}:{redis_service_port}"
                    redis_alt_url = f"redis://{password}@{redis_service_name}:{redis_service_port}"
                    openwhisk.annotate(f"redis_url={redis_url}")
                    openwhisk.annotate(f"redis_prefix={data['prefix']}")
                    openwhisk.annotate(f"redis_alt_url={redis_alt_url}")
                    openwhisk.annotate(f"redis_service={redis_service_name}")
                    openwhisk.annotate(f"redis_port={redis_service_port}")
                    openwhisk.annotate(f"redis_password={data['password']}")
                    openwhisk.annotate(f"redis_provider=valkey")                    
                    logging.info("*** saved annotation for redis openserverless user")
            return res

        return None
    except Exception as e:
        logging.error(f"failed to add redis namespace {data['namespace']}: {e}")
        return None   

def delete_by_owner():
    spec = kus.build("redis")
    res = kube.delete(spec)
    logging.info(f"delete redis: {res}")
    return res

def delete_by_spec():
    spec = cfg.get("state.redis.spec")
    res = False
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete redis: {res}")
    return res

def delete(owner=None):
    if owner:        
        return delete_by_owner()
    else:
        return delete_by_spec()    

def render_redis_script(namespace,template,data):
    """
    uses the given template to render a redis-cli script to be executed.
    """
    if not util.validate_namespace(namespace):
        raise ValueError(f"Invalid namespace {namespace}")       
    
    out = f"/tmp/__{namespace}_{template}"
    file = ntp.spool_template(template, out, data)
    return os.path.abspath(file)

def exec_redis_command(pod_name,path_to_script):
    if not os.path.exists(path_to_script):
        raise ValueError(f"invalid path script in exec_redis_command")
    
    
    logging.info(f"passing script {path_to_script} to pod {pod_name}")
    res = kube.kubectl("cp",path_to_script,f"{pod_name}:{path_to_script}")
    res = kube.kubectl("exec","-it",pod_name,"--","/bin/bash","-c",f"cat {path_to_script} | redis-cli")
    os.remove(path_to_script)
    return res

def admin_client(password=None):
    stored = util.get_redis_config_data()['redis_password']
    if password is not None and password != stored:
        raise RuntimeError('Redis administrator credentials do not match')

    # doctest imports this file with openserverless/ on sys.path, where the
    # module name redis shadows the third-party driver. Resolve the class only
    # when an actual client is requested, preserving import-only tooling.
    class _AdminClient(redislib.Redis):
        def __init__(self, secret):
            self._service_context = contextlib.ExitStack()
            try:
                host, port = self._service_context.enter_context(service_endpoint('redis', 6379))
                super().__init__(host=host, port=port, password=secret, decode_responses=True,
                                 socket_timeout=10, socket_connect_timeout=5)
            except BaseException:
                self._service_context.close()
                raise

        def close(self):
            try:
                if hasattr(self, 'connection_pool'):
                    super().close()
            finally:
                self._service_context.close()

    return _AdminClient(stored)


def _tenant_identity(namespace, prefix=None):
    if (not util.validate_namespace(namespace)
            or namespace in ('default', 'openserverless')):
        raise ValueError('Invalid Redis tenant name')
    if prefix is not None:
        if not isinstance(prefix, str) or not prefix:
            raise ValueError('Invalid Redis tenant prefix')
        prefix = prefix if prefix.endswith(':') else prefix + ':'
        tenant_rules(prefix)
    return prefix


def _save_acl_if_configured(client):
    # Preserve the 0.9.0 storage contract: persist when an ACL file is configured.
    # With no ACL file, startup reconciliation recreates identities as before.
    if client.config_get('aclfile').get('aclfile'):
        client.acl_save()


def provision_user(namespace, password, prefix, readonly=False):
    prefix = _tenant_identity(namespace, prefix)
    if not isinstance(password, str) or not password:
        raise ValueError('Redis tenant password is required')
    hashed = hashlib.sha256(password.encode()).hexdigest()
    with admin_client() as client, client.lock('__ops_acl_lock__', timeout=120, blocking_timeout=15):
        previous = client.acl_getuser(namespace)
        # 0.9.0 reconciliation adds the configured password without revoking
        # existing valid credentials. Change only authorization in this backport.
        hashes = list(dict.fromkeys((previous or {}).get('passwords', []) + [hashed]))
        client.execute_command('ACL', 'SETUSER', namespace, 'reset', 'on',
                               *['#' + value for value in hashes], *tenant_rules(prefix, readonly))
        try:
            _save_acl_if_configured(client)
        except redislib.RedisError:
            client.acl_deluser(namespace)
            raise RuntimeError('Could not persist Redis tenant ACL') from None
    return True


def set_user_readonly(namespace, prefix, readonly):
    prefix = _tenant_identity(namespace, prefix)
    with admin_client() as client, client.lock('__ops_acl_lock__', timeout=120, blocking_timeout=15):
        if client.acl_getuser(namespace) is None:
            raise RuntimeError('Redis tenant does not exist')
        # Keep credentials; replace every command, key, channel and selector grant.
        client.execute_command('ACL', 'SETUSER', namespace, *tenant_rules(prefix, readonly))
        _save_acl_if_configured(client)
    return True


def create_db_user(ucfg: UserConfig, user_metadata: UserMetadata, read_only_mode = False):
    logging.info(f"authorizing new redis namespace {ucfg.get('namespace')}")    
    try:
        wait_for_redis_ready()
        prefix = _tenant_identity(ucfg.get('namespace'), ucfg.get('redis.prefix') or ucfg.get('namespace'))
        provision_user(ucfg.get('namespace'), ucfg.get('redis.password'), prefix, read_only_mode)
        user_metadata.add_metadata('REDIS_PREFIX', prefix)
        _add_redis_user_metadata(ucfg, user_metadata)
        return True

    except Exception as e:
        logging.error(f"failed to add redis namespace {ucfg.get('namespace')}: {e}")
        return None

def delete_db_user(namespace):
    _tenant_identity(namespace)
    try:
        with admin_client() as client, client.lock('__ops_acl_lock__', timeout=120, blocking_timeout=15):
            client.acl_deluser(namespace)
            _save_acl_if_configured(client)
        # Preserve the existing contract: deleting credentials retains the data.
        return True
    except Exception:
        logging.error('Failed to remove Redis tenant credentials')
        return None


def patch(status, action, owner=None):
    """
    Called the the operator patcher to create/delete redis
    """
    try:
        logging.info(f"*** handling request to {action} redis")  
        if  action == 'create':
            msg = create(owner)
            operator_util.patch_operator_status(status,'redis','on') 
        else:
            msg = delete(owner)
            operator_util.patch_operator_status(status,'redis','off') 

        logging.info(msg)        
        logging.info(f"*** hanlded request to {action} redis") 
    except Exception as e:
        logging.error('*** failed to update redis: %s' % e)
        operator_util.patch_operator_status(status,'redis','error')               

