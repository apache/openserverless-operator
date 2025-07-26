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
import kopf
import logging
import json, os, os.path
import nuvolaris.config as cfg
import nuvolaris.kube as kube
import nuvolaris.redis as redis
import nuvolaris.couchdb as couchdb
import nuvolaris.bucket as bucket
import nuvolaris.openwhisk as openwhisk
import nuvolaris.cronjob as cron
import nuvolaris.ferretdb as mongodb
import nuvolaris.issuer as issuer
import nuvolaris.endpoint as endpoint
import nuvolaris.minio_deploy as minio
import nuvolaris.zookeeper as zookeeper
import nuvolaris.kafka as kafka
import nuvolaris.invoker as invoker
import nuvolaris.patcher as patcher
import nuvolaris.storage_static as static
import nuvolaris.operator_util as operator_util
import nuvolaris.postgres_operator as postgres
import nuvolaris.runtimes_preloader as preloader
import nuvolaris.monitoring as monitoring
import nuvolaris.quota_checker_job as quota
import nuvolaris.etcd as etcd
import nuvolaris.milvus_standalone as milvus
import nuvolaris.registry_deploy as registry

@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
  settings.watching.server_timeout = 210

# tested by an integration test
@kopf.on.login()
def login(**kwargs):
    token = '/var/run/secrets/kubernetes.io/serviceaccount/token'
    if os.path.isfile(token):
        logging.debug("found serviceaccount token: login via pykube in kubernetes")
        return kopf.login_via_pykube(**kwargs)
    logging.debug("login via client")
    return kopf.login_via_client(**kwargs)

