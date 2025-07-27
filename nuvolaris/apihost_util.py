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
import re
import logging
import nuvolaris.config as cfg
import nuvolaris.kube as kube
import nuvolaris.util as util
import urllib.parse
import os, os.path

from nuvolaris.ip_util import IpUtil

# ensure if is an hostname, adding a suffix
def ensure_host(ip_address_str):
    """
    >>> ensure_host("142.251.163.105")
    '142.251.163.105.nip.io'
    >>> ensure_host("www.google.com")
    'www.google.com'
    """
    ip_address_regex = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_address_regex, ip_address_str):
        return f"{ip_address_str}.nip.io"
    return ip_address_str

def is_load_balanced_kube(runtime_str):
    """
    Test if the runtime has load balancer or not
    >>> is_load_balanced_kube("k3s")
    False
    >>> is_load_balanced_kube("microk8s")
    False
    >>> is_load_balanced_kube("eks")
    True
    >>> is_load_balanced_kube("lks")
    True
    >>> is_load_balanced_kube("aks")
    True
    >>> is_load_balanced_kube("kind")
    False
    """
    return runtime_str not in ["k3s","microk8s","kind"]

def to_ingress_ip(machine_ip_str):
    """
    Returns an array simulating the minimum required attributes
    representing an ip based ingress.
    >>> ingresses = to_ingress_ip("142.251.163.105")
    >>> len(ingresses) > 0
    True
    >>> ingresses[0]["ip"] == "142.251.163.105"
    True
    """
    return [{"ip":machine_ip_str}]

def get_ingress(namespace="ingress-nginx",ingress_srv_name="service/ingress-nginx-controller"):
    ingress = kube.kubectl("get", ingress_srv_name, namespace=namespace,jsonpath="{.status.loadBalancer.ingress[0]}")
    if ingress:
        return ingress
    
    return None

def assign_protocol(runtime_str, url):
    """
    Assign the url protocol. If not protocol is defined or it is in auto mode
    will use https in case the TLS compoenent is enabled, http otherwise.
    Setting inside the whisk.yaml the attribute nuvolaris.protocol will forse always to use the
    configured one, i.e it can be set as http despite it is in https and viceversa.
    """
    # if no protocol is defined, or it is in auto mode, uses https in case tls is enabled
    if cfg.exists("nuvolaris.protocol") and cfg.get("nuvolaris.protocol") in ["http","https"]:
        url = url._replace(scheme = cfg.get("nuvolaris.protocol"))    
    else:
        if cfg.get('components.tls'):
            url = url._replace(scheme = "https")
        else:
            url = url._replace(scheme = "http")

    # always use http on kind
    if runtime_str == "kind":
        url = url._replace(scheme = "http")

    return url    

def calculate_apihost(runtime_str,apiHost=None):
    """
    Calculate the apihost url
    """
    logging.info(f"*** openwhisk received ingress {apiHost}")
    url = urllib.parse.urlparse("https://pending")

    if apiHost and len(apiHost) > 0: 
        if "hostname" in apiHost[0]:
            url = url._replace(netloc = apiHost[0]['hostname'])
        elif "ip" in apiHost[0]:
            url = url._replace(netloc = ensure_host(apiHost[0]['ip']))

    # in auto mode we should use the calculated ip address and defaults to miniops.me
    if cfg.exists("nuvolaris.apihost") and not 'auto' == cfg.get('nuvolaris.apihost'):
        url =  url._replace(netloc = ensure_host(cfg.get("nuvolaris.apihost")))
    else:
        url =  url._replace(netloc = "miniops.me" )
    if cfg.exists("nuvolaris.apiport"):
        url = url._replace(netloc = f"{url.hostname}:{cfg.get('nuvolaris.apiport')}")

    final_url = assign_protocol(runtime_str, url)
    return final_url.geturl()      

def get_apihost(runtime_str):
    """
    Determine the api host based on the runtime and current configuration
    """
    apihost = ""

    if runtime_str in ["k3s","microk8s", "openshift"]:
        if(cfg.exists("nuvolaris.apihost") and 'auto' == cfg.get('nuvolaris.apihost') and not is_load_balanced_kube(runtime_str)):
            machine_ip = IpUtil().get_public_ip()
            logging.info(f"nuvolaris.apihost in auto mode. Will use machine public ip address {machine_ip}")
            apihost = calculate_apihost(runtime_str,to_ingress_ip(machine_ip))
        else:
            apihost = calculate_apihost(runtime_str,None)
    else:
        namespace = util.get_ingress_namespace(runtime_str)
        ingress_srv_name = util.get_ingress_service_name(runtime_str)
        
        apihost = calculate_apihost(runtime_str,get_ingress(namespace, ingress_srv_name))

    return apihost

