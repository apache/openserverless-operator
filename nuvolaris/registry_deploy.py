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
import nuvolaris.kustomize as kus
import nuvolaris.kube as kube
import nuvolaris.config as cfg
import nuvolaris.util as util
import logging
import kopf
import os
import nuvolaris.apihost_util as apihost_util
import nuvolaris.openwhisk as openwhisk
import nuvolaris.endpoint as endpoint
import nuvolaris.operator_util as operator_util

from nuvolaris.secret_htpasswd_data import SecretHtpasswordData
from nuvolaris.secret_imagepull_data import ImagePullSecretData
from nuvolaris.ingress_data import IngressData
from nuvolaris.route_data import RouteData


def create_external_registry(data, owner=None):
    logging.info("setting up an external registry")

    #set the registry secret
    registrySecret = SecretHtpasswordData(data['registryUsername'],data['registryPassword'])
    registrySecret.with_secret_name("registry-auth-secret")
    path_to_template_yaml = registrySecret.render_template("nuvolaris")
    res = kube.kubectl("apply", "-f",path_to_template_yaml)
    os.remove(path_to_template_yaml)

    #set the registry pull secret
    registryPullSecret = ImagePullSecretData(data['registryUsername'],data['registryPassword'],data['repoHostname'])
    registryPullSecret.with_secret_name("registry-pull-secret")
    path_to_template_yaml = registryPullSecret.render_template("nuvolaris")
    
    res += kube.kubectl("apply", "-f",path_to_template_yaml)
    os.remove(path_to_template_yaml)
    _annotate_registry_metadata(data)
    
    return res

def create_internal_registry(data, owner=None):
    logging.info("setting up an internal registry")
    tplp = ["pvc-attach.yaml"]

    if(data['affinity'] or data['tolerations']):
       tplp.append("affinity-tolerance-sts-core-attach.yaml")

    kust = kus.patchTemplates("registry",tplp , data)     

    #patch the registry secret    
    registrySecret = SecretHtpasswordData(data['registryUsername'],data['registryPassword'])
    registrySecret.with_secret_name("registry-auth-secret")
    kust += registrySecret.generateHtPasswordPatch()

    #path the registry pull secret
    registryPullSecret = ImagePullSecretData(data['registryUsername'],data['registryPassword'],data['repoHostname'])
    registryPullSecret.with_secret_name("registry-pull-secret")    
    kust += registryPullSecret.generatePullSecretPatch()

    spec = kus.kustom_list("registry", kust, templates=[], data=data)

    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.registry.spec", spec)
    res = kube.apply(spec)

    wait_for_registry_ready()
    _annotate_registry_metadata(data)

    if data['ingressEnabled']:
        create_registry_ingress(data)

    logging.info(f"created internal registry: {res}")
    return res    

def create(owner=None):    
    data = util.get_registry_config_data()    
    assign_registry_hostname(data)

    if data['mode'] == 'internal':        
        return create_internal_registry(data, owner)
    else:
        return create_external_registry(data, owner)
    
def _annotate_registry_metadata(data):
    """
    annotate nuvolaris configmap with entries for registry connectivity REGISTRY_ENDPOINT, REGISTRY_USERNAME, RESIGTRY_PASSWORD    
    """ 
    try:
        openwhisk.annotate(f"registry_host={data['repoHostname']}")
        openwhisk.annotate(f"registry_internal_host={data['repoSvcHostname']}")
        openwhisk.annotate(f"registry_username={data['registryUsername']}")
        openwhisk.annotate(f"registry_password={data['registryPassword']}")

        if data['repoUrl']:
            openwhisk.annotate(f"registry_url={data['repoUrl']}")

        return None
    except Exception as e:
        logging.error(f"failed to annotate registry_host for nuvolaris: {e}")
        return None     

#
# Determine the registry hostname to be set, when an internal registry must be set
#
def assign_registry_hostname(data):
    if data['repoHostname'] not in ["auto"]:
        return
    
    if not data['ingressEnabled']:        
        data['repoHostname'] = data['repoSvcHostname']     
        return
    
    runtime = cfg.get('nuvolaris.kube')
    repoUrl = apihost_util.append_prefix_to_url(apihost_util.get_apihost(runtime), "img")        
    data['repoHostname'] = apihost_util.extract_hostname(repoUrl)
    data['repoUrl'] = repoUrl

    logging.info(f"assigned registry hostname {data['repoHostname']}")


def wait_for_registry_ready():
    # dynamically detect registry pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.name == 'registry')].metadata.name}")

