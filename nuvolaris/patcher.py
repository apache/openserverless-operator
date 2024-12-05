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
import logging, time
import nuvolaris.openwhisk as openwhisk
import nuvolaris.ferretdb as mongodb
import nuvolaris.redis as redis
import nuvolaris.cronjob as cron
import nuvolaris.minio_deploy as minio
import nuvolaris.storage_static as static
import nuvolaris.config as cfg
import nuvolaris.kube as kube
import nuvolaris.util as util
import nuvolaris.kopf_util as kopf_util
import nuvolaris.postgres_operator as postgres
import nuvolaris.endpoint as endpoint
import nuvolaris.issuer as issuer
import nuvolaris.operator_util as operator_util
import nuvolaris.runtimes_preloader as preloader
import nuvolaris.invoker as invoker
import nuvolaris.quota_checker_job as quota
import nuvolaris.etcd as etcd
import nuvolaris.milvus_standalone as milvus

def patch_preloader(owner: None):
    try:
        logging.info("*** handling request to patch openwhisk runtime preloader")
        preloader.delete(owner)
        preloader.create(owner)
        logging.info("*** handled request to patch openwhisk runtime preloader")
    except Exception as e:
        logging.error("*** failed to patch openwhisk runtime preloader",e)
import nuvolaris.invoker as invoker

def redeploy_invoker(owner=None):
    try:
        logging.info('*** handling request to redeploy whisk invoker')
        msg = invoker.create(owner)
        logging.info(msg)
        rollout("sts/invoker")
        logging.info('*** handled request to redeploy whisk invoker')
    except Exception as e:
        logging.error('*** failed to redeploy whisk invoker: %s' % e) 

def rollout(kube_name):
    try:
        logging.info(f"*** handling request to rollout {kube_name}")
        kube.rollout(kube_name)
        logging.info(f"*** handled request to rollout {kube_name}")
    except Exception as e:
        logging.error('*** failed to rollout %s: %s' % kube_name,e)

def restart_sts(sts_name):
    try:
        logging.info(f"*** handling request to redeploy {sts_name} using scaledown/scaleup")
        replicas =  1
        current_rep = kube.kubectl("get",sts_name,jsonpath="{.spec.replicas}")
        if current_rep:
            replicas = current_rep[0]
        
        kube.scale_sts(sts_name,0)
        time.sleep(5)
        logging.info(f"scaling {sts_name} to {replicas}")
        kube.scale_sts(sts_name,replicas)
        logging.info(f"*** handling request to redeploy {sts_name} using scaledown/scaleup")
    except Exception as e:
        logging.error('*** failed to scale up/down %s: %s' % sts_name,e)

def redeploy_controller(owner=None):
    try:
        logging.info("*** handling request to redeploy whisk controller")      
        msg = openwhisk.create(owner)
        logging.info(msg)
        rollout("sts/controller")
        logging.info("*** handled request to redeploy whisk controller") 
    except Exception as e:
        logging.error('*** failed to redeploy whisk controller: %s' % e) 

def restart_whisk(owner=None):
    useInvoker = cfg.get('components.invoker') or False
    if useInvoker:
        rollout("sts/invoker")
    
    rollout("sts/controller")
    
def redeploy_whisk(owner=None):
    useInvoker = cfg.get('components.invoker') or False
    if useInvoker:
        redeploy_invoker(owner)
      
    redeploy_controller(owner)
    

def patch(diff, status, owner=None, name=None):
    """
    Implements the patching logic of the nuvolaris operator by analyzing the kopf
    provided diff object to identify which components needs to be added/removed.
    """
    logging.info(status)
    what_to_do = kopf_util.detect_component_changes(diff)

    if len(what_to_do) == 0:
        logging.warn("*** no relevant changes identified by the operator patcher. Skipping processing")
        return None
    
    for key in what_to_do.keys():
        logging.info(f"{key}={what_to_do[key]}")

    components_updated = False    

    # components 1st
    if "postgres" in what_to_do:
        postgres.patch(status,what_to_do['postgres'], owner)
        components_updated = True

    if "mongodb" in what_to_do:
        mongodb.patch(status,what_to_do['mongodb'], owner)
        components_updated = True

    if "redis" in what_to_do:
        redis.patch(status,what_to_do['redis'], owner)
        components_updated = True 

    if "cron" in what_to_do:
        cron.patch(status,what_to_do['cron'], owner)
        components_updated = True 

    if "minio" in what_to_do:
        minio.patch(status,what_to_do['minio'], owner)
        components_updated = True 

    if "static" in what_to_do:
        static.patch(status,what_to_do['static'], owner)
        components_updated = True

    if "quota" in what_to_do:
        quota.patch(status,what_to_do['quota'], owner)
        components_updated = True 

    if "etcd" in what_to_do:
        etcd.patch(status,what_to_do['etcd'], owner)
        components_updated = True 

    if "milvus" in what_to_do:
        milvus.patch(status,what_to_do['milvus'], owner)
        components_updated = True                              

    # handle update action on openwhisk
    if "openwhisk" in what_to_do and what_to_do['openwhisk'] == "update":        
        redeploy_whisk(owner)
        components_updated = True

    # handle update action on endpoint
    if "endpoint" in what_to_do and what_to_do['endpoint'] == "update":
        issuer.patch(status,what_to_do['endpoint'], owner)       
        endpoint.patch(status,what_to_do['endpoint'], owner)

    if "minio-ingresses" in what_to_do and what_to_do['minio-ingresses'] == "update":
        minio.patch_ingresses(status,what_to_do['minio-ingresses'], owner)

    if components_updated:
        operator_util.whisk_post_create(name)
    
        
    
