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
# this module wraps utilities functions
import logging
import math
import random
import time
import uuid
from base64 import b64decode, b64encode
from typing import List, Union
from urllib.parse import urlparse

import urllib3
from urllib3.exceptions import NewConnectionError, MaxRetryError, ProtocolError

import nuvolaris.apihost_util as apihost_util
import nuvolaris.config as cfg
import nuvolaris.kube as kube
import nuvolaris.template as template

# Implements truncated exponential backoff from
# https://cloud.google.com/storage/docs/retry-strategy#exponential-backoff
def nuv_retry(deadline_seconds=120, max_backoff=5):
    def decorator(function):
        from functools import wraps

        @wraps(function)
        def wrapper(*args, **kwargs):
            deadline = time.time() + deadline_seconds
            retry_number = 0

            while True:
                try:
                    result = function(*args, **kwargs)
                    return result
                except Exception as e:
                    current_t = time.time()
                    backoff_delay = min(
                            math.pow(2, retry_number) + random.random(), max_backoff
                    )

                    if current_t + backoff_delay < deadline:
                        time.sleep(backoff_delay)
                        retry_number += 1
                        logging.warn(f"#{retry_number} nuv_retry detected a failure...")
                        continue  # retry again
                    else:
                        raise
        return wrapper

    return decorator


def get_default_storage_class():
    """
    Get the storage class attempting to get the default storage class defined on the configured kubernetes environment
    """
    storage_class = kube.kubectl("get", "storageclass", jsonpath=r"{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io\/is-default-class=='true')].metadata.name}")
    storage_class += kube.kubectl("get", "storageclass", jsonpath=r"{.items[?(@.metadata.annotations.storageclass\.beta\.kubernetes\.io\/is-default-class=='true')].metadata.name}")
    if(storage_class):
        return storage_class[0]

    return ""

def get_default_storage_provisioner():
    """
    Get the storage provisioner
    """
    provisioner = kube.kubectl("get", "storageclass", jsonpath=r"{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io\/is-default-class=='true')].provisioner}")
    provisioner += kube.kubectl("get", "storageclass", jsonpath=r"{.items[?(@.metadata.annotations.storageclass\.beta\.kubernetes\.io\/is-default-class=='true')].metadata.name}")
    if(provisioner):
        return provisioner[0]

    return ""

def get_ingress_namespace(runtime):
    """
    Attempt to determine the namespace where the ingress-nginx-controller service has been deployed 
    checking the nuvolaris.ingresslb 
    - When set to 'auto' it will attempt to calculate it according to the kubernetes runtime
    - When set to <> 'auto' it will return the configured value. The configured value should be in the form <namespace>/<ingress-nginx-controller-service-name>
    >>> import nuvolaris.config as cfg
    >>> cfg.put('nuvolaris.ingresslb','auto')
    True
    >>> get_ingress_namespace('microk8s')
    'ingress'
    >>> get_ingress_namespace('kind')
    'ingress-nginx'
    >>> cfg.put('nuvolaris.ingresslb','ingress-nginx-azure/ingress-nginx-controller')
    True
    >>> get_ingress_namespace('kind')
    'ingress-nginx-azure'
    """
    ingresslb_value = cfg.get('nuvolaris.ingresslb') or 'auto'

    if 'auto' != ingresslb_value:
        ingress_namespace = ingresslb_value.split('/')[0]
        logging.debug(f"skipping ingress namespace auto detection and returning {ingress_namespace}")
        return ingress_namespace

    if runtime == "microk8s":
        return "ingress"
    else:
        return  "ingress-nginx"

def get_ingress_service_name(runtime):
    """
    Attempt to determine the namespace where the ingress-nginx-controller service has been deployed 
    checking the nuvolaris.ingresslb 
    - When set to 'auto' it will attempt to calculate it according to the kubernetes runtime
    - When set to <> 'auto' it will return the configured value. The configured value should be in the form <namespace>/<ingress-nginx-controller-service-name>
    >>> import nuvolaris.config as cfg
    >>> cfg.put('nuvolaris.ingresslb','auto')
    True
    >>> get_ingress_service_name('microk8s')
    'service/ingress-nginx-controller'
    >>> get_ingress_service_name('kind')
    'service/ingress-nginx-controller'
    >>> cfg.put('nuvolaris.ingresslb','ingress-nginx-azure/ingress-nginx-controller-custom')
    True
    >>> get_ingress_service_name('kind')
    'service/ingress-nginx-controller-custom'
    """
    ingresslb_value = cfg.get('nuvolaris.ingresslb') or 'auto'

    if 'auto' != ingresslb_value:
        ingress_srv_name = f"service/{ingresslb_value.split('/')[1]}"
        logging.debug(f"skipping ingress service name auto detection and returning {ingress_srv_name}")
        return ingress_srv_name

    return "service/ingress-nginx-controller"

