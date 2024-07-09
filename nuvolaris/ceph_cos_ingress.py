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

from nuvolaris.ingress_data import IngressData
from nuvolaris.route_data import RouteData

def deploy_cos_route(apihost,namespace,type,service_name,port,context_path):
    """
    Deploys a generic CEPH COS route ingress under the rook-ceph namespace
    param: apihost
    param: namespace
    param: type (s3)
    param: service_name (normally it is the RGW hostname)
    param: port (80)
    paramL context_path (/)
    """
    route = RouteData(apihost)
    route.with_route_name(endpoint.api_route_name(namespace,type))
    route.with_service_name(service_name)
    route.with_service_kind("Service")
    route.with_service_port(port)
    route.with_context_path(context_path)
    route.with_namespace(namespace)

    logging.info(f"*** configuring CEPH cos route for service {service_name}:{port}")
    path_to_template_yaml = route.render_template(namespace)
    res = kube.kubectl("apply", "-f",path_to_template_yaml,namespace=namespace)
    os.remove(path_to_template_yaml)        
    return res

def deploy_cos_ingress(apihost, namespace, type, service_name,port,context_path):
    """
    Deploys a generic CEPH COS nginx/traefik ingress under the rook-ceph namespace
    param: apihost
    param: namespace
    param: type (s3, console)
    param: service_name (normally it is the RGW hostname)
    param: port (9000 or 9090)
    paramL context_path (/)
    """
    ingress = IngressData(apihost)
    ingress.with_ingress_name(endpoint.api_ingress_name(namespace, type))
    ingress.with_secret_name(endpoint.ingress_secret_name(namespace, type))
    ingress.with_context_path(context_path)  
    ingress.with_service_name(service_name)
    ingress.with_service_port(port)
    ingress.with_namespace(namespace)

    if ingress.requires_traefik_middleware():
        logging.info(f"*** configuring traefik middleware for {type} ingress")
        path_to_template_yaml = ingress.render_traefik_middleware_template(namespace)
        res = kube.kubectl("apply", "-f",path_to_template_yaml, namespace=namespace)
        os.remove(path_to_template_yaml)

    logging.info(f"*** configuring static ingress for {type}")
    path_to_template_yaml = ingress.render_template(namespace)
    res = kube.kubectl("apply", "-f",path_to_template_yaml,namespace=namespace)
    os.remove(path_to_template_yaml)

    return res 
    
def create_s3_ingress_endpoint(data, runtime, apihost,service_name="rook-ceph-rgw-nuvolaris-s3-store", service_port=80, owner=None):
    """
    exposes CEPH OBJECT STORE S3 api ingress ingress/route
    """
    if runtime == 'openshift':
        return deploy_cos_route(apihost,data['cluster_namespace'],"cos-s3", service_name, service_port,"/")
    else:
        return deploy_cos_ingress(apihost,data['cluster_namespace'],"cos-s3",service_name, service_port,"/")
    
def get_cos_ingress_hostname(runtime, apihost_url, prefix, hostname_from_config):
    """
    Determine CEPH COS ingress hostname. In auto mode the prefix is appended
    to the configured apihost,, otherwise the one from configuration is used.
    """
    if hostname_from_config in ["auto"]:
        return apihost_util.append_prefix_to_url(apihost_url, prefix)

    return apihost_util.get_ingress_url(runtime, hostname_from_config)

    
def create_cos_ingresses(data, owner=None):
    """
    Creates all the Ceph Object related ingresses according to provided configuration
    """
    runtime = cfg.get('nuvolaris.kube')
    apihost_url = apihost_util.get_apihost(runtime)
    res = ""
    
    if data['s3_ingress_enabled']:
        s3_hostname_url = get_cos_ingress_hostname(runtime, apihost_url,"s3",data['s3_ingress_hostname'])
        res += create_s3_ingress_endpoint(data, runtime, s3_hostname_url,data['rgwservice_name'],data['rgwservice_port'], owner)
    
    return res


def delete_cos_ingress(runtime, namespace, ingress_class, type, owner=None):
    """
    undeploys ingresses for CEPH COS
    """    
    logging.info(f"*** removing ingresses for CEPH COS")
    
    try:
        res = ""
        if(runtime=='openshift'):
            res = kube.kubectl("delete", "route",endpoint.api_route_name(namespace,type), namespace="rook-ceph")
            return res

        res += kube.kubectl("delete", "ingress",endpoint.api_ingress_name(namespace,type), namespace="rook-ceph")    

        if(ingress_class == 'traefik'):            
            res = kube.kubectl("delete", "middleware.traefik.containo.us",endpoint.api_middleware_ingress_name(namespace,type), namespace="rook-ceph")

        return res
    except Exception as e:
        logging.warn(e)       
        return None     

def delete_cos_ingresses(data, owner=None):
    namespace = "nuvolaris"
    runtime = cfg.get('nuvolaris.kube')
    ingress_class = util.get_ingress_class(runtime)

    if data['cos_s3_ingress_enabled']:
        res += delete_cos_ingress(runtime, namespace, ingress_class, "cos-s3", owner)
    

    return res     