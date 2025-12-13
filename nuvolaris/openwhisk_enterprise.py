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
import nuvolaris.enterprise_util as cfg_util
import nuvolaris.util as util
import os, os.path
import logging
import kopf

def create(owner=None):
    logging.info("*** setup openwhisk in enterprise mode activated")
    data = cfg_util.getEnterpriseControllerConfigData()

    whisk_image = data["controller_image"]
    whisk_tag = data["controller_tag"]

    logging.info(f"*** configuring whisk controller {whisk_image}:{whisk_tag}")
    tplp = ["enterprise-np.yaml","enterprise-sts.yaml"]
    if(data['affinity'] or data['tolerations']):
       tplp.append("affinity-tolerance-sts-core-attach.yaml")    

    logging.info(f"using controller image {whisk_image}:{whisk_tag}")
    config = kus.image(whisk_image, newTag=whisk_tag)
    config += kus.patchTemplates("openwhisk-enterprise", tplp, data)
    spec = kus.kustom_list("openwhisk-enterprise", config, templates=[], data=data)
    
    if owner:
        kopf.append_owner_reference(spec['items'], owner)
    else:
        cfg.put("state.controller.spec", spec)

    
    res = kube.apply(spec)

    # dynamically detect controller pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.app == 'controller')].metadata.name}")

    logging.info("*** setup openwhisk in enterprise mode completed")
    return res

def delete():
    res = ""
    if cfg.exists("state.controller.spec"):
        res = kube.delete(cfg.get("state.controller.spec"))
        cfg.delete("state.controller.spec")
    res += kube.kubectl("delete", "pod", "-l", "user-action-pod=true")
    return res