def get_ingress_class(runtime):
    """
    Attempt to determine the proper ingress class
    - When set to 'auto' it will attempt to calculate it according to the kubernetes runtime
    - When set to <> 'auto' it will return the configured value.
    """
    ingress_class = cfg.get('nuvolaris.ingressclass') or 'auto'

    if 'auto' != ingress_class:
        logging.warn(f"skipping ingress class auto detection and returning {ingress_class}")
        return ingress_class

    # ingress class default to nginx
    ingress_class = "nginx"

    # On microk8s ingress class must be public
    if runtime == "microk8s":
        ingress_class = "public"

    # On k3s ingress class must be traefik
    if runtime == "k3s":
        ingress_class = "traefik"

    return ingress_class

# determine the ingress-nginx flavour
def get_ingress_yaml(runtime):
    if runtime == "eks":
        return "eks-nginx-ingress.yaml"
    elif runtime == "kind":
        return  "kind-nginx-ingress.yaml"
    else:
        return  "cloud-nginx-ingress.yaml"

# wait for a pod name
@nuv_retry()
def get_pod_name(jsonpath,namespace="nuvolaris"):
    pod_name = kube.kubectl("get", "pods", namespace=namespace, jsonpath=jsonpath)
    if(pod_name):
        return pod_name[0]

    raise Exception(f"could not find any pod matching jsonpath={jsonpath}")

# helper method waiting for a pod ready using the given jsonpath to retrieve the pod name
def wait_for_pod_ready(pod_name_jsonpath, timeout="600s", namespace="nuvolaris"):
    try:
        pod_name = get_pod_name(pod_name_jsonpath, namespace)
        logging.info(f"checking pod {pod_name}")
        while not kube.wait(f"pod/{pod_name}", "condition=ready", timeout, namespace):
            logging.info(f"waiting for {pod_name} to be ready...")
            time.sleep(1)
    except Exception as e:
        logging.error(e)


def status_matches(code: int, allowed: List[Union[int, str]]) -> bool:
    """Check if the status code matches any allowed pattern."""
    for pattern in allowed:
        if isinstance(pattern, int) and code == pattern:
            return True
        if isinstance(pattern, str) and len(pattern) == 3 and pattern.endswith("XX"):
            if int(pattern[0]) == code // 100:
                return True
    return False

