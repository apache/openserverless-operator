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
import flatdict, json, os
import logging

_config = {}

# Prefix of the kube node labels carrying configuration. Kept as a
# constant so the slice below tracks its length automatically.
LABEL_PREFIX = "openserverless.io/"

# define a configuration 
# the configuration is a map, followed by a list of labels 
# the map can be a serialized json and will be flattened to a map of values.
# you can have only a configuration active at a time
# if you want to set a new configuration you have to clean it
def configure(spec: dict):
    global _config
    _config = dict(flatdict.FlatDict(spec, delimiter="."))

    #forces autodetect of kube if not provided
    if not exists('openserverless.kube'):
        put('openserverless.kube','auto')

    return True

def clean():
    global _config
    _config = {}

def exists(key):
    return key in _config

def get(key, envvar=None, defval=None):
    val = _config.get(key)

    if envvar and envvar in os.environ:
        val = os.environ[envvar]
    
    if val: 
        return val
    
    return defval

def put(key, value):
    _config[key] = value
    return True

def delete(key):
    if key in _config:
        del _config[key]
        return True

def getall(prefix=""):
    res = {}
    for key in _config.keys():
        if key.startswith(prefix):
            res[key] = _config[key]
    return res

def keys(prefix=""):
    res = []
    if _config:
        for key in _config.keys():
            if key.startswith(prefix):
                res.append(key)
    return res

def detect_labels(labels=None):    
    # skip autodetection of openserverless.kube if already available in _config
    if exists('openserverless.kube') and get('openserverless.kube') != 'auto':
        logging.info(f"*** configuration provided already a openserverless.kube={get('openserverless.kube')}")
        return {}

    # read labels if not available
    if not labels:
        import openserverless.kube as kube
        labels = kube.kubectl("get", "nodes", jsonpath='{.items[].metadata.labels}')        
    
    res = {}
    kube = None
    for i in labels:
        for j in list(i.keys()):
            if j.startswith(LABEL_PREFIX):
                key = f"openserverless.{j[len(LABEL_PREFIX):]}"
                res[key] = i[j]
                _config[key] = i[j]

    for i in labels:
        for j in list(i.keys()):
            # detect the kube type
            if j.find("eksctl.io") >= 0:
                kube ="eks"
                break
            if j.find("k8s.io/cloud-provider-aws") >= 0:
                kube ="eks"
                break
            elif j.find("microk8s.io") >= 0:
                kube = "microk8s"
                break
            elif j.find("lke.linode.com") >=0:
                kube = "lks"
                break
            elif j.find("node.openshift.io") >=0:
                kube = "openshift"
                break
            elif j.endswith("kubernetes.io/instance-type") and i[j] == "k3s":
                kube = "k3s"
                break
            elif j.find("cloud.google.com/gke") >=0:
                kube = "gke"
                break 
            elif j.find("kubernetes.azure.com") >=0:
                kube = "aks"
                break                        
            # assign all the 'openserverless.io' labels
        
    if kube:
        res["openserverless.kube"] = kube 
        _config["openserverless.kube"] = kube
        return res

    # defaults to generic if it is not yet detected
    if exists('openserverless.kube') and get('openserverless.kube') == 'auto':
        _config["openserverless.kube"] = "generic"
        res["openserverless.kube"] = "generic"

    return res

def detect_storage(storages=None):
    res = {}
    if not storages:
        import openserverless.util as util

        try:
            detect_storageclass = True
            detect_provisioner = True

            # skips autodetection if already provided
            if exists('openserverless.storageclass') and get('openserverless.storageclass') != 'auto':
                logging.info(f"*** configuration provided already a openserverless.storageclass={get('openserverless.storageclass')}")
                detect_storageclass = False

            if exists('openserverless.provisioner') and get('openserverless.provisioner') != 'auto':
                logging.info(f"*** configuration provided already a openserverless.provisioner={get('openserverless.provisioner')}")
                detect_provisioner = False

            if not detect_storageclass and not detect_provisioner:
                return res    

            if detect_storageclass:
                storage_class = util.get_default_storage_class()
                if storage_class:
                    res['openserverless.storageclass'] = storage_class
                    _config['openserverless.storageclass'] = storage_class
            
            if detect_provisioner:
                provisioner = util.get_default_storage_provisioner()
                if(provisioner):
                    res['openserverless.provisioner'] = provisioner
                    _config['openserverless.provisioner'] = provisioner
        except:
            pass
    return res

