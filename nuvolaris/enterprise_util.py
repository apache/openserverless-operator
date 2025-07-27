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

import nuvolaris.config as cfg
import nuvolaris.kube as kube
import nuvolaris.util as util
import logging
import re

# extract the srv name from 
def extract_host(srv_address_url):
    """
    >>> extract_host("zookeeper-0.zookeeper:2181")
    'zookeeper-0.zookeeper'
    >>> extract_host("zookeeper-0.zookeeper")
    'zookeeper-0.zookeeper'
    >>> extract_host("zookeeper-0.zookeeper.nuvolaris.svc.cluster.local:2181")
    'zookeeper-0.zookeeper.nuvolaris.svc.cluster.local'
    """
    host_regex = r'([a-z0-9\-._~%]+)'
    m = re.search(host_regex, srv_address_url)
    return m.group(0)

def get_invoker_image_data(data):
    invoker_image = cfg.get("invoker.image")

    if ":" in invoker_image:
        img_data = util.parse_image(invoker_image)
        data['invoker_image'] = img_data["image"]
        data['invoker_tag'] = img_data["tag"]
    else:        
        data['invoker_image'] = cfg.get("invoker.image") or "ghcr.io/nuvolaris/openwhisk-invoker"
        data['invoker_tag'] = cfg.get("invoker.tag") or "3.1.0-mastrogpt.2402101445"    

def getEnterpriseControllerConfigData():
    data = {
        "name":"controller",
        "couchdb_host": cfg.get("couchdb.host") or "couchdb",
        "couchdb_port": cfg.get("couchdb.port") or "5984",
        "couchdb_admin_user": cfg.get("couchdb.admin.user"),
        "couchdb_admin_password": cfg.get("couchdb.admin.password"),
        "couchdb_controller_user": cfg.get("couchdb.controller.user"),
        "couchdb_controller_password": cfg.get("couchdb.controller.password"),
        "couchdb_invoker_user": cfg.get("couchdb.invoker.user"),
        "couchdb_invoker_password": cfg.get("couchdb.invoker.password"),        
        "triggers_fires_perMinute": cfg.get("configs.limits.triggers.fires-perMinute") or 999,
        "actions_sequence_maxLength": cfg.get("configs.limits.actions.sequence-maxLength") or 50,
        "actions_invokes_perMinute": cfg.get("configs.limits.actions.invokes-perMinute") or 999,
        "actions_invokes_concurrent": cfg.get("configs.limits.actions.invokes-concurrent") or 250,
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
        "loadbalancer_blackbox_fraction": cfg.get("configs.limits.loadbalancer.blackbox-fraction") or "10%",
        "loadbalancer_timeout_factor": cfg.get("configs.limits.loadbalancer.timeout-factor") or "2",
        "controller_host": cfg.get("controller.host") or "localhost",
        "controller_port": cfg.get("controller.port") or "3233",
        "controller_protocol": cfg.get("controller.protocol") or "http",
        "invoker_host": cfg.get("invoker.host") or "localhost",
        "invoker_port": cfg.get("invoker.port") or "8080",
        "invoker_protocol": cfg.get("invoker.protocol") or "http",        
        "kafka_host": cfg.get("nuvolaris.kafka.url") or  "kafka:9092",
        "zookeeper_url": cfg.get('nuvolaris.zookeeper.url') or "zookeeper-0.zookeeper:2181",
        "controller_java_opts": cfg.get('configs.controller.javaOpts') or "-Xmx1024M",
        "controller_logging_level": cfg.get('configs.controller.loggingLevel') or "INFO",
        "controller_replicas": cfg.get('configs.controller.replicas') or 1,
        "container_cpu_req": cfg.get('configs.controller.resources.cpu-req') or "1",
        "container_cpu_lim": cfg.get('configs.controller.resources.cpu-lim') or "2",
        "container_mem_req": cfg.get('configs.controller.resources.mem-req') or "1G",
        "container_mem_lim": cfg.get('configs.controller.resources.mem-lim') or "2G",
        "container_manage_resources": cfg.exists('configs.controller.resources.cpu-req'),
        "usePrivateRegistry":cfg.get('components.registry') or False,      
    }
    
    util.get_controller_image_data(data)
    get_invoker_image_data(data)
    enterprise_affinity_tolerations_data(data)    
    return data