def wait_for_http(url: str, timeout: int = 60, up_statuses: List[Union[int, str]] = [200]):
    """Wait until an HTTP endpoint becomes available with an accepted status code.

    Args:
        url (str): Full URL to check (e.g. http://milvus:9091/healthz)
        timeout (int): Total seconds to wait before giving up.
        up_statuses (List[Union[int, str]]): Status codes or patterns considered as 'UP'.

    Raises:
        TimeoutError: If the endpoint doesn't respond with a valid status within the timeout.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"

    if scheme == "https":
        conn = urllib3.connectionpool.HTTPSConnectionPool(host, port=port,
                                                          timeout=urllib3.util.Timeout(connect=5.0, read=5.0),
                                                          retries=False)
    else:
        conn = urllib3.connectionpool.HTTPConnectionPool(host, port=port,
                                                         timeout=urllib3.util.Timeout(connect=5.0, read=5.0),
                                                         retries=False)

    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            response = conn.request("GET", path)
            if status_matches(response.status, up_statuses):
                logging.info(f"Service is up: {url} (status {response.status})")
                return
            else:
                logging.warning(f"Service responded with {response.status}, not in {up_statuses}. Waiting...")
        except (NewConnectionError, MaxRetryError):
            logging.warning(f"Cannot connect to {url}, retrying...")
        except ProtocolError as e:
            if "Connection reset by peer" in str(e):
                logging.warning("Connection reset by peer. Sleeping 2 seconds...")
                time.sleep(2)
                continue
            else:
                logging.error(f"Protocol error: {e}")
        time.sleep(1)

# return mongodb configuration parameter with default valued if not configured
def get_mongodb_config_data():
    data = {
        'mongo_admin_user': cfg.get('mongodb.admin.user') or "whisk_user",
        'mongo_admin_password': cfg.get('mongodb.admin.password') or "0therPa55",
        'mongo_nuvolaris_user': cfg.get('mongodb.nuvolaris.user') or "nuvolaris",
        'mongo_nuvolaris_password': cfg.get('mongodb.nuvolaris.password') or "s0meP@ass3",
        'size': cfg.get('mongodb.volume-size') or 10,
        'pvcName': 'mongodb-data',
        'storageClass':cfg.get("nuvolaris.storageclass"),
        'pvcAccessMode':'ReadWriteOnce'
        }
    return data

def parse_image(img):
    """
    Parse a string representing a pod image in the form <image>:<tag> and return
    a dictionary containing {"image":<img>, "tag":<tag>}
    >>> img_data = parse_image("ghcr.io/nuvolaris/openwhisk-controller:0.3.0-morpheus.22122609")
    >>> "ghcr.io/nuvolaris/openwhisk-controller" == img_data["image"]
    True
    >>> "0.3.0-morpheus.22122609" == img_data["tag"]
    True
    """
    tmp_img_items = img.split(":")

    if len(tmp_img_items) != 2:
        raise Exception(f"wrong image name format {img}. Image and tag must be separated by a :")

    data = {
        "image": tmp_img_items[0],
        "tag": tmp_img_items[1],
    }

    return data

def get_controller_image_data(data):
    controller_image = cfg.get("controller.image")

    if ":" in controller_image:
        img_data = parse_image(controller_image)
        data['controller_image'] = img_data["image"]
        data['controller_tag'] = img_data["tag"]
    else:
        data['controller_image'] = cfg.get("controller.image") or "ghcr.io/nuvolaris/openwhisk-controller"
        data['controller_tag'] = cfg.get("controller.tag") or "3.1.0-mastrogpt.2402101445"

# return configuration parameters for the standalone controller
def get_standalone_config_data():
    data = {
        "name":"controller",
        "couchdb_host": cfg.get("couchdb.host") or "couchdb",
        "couchdb_port": cfg.get("couchdb.port") or "5984",
        "couchdb_admin_user": cfg.get("couchdb.admin.user"),
        "couchdb_admin_password": cfg.get("couchdb.admin.password"),
        "couchdb_controller_user": cfg.get("couchdb.controller.user"),
        "couchdb_controller_password": cfg.get("couchdb.controller.password"),
        "triggers_fires_perMinute": cfg.get("configs.limits.triggers.fires-perMinute") or 60,
        "actions_sequence_maxLength": cfg.get("configs.limits.actions.sequence-maxLength") or 50,
        "actions_invokes_perMinute": cfg.get("configs.limits.actions.invokes-perMinute") or 60,
        "actions_invokes_concurrent": cfg.get("configs.limits.actions.invokes-concurrent") or 30,
        "activation_payload_max": cfg.get('configs.limits.activations.max_allowed_payload') or "1048576",
        "time_limit_min": cfg.get("configs.limits.time.limit-min") or "100ms",
        "time_limit_std": cfg.get("configs.limits.time.limit-std") or "1min",
        "time_limit_max": cfg.get("configs.limits.time.limit-max") or "5min",
        "memory_limit_min": cfg.get("configs.limits.memory.limit-min") or "128m",
        "memory_limit_std": cfg.get("configs.limits.memory.limit-std") or "256m",
        "memory_limit_max": cfg.get("configs.limits.memory.limit-max") or "512m",
        "concurrency_limit_min": cfg.get("configs.limits.concurrency.limit-min") or 1,
        "concurrency_limit_std": cfg.get("configs.limits.concurrency.limit-std") or 1,
        "concurrency_limit_max": cfg.get("configs.limits.concurrency.limit-max") or 1,
        "controller_java_opts": cfg.get('configs.controller.javaOpts') or "-Xmx2048M",
        "invoker_containerpool_usermemory": cfg.get('configs.invoker.containerPool.userMemory') or "2048m",
        "container_cpu_req": cfg.get('configs.controller.resources.cpu-req') or "500m",
        "container_cpu_lim": cfg.get('configs.controller.resources.cpu-lim') or "1",
        "container_mem_req": cfg.get('configs.controller.resources.mem-req') or "1G",
        "container_mem_lim": cfg.get('configs.controller.resources.mem-lim') or "2G",
        "container_manage_resources": cfg.exists('configs.controller.resources.cpu-req'),
        "usePrivateRegistry":cfg.get('components.registry') or False,
    }

    get_controller_image_data(data)
    standalone_affinity_tolerations_data(data)
    return data

def validate_ow_auth(auth):
    """
        >>> import nuvolaris.testutil as tutil
        >>> import nuvolaris.util as util
        >>> auth = tutil.generate_ow_auth()
        >>> util.validate_ow_auth(auth)
        True
        >>> util.validate_ow_auth('21321:3213216')
        False
    """
    try:
        parts = auth.split(':')
        try:
            uid = str(uuid.UUID(parts[0], version = 4))
        except ValueError:
            logging.error('authorization id is not a valid UUID')
            return False

        key = parts[1]
        if len(key) < 64:
            logging.error('authorization key must be at least 64 characters long')
            return False

        return True
    except Exception as e:
        logging.error('failed to determine authorization id and key: %s' % e)
        return False

def check(f, what, res):
    if f:
        logging.info(f"OK: {what}")
        return res and True
    else:
        logging.warn(f"ERR: {what}")
        return False

# return redis configuration parameters with default values if not configured
def get_redis_config_data():
    # ensure prefix key contains : at the end to be compliant with REDIS script ACL creator
    prefix = cfg.get("redis.nuvolaris.prefix") or "nuvolaris:"

    if(not prefix.endswith(":")):
        prefix = f"{prefix}:"

    data = {
        "applypodsecurity":get_enable_pod_security(),
        "name": "redis",
        "container": "redis",
        "dir": "/bitnami/redis/data",
        "size": cfg.get("redis.volume-size", "REDIS_VOLUME_SIZE", 10),
        "storageClass": cfg.get("nuvolaris.storageclass"),
        "redis_password":cfg.get("redis.default.password") or "s0meP@ass3",
        "namespace":"nuvolaris",
        "password":cfg.get("redis.nuvolaris.password") or "s0meP@ass3",
        "prefix": prefix,
        "persistence": cfg.get("redis.persistence-enabled") or False,
        "maxmemory": cfg.get("redis.maxmemory") or "1000mb"
    }

    redis_affinity_tolerations_data(data)
    return data

def get_service(jsonpath,namespace="nuvolaris"):
    services= kube.kubectl("get", "svc", namespace=namespace, jsonpath=jsonpath)
    if(services):
        return services[0]

    raise Exception(f"could not find any svc matching jsonpath={jsonpath}")

# return minio configuration parameters with default values if not configured
def get_minio_config_data():
    data = {
        "applypodsecurity":get_enable_pod_security(),
        "name":"minio-deployment",
        "container":"minio",
        "minio_host": cfg.get('minio.host') or 'nuvolaris-minio',
        "minio_volume_size": cfg.get('minio.volume-size') or "5",
        "minio_root_user": cfg.get('minio.admin.user') or "minio",
        "minio_root_password": cfg.get('minio.admin.password') or "minio123",
        "storage_class": cfg.get("nuvolaris.storageclass"),
        "minio_nuv_user": cfg.get('minio.nuvolaris.user') or "nuvolaris",
        "minio_nuv_password": cfg.get('minio.nuvolaris.password') or "zuf+tfteSlswRu7BJ86wekitnifILbZam1KYY3TG",
        "minio_s3_ingress_enabled": cfg.get('minio.ingress.s3-enabled') or False,
        "minio_console_ingress_enabled": cfg.get('minio.ingress.console-enabled') or False,
        "minio_s3_ingress_hostname": cfg.get('minio.ingress.s3-hostname') or "auto",
        "minio_console_ingress_hostname": cfg.get('minio.ingress.console-hostname') or "auto"
    }
    minio_affinity_tolerations_data(data)
    return data

# return postgres configuration parameter with default valued if not configured
def get_postgres_config_data():
    data = {
        'postgres_root_password': cfg.get('postgres.admin.password') or "0therPa55",
        'postgres_root_replica_password': cfg.get('postgres.admin.password') or "0therPa55sd",
        'postgres_nuvolaris_user': "nuvolaris",
        'postgres_nuvolaris_password': cfg.get('postgres.nuvolaris.password') or "s0meP@ass3",
        'size': cfg.get('postgres.volume-size') or 10,
        'replicas': cfg.get('postgres.replicas') or 2,
        'storageClass': cfg.get('nuvolaris.storageclass'),
        'failover': cfg.get('postgres.failover') or False,
        'backup': cfg.get('postgres.backup.enabled') or False,
        'schedule': cfg.get('postgres.backup.schedule') or '30 * * * *'
        }
    postgres_affinity_tolerations_data(data)
    return data

def get_postgres_backup_data():
    data = {
        'size': cfg.get('postgres.volume-size') or 10,
        'storageClass': cfg.get('nuvolaris.storageclass'),
        'schedule': cfg.get('postgres.backup.schedule') or '30 * * * *',
        'name': 'nuvolaris-postgres-backup',
        'dir':'/var/lib/backup',
        'container':'nuvolaris-postgres-backup'
        }
    postgres_affinity_tolerations_data(data)
    return data

# wait for a service matching the given jsonpath name
@nuv_retry()
def wait_for_service(jsonpath,namespace="nuvolaris"):
    service_names = kube.kubectl("get", "svc", namespace=namespace, jsonpath=jsonpath)
    if(service_names):
        return service_names[0]

    raise Exception(f"could not find any pod matching jsonpath={jsonpath}")

def get_controller_http_timeout():
    return cfg.get("configs.limits.time.limit-max") or "5min"

def get_apihost_from_config_map(namespace="nuvolaris"):
    annotations= kube.kubectl("get", "cm/config", namespace=namespace, jsonpath='{.metadata.annotations.apihost}')
    if(annotations):
        return annotations[0]

    raise Exception("Could not find apihost annotation inside internal cm/config config Map")

def get_value_from_config_map(namespace="nuvolaris", path='{.metadata.annotations.apihost}'):
    annotations= kube.kubectl("get", "cm/config", namespace=namespace, jsonpath=path)
    if(annotations):
        return annotations[0]

    raise Exception(f"Could not find {path} annotation inside internal cm/config config Map")

def get_enable_pod_security():
    """
    Return true if there is the need to enable pod security context
    for some specific pod. This is a test based on some empiric assumption on runtime 
    basis and/or storage class.
    @TODO: find a better way to determine when this function should return true.
    """
    runtime = cfg.get('nuvolaris.kube')
    storage_class = cfg.get('nuvolaris.storageclass')
    return runtime in ["eks","gke","aks","generic"] or (runtime in ["k3s"] and "rook" in storage_class)

def get_runtimes_json_from_config_map(namespace="nuvolaris", path=r'{.data.runtimes\.json}'):
    """ Return the configured runtimes.json from the config map cm/openwhisk-runtimes
    """
    runtimes= kube.kubectl("get", "cm/openwhisk-runtimes", namespace=namespace, jsonpath=path)
    if(runtimes):
        return runtimes[0]

    raise Exception("Could not find runtimes.json inside cm/openwhisk-runtimes config Map")

# return static nginx configuration parameters with default values if not configured
def get_storage_static_config_data():
    data = {
        "name":"nuvolaris-static",
        "container":"nuvolaris-static",
        "size":1,
        "storageClass": cfg.get('nuvolaris.storageclass'),
        "dir":"/var/cache/nginx",
        "applypodsecurity": get_enable_pod_security()
    }

    if cfg.get('components.minio'):
        minio_host=cfg.get('minio.host') or "nuvolaris-minio"
        minio_port=cfg.get('minio.port') or "9000"
        data['storage_url']=f"http://{minio_host}.nuvolaris.svc.cluster.local:{minio_port}"

    if cfg.get('components.cosi'):
        data['storage_url']=apihost_util.add_suffix_to_url(get_object_storage_rgw_url(),"cluster.local")

    storage_static_affinity_tolerations_data(data)
    return data

# populate common affinity data
def common_affinity_tolerations_data(data):
    data["affinity"] = cfg.get('nuvolaris.affinity') or False
    data["tolerations"] = cfg.get('nuvolaris.tolerations') or False
    data["affinity_invoker_node_label"] = "invoker"
    data["affinity_core_node_label"] = "core"
    data["toleration_role"] = "core"

# populate specific affinity data for couchdb
def couch_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "couchdb"

# populate specific affinity data for redis
def redis_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "redis"

# populate specific affinity data for minio
def minio_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "minio"

# populate specific affinity data for minio
def storage_static_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "nuvolaris-static"

# populate specific affinity data for postgres
def postgres_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "nuvolaris-postgres"

# populate specific affinity data for ferretdb
def ferretb_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "ferretdb"

# populate specific affinity data for ferretdb
def standalone_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "controller"

# populate specific affinity data for postgres controller manager
def postgres_manager_affinity_tolerations_data():
    data = {
            "pod_anti_affinity_name":"kubegres-controller-manager",
            "name":"kubegres-controller-manager"
    }
    common_affinity_tolerations_data(data)
    return data

def postgres_backup_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "nuvolaris-postgres-backup"

# populate specific affinity data for registry
def registry_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "registry"    

# wait for a pod name using a label selector and eventually an optional jsonpath
@nuv_retry()
def get_pod_name_by_selector(selector, jsonpath, namespace="nuvolaris"):
    """
    get pods matching the given selector filtering them using the given jsonpath.
    param: selector (eg app="nuvolaris-postgres")
    param: jsonpath (eg "{.items[?(@.metadata.labels.replicationRole == 'primary')].metadata.name}")
    return: 1st mathing pod name
    """
    pod_names = kube.kubectl("get", "pods","-l", selector, namespace=namespace, jsonpath=jsonpath)
    if(pod_names):
        return pod_names[0]

    raise Exception(f"could not find any pod matching jsonpath={jsonpath}")

# wait for a svc name using a label selector and eventually an optional jsonpath
@nuv_retry()
def get_service_by_selector(selector,jsonpath,namespace="nuvolaris"):
    """
    get services matching the given selector filtering them using the given jsonpath
    param: selector (eg app="nuvolaris-postgres")
    param: jsonpath (eg "{.items[?(@.metadata.labels.replicationRole == 'primary')].metadata.name}")
    return: 1st mathing service name
    """
    services= kube.kubectl("get", "svc","-l",selector, namespace=namespace, jsonpath=jsonpath)
    if(services):
        return services[0]

    raise Exception(f"could not find any svc matching jsonpath={jsonpath}")

def get_kvrocks_config_data():
    # ensure prefix key contains : at the end to be compliant with REDIS script ACL creator
    prefix = cfg.get("redis.nuvolaris.prefix") or "nuvolaris:"

    if(not prefix.endswith(":")):
        prefix = f"{prefix}:"

    data = {
        "applypodsecurity":get_enable_pod_security(),
        "name": "kvrocks",
        "container": "redis",
        "dir": "/var/lib/kvrocks/data",
        "size": cfg.get("redis.volume-size", "REDIS_VOLUME_SIZE", 10),
        "storageClass": cfg.get("nuvolaris.storageclass"),
        "redis_password":cfg.get("redis.default.password") or "s0meP@ass3",
        "namespace":"nuvolaris",
        "password":cfg.get("redis.nuvolaris.password") or "s0meP@ass3",
        "prefix": prefix,
        "persistence": True,
        "maxmemory": cfg.get("redis.maxmemory") or "1000mb",
        "pvcName":"kvrocks-pvc",
        "container_cpu_req": cfg.get('redis.resources.cpu-req') or "128",
        "container_cpu_lim": cfg.get('redis.resources.cpu-lim') or "256",
        "container_mem_req": cfg.get('redis.resources.mem-req') or "512m",
        "container_mem_lim": cfg.get('redis.resources.mem-lim') or "1Gi",
    }

    redis_affinity_tolerations_data(data)
    return data

def get_object_storage_class():
    """
    Get the object storage class attempting to get the default storage class defined on the configured kubernetes environment
    """
    storage_class = kube.kubectl("get", "storageclass", jsonpath="{.items[?(@.parameters.objectStoreName=='nuvolaris-s3-store')].metadata.name}")
    if(storage_class):
        return storage_class[0]

    return ""

def get_object_storage_rgw_url():
    """
    Get the object store RGW service URL, to be used to configure the static nginx services when running on top of a CEPH OBJECT STORE
    """
    rgw_urls = kube.kubectl("get", "cephobjectstores",namespace="rook-ceph",jsonpath="{.items[?(@.metadata.name=='nuvolaris-s3-store')].status.info.endpoint}")
    if(rgw_urls):
        return rgw_urls[0]

    return ""

def get_object_storage_rgw_srv_name():
    """
    Get the object store RGW service URL, to be used to configure the static nginx services when running on top of a CEPH OBJECT STORE
    """
    rgw_urls = kube.kubectl("get", "svc",namespace="rook-ceph",jsonpath="{.items[?(@.metadata.labels.rgw=='nuvolaris-s3-store')].metadata.name}")
    if(rgw_urls):
        return rgw_urls[0]

    return ""

def get_object_storage_rgw_srv_http_port():
    """
    Get the object store RGW service URL, to be used to configure the static nginx services when running on top of a CEPH OBJECT STORE
    """
    rgw_ports = kube.kubectl("get", "svc",namespace="rook-ceph",jsonpath="{.items[?(@.metadata.labels.rgw=='nuvolaris-s3-store')].spec.ports[?(@.name=='http')].port}")
    if(rgw_ports):
        return rgw_ports[0]

    return ""

def get_cosi_config_data():
    data = {
        "bucket_storageclass": cfg.get('cosi.bucket_storageclass') or "rook-ceph-bucket",
        "s3_ingress_enabled": cfg.get('cosi.ingress.s3-enabled') or False,
        "s3_ingress_hostname": cfg.get('cosi.ingress.s3-hostname') or "auto",
        "rgwservice_name": cfg.get('cosi.rgwservice_name'),
        "rgwservice_port": cfg.get('cosi.rgwservice_port'),
        "cluster_namespace": cfg.get('cosi.namespace') or "rook-ceph",
        "object_store_name": cfg.get('cosi.object_store_name') or "nuvolaris-s3-store",
        "max_bucket_limit": cfg.get('cosi.max_bucket_limit') or 5,
    }
    return data

def b64_encode(value:str):
    """
    Encode a value into as base 64
    param: value to be encoded
    return: the input value in case of error, otherwise the b64 representation of the the input value
    """
    try:
        return b64encode(value.encode(encoding="utf-8")).decode()
    except:
        return value

def b64_decode(encoded_str:str):
    """
    Base 64 decode
    param: encoded_str a b64 encoded string
    return: the inpiut value in case of error, the decoded string otherwise.
    """
    try:
        return b64decode(encoded_str).decode()
    except:
        return encoded_str

# populate specific affinity data for redis
def etcd_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "nuvolaris-etcd"

def get_etcd_initial_clusters(name: str, replicas = 1):
    """ Calculate the proper setup for ETCD initial clusters
    >>> print(get_etcd_initial_clusters("nuvolaris-etcd"))
    nuvolaris-etcd-0=http://nuvolaris-etcd-0.nuvolaris-etcd-headless.nuvolaris.svc.cluster.local:2380
    >>> print(get_etcd_initial_clusters("nuvolaris-etcd",2))
    nuvolaris-etcd-0=http://nuvolaris-etcd-0.nuvolaris-etcd-headless.nuvolaris.svc.cluster.local:2380,nuvolaris-etcd-1=http://nuvolaris-etcd-1.nuvolaris-etcd-headless.nuvolaris.svc.cluster.local:2380
    """
    etc_initial_clusters = ""
    for idx in range(replicas):
        if len(etc_initial_clusters) > 0:
            etc_initial_clusters+=","

        etc_initial_clusters += f"{name}-{idx}=http://{name}-{idx}.{name}-headless.nuvolaris.svc.cluster.local:2380"

    return etc_initial_clusters.strip()

# populate etcd configuration parameters
def get_etcd_config_data():

    data = {
        "applypodsecurity":get_enable_pod_security(),
        "name": "nuvolaris-etcd",
        "container": "nuvolaris-etcd",
        "size": cfg.get("etcd.volume-size", "REDIS_VOLUME_SIZE", 5),
        "storageClass": cfg.get("nuvolaris.storageclass"),
        "root_password":cfg.get("etcd.root.password") or "s0meP@ass3wd",
        "etcd_replicas":get_etcd_replica(),
        "etcd_auto_compaction_retention": cfg.get("etcd.auto_compaction_retention") or "1",
        "etcd_quota_backend_bytes": cfg.get("etcd.quota-backend-bytes") or "2147483648",
        "namespace":"nuvolaris",
        "container_cpu_req": cfg.get('etcd.resources.cpu-req') or "250m",
        "container_cpu_lim": cfg.get('etcd.resources.cpu-lim') or "375m",
        "container_mem_req": cfg.get('etcd.resources.mem-req') or "256Mi",
        "container_mem_lim": cfg.get('etcd.resources.mem-lim') or "384Mi"
    }

    data["etc_initial_cluster"] = get_etcd_initial_clusters(data["container"],data['etcd_replicas'])

    etcd_affinity_tolerations_data(data)
    return data

def get_etcd_replica():
    return cfg.get("etcd.replicas") or 1

# populate specific affinity data for milvus controller manager
def milvus_manager_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "milvus-operator"
    return data

def milvus_standalone_affinity_tolerations_data(data):
    common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "nuvolaris-milvus"
    data["name"] = "nuvolaris-milvus-standalone"
    data["container-name"] = "nuvolaris-milvus"
    return data

# return milvus configuration parameter with default valued if not configured
def get_milvus_config_data():
    data = {
        'milvus_etcd_username': "etcdmilvus",
        'milvus_etcd_password': cfg.get('milvus.password.etcd') or "0therPa55",
        'milvus_etcd_root_password':cfg.get("etcd.root.password") or "s0meP@ass3wd",
        'milvus_etcd_prefix': 'milvus',
        'milvus_s3_username': 'miniomilvus',
        'milvus_s3_password': cfg.get('milvus.password.s3') or "s0meP@ass3",
        'milvus_bucket_name': 'vectors',
        'milvus_bucket_prefix': 'milvus/nuvolaris-milvus',
        'size': cfg.get('milvus.volume-size.cluster') or 10,
        'zookeeper_size': cfg.get('milvus.volume-size.zookeeper') or 10,
        'bookie_journal_size': cfg.get('milvus.volume-size.journal') or 25,
        'bookie_ledgers_size': cfg.get('milvus.volume-size.ledgers') or 50,
        'replicas': cfg.get('milvus.replicas') or 1,
        'storageClass': cfg.get('nuvolaris.storageclass'),
        'etcd_replicas':get_etcd_replica(),
        'etcd_container': 'nuvolaris-etcd',
        'milvus_root_password': cfg.get('milvus.password.root') or "An0therPa55",
        'nuvolaris_password': cfg.get('milvus.nuvolaris.password') or "Nuv0therPa55",
        'milvus_max_role_num': cfg.get('milvus.proxy.max-role-num') or 10,
        'milvus_max_user_num': cfg.get('milvus.proxy.max-user-num') or 100,
        'milvus_max_database_num': cfg.get('milvus.root-coord.max-database-num') or 64,
        'slim': cfg.get('nuvolaris.slim') or False,
        }

    data["etcd_range"]=range(data["etcd_replicas"])
    milvus_standalone_affinity_tolerations_data(data)
    return data


# return registry configuration parameters with default values if not configured
def get_registry_config_data():

    data = {
        "applypodsecurity":get_enable_pod_security(),
        "name": "registry",
        "container": "registry",
        "dir":"/var/lib/registry",
        "pvcName":"registry-pvc",
        "size": cfg.get("registry.volume-size", "REGISTRY_VOLUME_SIZE", 20),
        "storageClass": cfg.get("nuvolaris.storageclass"),
        "repoHostname": cfg.get('registry.hostname') or "auto",
        "ingressEnabled": cfg.get('registry.ingress.enabled') or False,
        "registryUsername": cfg.get('registry.auth.username') or "openserverless",
        "registryPassword": cfg.get('registry.auth.password') or "4pwdregistry",
        "mode": cfg.get('registry.mode') or "internal"
    }

    # always add the internal SvcHostname
    data['repoSvcHostname'] = "nuvolaris-registry-svc:5000"
    registry_affinity_tolerations_data(data)
    return data


