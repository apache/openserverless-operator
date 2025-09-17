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
import nuvolaris.apihost_util as apihost_util
import nuvolaris.endpoint as endpoint
import nuvolaris.openwhisk as openwhisk

from nuvolaris.ingress_data import IngressData
from nuvolaris.route_data import RouteData

def deploy_seaweedfs_route(apihost,namespace,type,service_name,port,context_path):
    """
    Deploys a generic SEAWEEDFS route ingress
    param: apihost
    param: namespace
    param: type (s3, console)
    param: service_name (normally it is seaweedfs)
    param: port (9090 or 9000)
    paramL context_path (/)
    """
    route = RouteData(apihost)
    route.with_route_name(endpoint.api_route_name(namespace,type))
    route.with_service_name(service_name)
    route.with_service_kind("Service")
    route.with_service_port(port)
    route.with_context_path(context_path)

    logging.info(f"*** configuring seaweedfs route for service {service_name}:{port}")
    path_to_template_yaml = route.render_template(namespace)
    res = kube.kubectl("apply", "-f",path_to_template_yaml)
    os.remove(path_to_template_yaml)        
    return res

def deploy_seaweedfs_ingress(apihost, namespace, type, service_name,port,context_path):
    """
    Deploys a generic SEAWEEDFS nginx/traefik ingress
    param: apihost
    param: namespace
    param: type (s3, console)
    param: service_name (normally it is seaweedfs)
    param: port (8888 or 8333)
    paramL context_path (/)
    """
    ingress = IngressData(apihost)
    ingress.with_ingress_name(endpoint.api_ingress_name(namespace, type))
    ingress.with_secret_name(endpoint.ingress_secret_name(namespace, type))
    ingress.with_context_path(context_path)  
    ingress.with_service_name(service_name)
    ingress.with_service_port(port)

    if ingress.requires_traefik_middleware():
        logging.info(f"*** configuring traefik middleware for {type} ingress")
        path_to_template_yaml = ingress.render_traefik_middleware_template(namespace)
        res = kube.kubectl("apply", "-f",path_to_template_yaml)
        os.remove(path_to_template_yaml)

    logging.info(f"*** configuring static ingress for {type}")
    path_to_template_yaml = ingress.render_template(namespace)
    res = kube.kubectl("apply", "-f",path_to_template_yaml)
    os.remove(path_to_template_yaml)

    return res 


def create_s3_ingress_endpoint(data, runtime, apihost, owner=None):
    """
    exposes SEAWEEDFS S3 api ingress ingress/route
    """
    if runtime == 'openshift':
        return deploy_seaweedfs_route(apihost,"nuvolaris","seaweedfs-s3","seaweedfs","9000","/")
    else:
        return deploy_seaweedfs_ingress(apihost,"nuvolaris","seaweedfs-s3","seaweedfs","9000","/")

def create_console_ingress_endpoint(data, runtime, apihost, owner=None):
    """
    exposes SEAWEEDFS api ingress ingress/route
    """

    if runtime == 'openshift':           
        return deploy_seaweedfs_route(apihost,"nuvolaris","seaweedfs-filer","seaweedfs","9090","/")
    else:
        return deploy_seaweedfs_ingress(apihost,"nuvolaris","seaweedfs-filer","seaweedfs","9090","/")
    
def get_seaweedfs_ingress_hostname(runtime, apihost_url, prefix, hostname_from_config):
    """
    Determine the SEAWEEDFS ingress hostname. In auto mode the prefix is appended
    to the configured apihost,, otherwise the one from configuration is used.
    """
    if hostname_from_config in ["auto"]:
        return apihost_util.append_prefix_to_url(apihost_url, prefix)

    return apihost_util.get_ingress_url(runtime, hostname_from_config)

    
def create_seaweedfs_ingresses(data, owner=None):
    """
    Creates all the SEAWEEDFS related ingresses according to provide configuration
    """
    runtime = cfg.get('nuvolaris.kube')
    apihost_url = apihost_util.get_apihost(runtime)
    res = ""

    if data['seaweedfs_s3_ingress_enabled']:
        s3_hostname_url = get_seaweedfs_ingress_hostname(runtime, apihost_url,"s3",data['seaweedfs_s3_ingress_hostname'])
        res += create_s3_ingress_endpoint(data, runtime, s3_hostname_url, owner)

        if res:
            openwhisk.annotate(f"s3_api_url={s3_hostname_url}")
    
    if data['seaweedfs_console_ingress_enabled']:
        filer_hostname_url = get_seaweedfs_ingress_hostname(runtime, apihost_url,"filer",data['seaweedfs_console_ingress_hostname'])
        res += create_console_ingress_endpoint(data, runtime, filer_hostname_url, owner)

        if res:
            openwhisk.annotate(f"s3_console_url={filer_hostname_url}")

    return res


def delete_seaweedfs_ingress(runtime, namespace, ingress_class, type, owner=None):
    """
    undeploys ingresses for seaweedfs apihost
    """    
    logging.info("*** removing ingresses for seaweedfs upload")
    
    try:
        res = ""
        if(runtime=='openshift'):
            res = kube.kubectl("delete", "route",endpoint.api_route_name(namespace,type))
            return res

        res += kube.kubectl("delete", "ingress",endpoint.api_ingress_name(namespace,type))    

        if(ingress_class == 'traefik'):            
            res = kube.kubectl("delete", "middleware.traefik.containo.us",endpoint.api_middleware_ingress_name(namespace,type))         

        return res
    except Exception as e:
        logging.warn(e)       
        return None    

def delete_seaweedfs_ingresses(data, owner=None):
    namespace = "nuvolaris"
    runtime = cfg.get('nuvolaris.kube')
    ingress_class = util.get_ingress_class(runtime)
    res = ""

    if data['seaweedfs_s3_ingress_enabled']:
        res += delete_seaweedfs_ingress(runtime, namespace, ingress_class, "seaweedfs-s3", owner)
    
    if data['seaweedfs_console_ingress_enabled']:
        res += delete_seaweedfs_ingress(runtime, namespace, ingress_class, "seaweedfs-filer", owner)

    return res       