def detect_object_storage(object_storages=None):
    """
    Detect the basic Object Store setup if enabled
    """
    res = {}
    if not object_storages:
        import openserverless.util as util

        try:
            detect_object_store = True
            detect_object_store_rgw_srv_name = True
            detect_object_store_rgw_srv_port = True

            # skips autodetection if cephobjectstore is not active
            if not exists('components.cosi') or not get('components.cosi'):
                logging.info(f"*** cephobjectstore support is not requested skipping auto configuration check")
                return res

            # skips autodetection if already provided
            if exists('cosi.bucket_storageclass') and get('cosi.bucket_storageclass') != 'auto':
                logging.info(f"*** configuration provided already a cosi.bucket_storageclass={get('cosi.bucket_storageclass')}")
                detect_object_store = False

            if exists('cosi.rgwservice_name') and get('cosi.rgwservice_name') != 'auto':
                logging.info(f"*** configuration provided already a cosi.rgwservice_name={get('cosi.rgwservice_name')}")
                detect_object_store_rgw_srv_name = False

            if exists('cosi.rgwservice_port') and get('cosi.rgwservice_port') != 'auto':
                logging.info(f"*** configuration provided already a cosi.rgwservice_port={get('cosi.rgwservice_port')}")
                detect_object_store_rgw_srv_port = False                

            if not detect_object_store and not detect_object_store_rgw_srv_name and not detect_object_store_rgw_srv_port:
                return res    

            if detect_object_store:
                storage_class = util.get_object_storage_class()
                if storage_class:
                    res['cosi.bucket_storageclass'] = storage_class
                    _config['cosi.bucket_storageclass'] = storage_class
            
            if detect_object_store_rgw_srv_name:
                rgwsrv = util.get_object_storage_rgw_srv_name()
                if(rgwsrv):
                    res['cosi.rgwservice_name'] = rgwsrv
                    _config['cosi.rgwservice_name'] = rgwsrv

            if detect_object_store_rgw_srv_port:
                rgwport = util.get_object_storage_rgw_srv_http_port()
                if(rgwport):
                    res['cosi.rgwservice_port'] = rgwport
                    _config['cosi.rgwservice_port'] = rgwport                   
        except:
            pass
    return res  

def detect_env():
    _config['operator.image'] = os.environ.get("OPERATOR_IMAGE", "missing-OPERATOR_IMAGE")
    _config['operator.tag'] = os.environ.get("OPERATOR_TAG", "missing-OPERATOR_TAG")

    # skip autodetection of controller.image if already configure into whisk.yaml
    if not exists('controller.image'):
        _config['controller.image'] = os.environ.get("CONTROLLER_IMAGE", "missing-CONTROLLER_IMAGE")
        _config['controller.tag'] = os.environ.get("CONTROLLER_TAG", "missing-CONTROLLER_TAG")
    else:
        logging.warn(f"OW controller image detection skipped. Using {get('controller.image')}")

    if not exists('invoker.image'):
        _config['invoker.image'] = os.environ.get("INVOKER_IMAGE", "missing-INVOKER_IMAGE")
        _config['invoker.tag'] = os.environ.get("INVOKER_TAG", "missing-INVOKER_TAG")
    else:
        logging.warn(f"OW invoker image detection skipped. Using {get('invoker.image')}")

def detect():
    detect_storage()
    detect_labels()
    detect_env()
    detect_object_storage()

def dump_config():
    import openserverless.config as cfg
    for k in cfg.getall():
        logging.debug(f"{k} = {cfg.get(k)}") 