def create_registry_ingress(data, owner=None):
    """
    Creates all the REGISTRY related ingresses according to provide configuration
    """    
    if cfg.get('nuvolaris.kube') == 'openshift':           
        return deploy_registry_route(data)
    else:
        return deploy_registry_ingress(data)
    
def deploy_registry_route(data, namespace="nuvolaris"):
    """
    Deploys a generic REGISTRY route ingress
    param: data
    param: namespace
    """
    route = RouteData(data['repoUrl'])
    route.with_route_name(endpoint.api_route_name(namespace,"registry"))
    route.with_service_name("nuvolaris-registry-svc")
    route.with_service_kind("Service")
    route.with_service_port("5000")
    route.with_context_path("/")

    logging.info("*** configuring registry route for service nuvolaris-registry-svc:5000")
    path_to_template_yaml = route.render_template(namespace)
    res = kube.kubectl("apply", "-f",path_to_template_yaml)
    os.remove(path_to_template_yaml)        
    return res

def deploy_registry_ingress(data, namespace="nuvolaris"):
    """
    Deploys a generic MINIO nginx/traefik ingress
    param: apihost
    param: namespace
    param: type (s3, console)
    param: service_name (normally it is minio)
    param: port (9000 or 9090)
    paramL context_path (/)
    """
    ingress = IngressData(data['repoUrl'])
    ingress.with_ingress_name(endpoint.api_ingress_name(namespace, "registry"))
    ingress.with_secret_name(endpoint.ingress_secret_name(namespace, "registry"))
    ingress.with_context_path("/")  
    ingress.with_service_name("nuvolaris-registry-svc")
    ingress.with_service_port("5000")

    if ingress.requires_traefik_middleware():
        logging.info("*** configuring traefik middleware for registry ingress")
        path_to_template_yaml = ingress.render_traefik_middleware_template(namespace)
        res = kube.kubectl("apply", "-f",path_to_template_yaml)
        os.remove(path_to_template_yaml)

    logging.info("*** configuring static ingress for registry")
    path_to_template_yaml = ingress.render_template(namespace)
    res = kube.kubectl("apply", "-f",path_to_template_yaml)
    os.remove(path_to_template_yaml)

    return res

def delete_registry_ingress(owner=None, namespace="nuvolaris"):
    """
    undeploys ingresses for registry apihost
    """    
    logging.info("*** removing ingresses for REGISTRY")
    runtime = cfg.get('nuvolaris.kube')
    ingress_class = util.get_ingress_class(runtime)
    
    try:
        res = ""
        if(runtime=='openshift'):
            res = kube.kubectl("delete", "route",endpoint.api_route_name(namespace,"registry"))
            return res

        res += kube.kubectl("delete", "ingress",endpoint.api_ingress_name(namespace,"registry"))    

        if(ingress_class == 'traefik'):            
            res = kube.kubectl("delete", "middleware.traefik.containo.us",endpoint.api_middleware_ingress_name(namespace,"registry"))         

        return res
    except Exception as e:
        logging.warning(e)       
        return None 

def delete_by_owner():
    spec = kus.build("registry")
    res = kube.delete(spec)
    logging.info(f"delete registry: {res}")
    return res

def delete_by_spec():
    spec = cfg.get("state.registry.spec")
    res = False
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete registry: {res}")
    return res

def delete(owner=None):
    delete_registry_ingress(owner)

    if owner:        
        return delete_by_owner()
    else:
        return delete_by_spec()
    
def patch(status, action, owner=None):
    """
    Called by the operator patcher to create/delete registry component
    """
    try:
        logging.info(f"*** handling request to {action} registry")
        if action == 'create':
            msg = create(owner)
            operator_util.patch_operator_status(status, 'registry', 'on')
        else:
            msg = delete(owner)
            operator_util.patch_operator_status(status, 'registry', 'off')

        logging.info(msg)
        logging.info(f"*** handled request to {action} registry")
    except Exception as e:
        logging.error('*** failed to update milvus: %s' % e)
        operator_util.patch_operator_status(status, 'registry', 'error')

def patch_ingresses(status, action, owner=None):
    """
    Called by the operator patcher to create/delete registry component
    """
    try:
        logging.info(f"*** handling request to {action} registry ingresses")
        data = util.get_registry_config_data()
        assign_registry_hostname(data)

        if action == 'update':
            msg = create_registry_ingress(data, owner)
            operator_util.patch_operator_status(status,'registry-ingresses','on')

        logging.info(msg)        
        logging.info(f"*** hanlded request to {action} registry ingresses") 
    except Exception as e:
        logging.error('*** failed to update minio ingresses: %s' % e)    
        operator_util.patch_operator_status(status,'registry-ingresses','error')