# tested by an integration test
@kopf.on.create('nuvolaris.org', 'v1', 'whisks')
def whisk_create(spec, name, **kwargs):
    logging.info(f"*** whisk_create {name}")

    operator_util.config_from_spec(spec)
    owner = kube.get(f"wsk/{name}")

    state = {
        "openwhisk": "?",  # Openwhisk Controller or Standalone
        "invoker": "?",  # Invoker
        "couchdb": "?",  # Couchdb
        "kafka": "?",  # Kafka
        "redis": "?",  # Redis
        "mongodb": "?",  # MongoDB
        "cron": "?",   # Cron based actions executor
        "tls": "?",   # Cron based actions executor
        "endpoint": "?", # Http/s controller endpoint # Http/s controller endpoint
        "issuer": "?", # ClusterIssuer configuration
        "ingress": "?", # Ingress configuration
        "minio": "?", # Minio configuration
        "static": "?", # Minio static endpoint provider
        "zookeeper": "?", #Zookeeper configuration
        "quota":"?", #Quota configuration
        "etcd":"?" #Etcdd configuration
    }

    runtime = cfg.get('nuvolaris.kube')
    logging.info(f"kubernetes engine in use={runtime}")

    if cfg.get('components.openwhisk'):
        try:
            msg = preloader.create(owner)
            state['preloader']= "on"
            logging.info(msg)
        except:
            logging.exception("could not create runtime preloader batach")
            state['preloader']= "error"
    else:
        state['preloader']= "off"   

    if cfg.get('components.couchdb'):
        try:
            msg = couchdb.create(owner)
            state['couchdb']= "on"
            logging.info(msg)
        except:
            logging.exception("cannot create couchdb")
            state['couchdb']= "error"
    else:
        state['couchdb'] = "off"

    if cfg.get('components.redis'):
        try:
            msg = redis.create(owner)
            state['redis'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create redis")
            state['redis']= "error"
    else:
        state['redis'] = "off"

    if cfg.get('components.registry'):
        try:
            msg = registry.create(owner)
            state['registry'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create registry")
            state['registry']= "error"
    else:
        state['registry'] = "off"         

    if cfg.get('components.tls') and not runtime in ["kind","openshift"]:
        try:
            msg = issuer.create(owner)
            state['issuer'] = "on"
            state['tls'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot configure issuer")
            state['issuer']= "error"
            state['tls'] = "error"
    else:
        state['issuer'] = "off"
        state['tls'] = "off"
        if runtime == "kind" and cfg.get('components.tls'):
            logging.info("*** cluster issuer will not be deployed with kind runtime")

    if cfg.get('components.cron'):
        try:
            msg = cron.create(owner)
            state['cron'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create cron")
            state['cron']= "error"
    else:
        state['cron'] = "off" 

    if cfg.get('components.minio'):
        msg = minio.create(owner)
        logging.info(msg)
        state['minio'] = "on"
    else:
        state['minio'] = "off"

    if cfg.get('components.static'):
        msg = static.create(owner)
        logging.info(msg)
        state['static'] = "on"
    else:
        state['static'] = "off"

    if cfg.get('components.postgres') or cfg.get('components.mongodb'):
        msg = postgres.create(owner)
        logging.info(msg)
        state['postgres'] = "on"
    else:
        state['postgres'] = "off"

    if cfg.get('components.mongodb'):
        msg = mongodb.create(owner)
        logging.info(msg)
        state['mongodb'] = "on"
    else:
        state['mongodb'] = "off"
    
    if(cfg.get('components.zookeeper')):
        try:
            msg = zookeeper.create(owner)
            state['zookeeper'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create zookeeper")
            state['zookeeper'] = "error"

    if(cfg.get('components.kafka')):
        try:
            msg = kafka.create(owner)
            state['kafka'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create kafka")
            state['kafka'] = "error"            

    if (cfg.get('components.invoker')):
        try:
            msg = invoker.create(owner)
            state['invoker'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create openwhisk invoker")
            state['invoker']= "error"

    if cfg.get('components.openwhisk'):
        try:
            msg = openwhisk.create(owner)
            state['openwhisk'] = "on"
            logging.info(msg)

            msg = endpoint.create(owner)
            state['endpoint'] = "on"
            logging.info(msg)

        except:
            logging.exception("cannot create openwhisk")
            state['openwhisk']= "error"
            state['endpoint'] = "error"
    else:
        state['openwhisk'] = "off"
        state['endpoint'] = "off"

    if (cfg.get('components.monitoring')):
        try:
            msg = monitoring.create(owner)
            state['monitoring'] = "on"
            logging.info(msg)

        except:
            logging.exception("cannot create monitoring")
            state['monitoring']= "error"
    else:
        state['monitoring'] = "off"

    if cfg.get('components.quota'):
        try:
            msg = quota.create(owner)
            state['quota'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create quotaa checker")
            state['quota']= "error"
    else:
        state['quota'] = "off"

    if cfg.get('components.etcd'):
        try:
            msg = etcd.create(owner)
            state['etcd'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create etcd")
            state['etcd']= "error"
    else:
        state['etcd'] = "off" 

    if cfg.get('components.milvus'):
        try:
            msg = milvus.create(owner)
            state['milvus'] = "on"
            logging.info(msg)
        except:
            logging.exception("cannot create milvus")
            state['milvus']= "error"
    else:
        state['milvus'] = "off"  

    whisk_post_create(name,state)
    state['controller']= "Ready"
    return state

def whisk_post_create(name, state):    
    sysres = operator_util.whisk_post_create(name)
    if(sysres):
        state['whisk-system']="on"
    else:                   
        state['whisk-system']="error"

# tested by an integration test
@kopf.on.delete('nuvolaris.org', 'v1', 'whisks')
def whisk_delete(spec, **kwargs):
    runtime = cfg.get('nuvolaris.kube')
    logging.info("whisk_delete")
   
    if cfg.get("components.openwhisk"):
        msg = preloader.delete()
        msg = openwhisk.delete()
        logging.info(msg)
        msg = endpoint.delete()
        logging.info(msg)

    if cfg.get("components.invoker"):       
        msg = invoker.delete()
        logging.info(msg)            

    if cfg.get('components.tls') and not runtime == "kind":
        msg = issuer.delete()
        logging.info(msg)

    if cfg.get("components.redis"):
        msg = redis.delete()
        logging.info(msg)

    if cfg.get('components.couchdb'):
        msg = couchdb.delete()
        logging.info(msg)
        
    if cfg.get("components.mongodb"):
        msg = mongodb.delete()
        logging.info(msg)         

    if cfg.get("components.cron"):
        msg = cron.delete()
        logging.info(msg)

    if cfg.get('components.static'):
        msg = static.delete()
        logging.info(msg) 

    if cfg.get("components.minio"):
        msg = minio.delete()
        logging.info(msg)

    if cfg.get('components.postgres'):
        msg = postgres.delete()
        logging.info(msg)
                 
    if cfg.get("components.kafka"):
        msg = kafka.delete()
        logging.info(msg)  

    if cfg.get("components.zookeeper"):
        msg = zookeeper.delete()
        logging.info(msg)
    
    if cfg.get("components.monitoring"):
        msg = monitoring.delete()
        logging.info(msg)

    if cfg.get("components.quota"):
        msg = quota.delete()
        logging.info(msg) 

    if cfg.get("components.etcd"):
        msg = etcd.delete()
        logging.info(msg) 

    if cfg.get("components.milvus"):
        msg = milvus.delete()
        logging.info(msg) 

    if cfg.get("components.registry"):
        msg = registry.delete()
        logging.info(msg)                                                           
    
                         
# tested by integration test
#@kopf.on.field("service", field='status.loadBalancer')
def service_update(old, new, name, **kwargs):
    if not name == "apihost":
        return

    logging.info(f"service_update: {json.dumps(new)}")
    ingress = []
    if "ingress" in new and len(new['ingress']) >0:
        ingress = new['ingress']
    
    apihost = openwhisk.apihost(ingress)
    openwhisk.annotate(f"apihost={apihost}")
    cfg.put("config.apihost", apihost)

@kopf.on.update('nuvolaris.org', 'v1', 'whisks')
def whisk_update(spec, status, namespace, diff, name, **kwargs):
    logging.info(f"*** detected an update of wsk/{name} under namespace {namespace}")
    
    operator_util.config_from_spec(spec,handler_type="on_update")
    owner = kube.get(f"wsk/{name}")

    patcher.patch(diff, status, owner, name)

@kopf.on.resume('nuvolaris.org', 'v1', 'whisks')
def whisk_resume(spec, status, name, **kwargs):   
    operator_util.config_from_spec(spec, handler_type="on_resume")
    operator_util.whisk_post_resume(name)

def runtimes_filter(name, type, **kwargs):
    return name == 'openwhisk-runtimes' and type == 'MODIFIED'  

@kopf.on.event("configmap", when=runtimes_filter)
def runtimes_cm_event_watcher(event, **kwargs):    
    logging.info("*** detected a change in cm/openwhisk-runtimes config map, restarting openwhisk related PODs")
    owner = kube.get(f"wsk/controller") 
    patcher.patch_preloader(owner)

    if cfg.get('components.openwhisk'):
        patcher.restart_whisk(owner)