def getEnterpriseInvokerConfigData():
    data = {
        "name":"invoker",
        "couchdb_host": cfg.get("couchdb.host") or "couchdb",
        "couchdb_port": cfg.get("couchdb.port") or "5984",
        "couchdb_admin_user": cfg.get("couchdb.admin.user"),
        "couchdb_admin_password": cfg.get("couchdb.admin.password"),
        "couchdb_controller_user": cfg.get("couchdb.controller.user"),
        "couchdb_controller_password": cfg.get("couchdb.controller.password"),
        "couchdb_invoker_user": cfg.get("couchdb.invoker.user"),
        "couchdb_invoker_password": cfg.get("couchdb.invoker.password"),        
        "triggers_fires_perMinute": cfg.get("configs.limits.triggers.fires-perMinute") or 999,
        "actions_sequence_maxLength": cfg.get("configs.limits.actions.sequence-maxLength") or 50,
        "actions_invokes_perMinute": cfg.get("configs.limits.actions.invokes-perMinute") or 999,
        "actions_invokes_concurrent": cfg.get("configs.limits.actions.invokes-concurrent") or 250,
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
        "loadbalancer_blackbox_fraction": cfg.get("configs.limits.loadbalancer.blackbox-fraction") or "10%",
        "loadbalancer_timeout_factor": cfg.get("configs.limits.loadbalancer.timeout-factor") or "2",
        "controller_host": cfg.get("controller.host") or "localhost",
        "controller_port": cfg.get("controller.port") or "3233",
        "controller_protocol": cfg.get("controller.protocol") or "http",
        "invoker_host": cfg.get("invoker.host") or "localhost",
        "invoker_port": cfg.get("invoker.port") or "8080",
        "invoker_protocol": cfg.get("invoker.protocol") or "http",        
        "kafka_host": cfg.get("nuvolaris.kafka.url") or  "kafka:9092",
        "zookeeper_url": cfg.get('nuvolaris.zookeeper.url') or "zookeeper-0.zookeeper:2181",
        "invoker_java_opts": cfg.get('configs.invoker.javaOpts') or "-Xmx1024M",
        "invoker_containerpool_usermemory": cfg.get('configs.invoker.containerPool.userMemory') or "2048m",
        "invoker_logging_level": cfg.get('configs.invoker.loggingLevel') or "INFO",
        "invoker_replicas": cfg.get('configs.invoker.replicas') or 1,
        "container_cpu_req": cfg.get('configs.invoker.resources.cpu-req') or "1",
        "container_cpu_lim": cfg.get('configs.invoker.resources.cpu-lim') or "2",
        "container_mem_req": cfg.get('configs.invoker.resources.mem-req') or "1G",
        "container_mem_lim": cfg.get('configs.invoker.resources.mem-lim') or "2G",
        "container_manage_resources": cfg.exists('configs.invoker.resources.cpu-req'),
        "kubernetes_timeouts_run":cfg.get('configs.invoker.kubernetes.timeouts_run') or "1",
        "kubernetes_timeouts_logs":cfg.get('configs.invoker.kubernetes.timeouts_logs') or "1",       
        "kubernetes_port_forwarding_enabled":cfg.get('configs.invoker.kubernetes.port_forwarding_enabled') and "true" or "false",
        "kubernetes_action_namespace":cfg.get('configs.invoker.kubernetes.action_namespace') or "nuvolaris",
        "kubernetes_user_pod_affinity_enabled":cfg.get('configs.invoker.kubernetes.user_pod_affinity_enabled') and "true" or "false",
        "kubernetes_user_pod_affinity_key":cfg.get('configs.invoker.kubernetes.user_pod_affinity_key') or "nuvolaris-role",
        "kubernetes_user_pod_affinity_value":cfg.get('configs.invoker.kubernetes.user_pod_affinity_value') or "invoker",
        "usePrivateRegistry":cfg.get('components.registry') or False,
    }

    util.get_controller_image_data(data)
    get_invoker_image_data(data)
    invoker_affinity_tolerations_data(data)
    return data    