def extract_hostname(url):
    """
    Parse a url and extract the hostname part
    >>> extract_hostname('http://localhost:8080')
    'localhost'
    >>> extract_hostname('https://nuvolaris.org')    
    'nuvolaris.org'
    """
    parsed_url = urllib.parse.urlparse(url)
    return parsed_url.hostname

def extract_port(url):
    """
    Parse a url and extract the port part
    >>> extract_port('http://localhost:8080')
    8080
    >>> extract_port('https://nuvolaris.org')
    """
    parsed_url = urllib.parse.urlparse(url)
    return parsed_url.port

def split_hostname_port(url):
    """
    Parse a url and extract the port part
    >>> split_hostname_port('http://localhost:8080')
    ('localhost', 8080)
    >>> split_hostname_port('https://nuvolaris.org')
    ('nuvolaris.org', None)
    """
    parsed_url = urllib.parse.urlparse(url)
    return parsed_url.hostname, parsed_url.port    


def get_user_static_hostname(runtime, username, apihost):
    """
    Determine the api host to be associated to a user namespace. In auto mode (input apihost=auto) it is derived by reading the apihost annotated
    inside the cm/config configMap prepending the user_namespace when needed.
    """
    
    apihost_url = util.get_apihost_from_config_map()

    if apihost_url:
        apihost = extract_hostname(apihost_url)
        return f"{username}.{apihost}"

    raise Exception(f"Could not determine hostname for static bucket for username {username}")

def get_user_static_url(runtime, hostname):
    """
    Build the full URL that will give access to the user web bucket via the static endpoint
    """
    url = urllib.parse.urlparse(f"http://{hostname}")

    final_url = assign_protocol(runtime, url)
    return final_url.geturl()

def get_url(runtime, hostname):
    """
    Build the full URL that will give access to the user web bucket via the static endpoint
    """
    url = urllib.parse.urlparse(f"http://{hostname}")

    final_url = assign_protocol(runtime, url)
    return final_url.geturl()    

def get_user_api_url(runtime, hostname, api_context):
    """
    Build the full URL that will give access to the user web bucket via the static endpoint
    """
    full_hostname = hostname.endswith("/") and f"{hostname}{api_context}" or f"{hostname}/{api_context}"
    url = urllib.parse.urlparse(f"http://{full_hostname}")

    final_url = assign_protocol(runtime, url)
    return final_url.geturl()

def append_prefix_to_url(url,prefix):
    """
    Appends the given prefix to the specified if not present
    >>> append_prefix_to_url("http://nuvolaris.dev:8080","www")    
    'http://www.nuvolaris.dev:8080'
    >>> append_prefix_to_url("http://www.nuvolaris.dev:8080","www")
    'http://www.nuvolaris.dev:8080'
    >>> append_prefix_to_url("http://nuvolaris.dev:8080",None)
    'http://nuvolaris.dev:8080'
    >>> append_prefix_to_url("https://nuvolaris.dev","www")
    'https://www.nuvolaris.dev'
    """
    try:
        if not prefix:
            return url

        tmp_url = urllib.parse.urlparse(url)        
        hostname = extract_hostname(url)
        port = extract_port(url)

        if prefix in hostname:
            return url

        if port:
            tmp_url = tmp_url._replace(netloc = f"{prefix}.{hostname}:{port}")
        else:    
            tmp_url = tmp_url._replace(netloc = f"{prefix}.{hostname}")
        
        return tmp_url.geturl()

    except Exception as e:
        return url
    
def get_ingress_url(runtime, hostname):
    """
    Build the full URL too an ingress according to the current config
    """
    url = urllib.parse.urlparse(f"http://{hostname}")

    final_url = assign_protocol(runtime, url)
    return final_url.geturl()

def add_suffix_to_url(url,suffix):
    """
    Appends the given suffix to the specified url if not present
    >>> add_suffix_to_url("http://nuvolaris.dev:8080","svc.cluster.local")    
    'http://nuvolaris.dev.svc.cluster.local:8080'
    >>> add_suffix_to_url("http://nuvolaris.dev.svc.cluster.local:8080","svc.cluster.local")
    'http://nuvolaris.dev.svc.cluster.local:8080'
    >>> add_suffix_to_url("http://nuvolaris.dev:8080",None)
    'http://nuvolaris.dev:8080'
    >>> add_suffix_to_url("https://nuvolaris.dev","svc.cluster.local")
    'https://nuvolaris.dev.svc.cluster.local'
    """
    try:
        if not suffix:
            return url

        tmp_url = urllib.parse.urlparse(url)        
        hostname = extract_hostname(url)
        port = extract_port(url)

        if suffix in hostname:
            return url

        if port:
            tmp_url = tmp_url._replace(netloc = f"{hostname}.{suffix}:{port}")
        else:    
            tmp_url = tmp_url._replace(netloc = f"{hostname}.{suffix}")
        
        return tmp_url.geturl()

    except Exception as e:
        return url    
  