def get_prometheus_config_data():
    data = {
        "name":"nuvolaris-prometheus-server",
        "pod_anti_affinity_name":"nuvolaris-prometheus-server", 
        "pvcName":"nuvolaris-prometheus-server-pvc",
        "pvcAccessMode":"ReadWriteOnce",
        "size": cfg.get("monitoring.prometheus.volume-size") or 10,
        "storageClass": cfg.get("nuvolaris.storageclass"),
        "applypodsecurity":util.get_enable_pod_security()
    }
    util.common_affinity_tolerations_data(data)

    return data

def get_am_config_data():
    data = {
        "name":"nuvolaris-prometheus-alertmanager",
        "pod_anti_affinity_name":"nuvolaris-prometheus-alertmanager",      
        "pvcName":"storage-nuvolaris-prometheus-alertmanager",
        "pvcAccessMode":"ReadWriteOnce",
        "size": cfg.get("monitoring.alert-manager.volume-size") or 2,
        "storageClass": cfg.get("nuvolaris.storageclass"),
        "slack": cfg.get("monitoring.alert-manager.slack.enabled") or False,
        "slack_channel_name": cfg.get("monitoring.alert-manager.slack.slack_channel_name") or '#monitoring-nuvolaris',
        "slack_api_url": cfg.get("monitoring.alert-manager.slack.slack_api_url","SLACK_API_URL",""),
        "slack_default": cfg.get("monitoring.alert-manager.slack.default") or False,
        "gmail": cfg.get("monitoring.alert-manager.gmail.enabled") or False,
        "gmail_default": cfg.get("monitoring.alert-manager.gmail.false") or False,
        "email_recipients": cfg.get("monitoring.alert-manager.gmail.to"),
        "email_from": cfg.get("monitoring.alert-manager.gmail.from"),
        "gmail_username": cfg.get("monitoring.alert-manager.gmail.username","GMAIL_USERNAME",""),
        "gmail_password": cfg.get("monitoring.alert-manager.gmail.password","GMAIL_PASSWORD",""),
        "applypodsecurity":util.get_enable_pod_security()
    }
    util.common_affinity_tolerations_data(data)
    return data

# populate specific affinity data for enterprise controller
def enterprise_affinity_tolerations_data(data):
    util.common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "controller"

# populate specific affinity data for enterprise invoker
def invoker_affinity_tolerations_data(data):
    util.common_affinity_tolerations_data(data)
    data["pod_anti_affinity_name"] = "invoker"

# populate specific affinity data for zookeper
def get_zookeeper_config_data():
    data = {
        "name":"zookeeper",
        "pod_anti_affinity_name":"zookeeper",
        "data_volume_size": cfg.get('zookeeper.data-volume-size') or "10",
        "log_volume_size": cfg.get('zookeeper.log-volume-size') or "5",
        "storage_class": cfg.get("nuvolaris.storageclass")
    }
    util.common_affinity_tolerations_data(data)
    return data

# populate specific affinity data for zookeper
def get_kafka_config_data():
    data = {
        "name":"kafka",
        "pod_anti_affinity_name":"kafka",
        "data_volume_size": cfg.get('kafka.volume-size') or "10",
        "storage_class": cfg.get("nuvolaris.storageclass") or "standard"
    }
    util.common_affinity_tolerations_data(data)
    return data    