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
import json
import logging
import os
import nuvolaris.config as cfg
import nuvolaris.util as util
import nuvolaris.kustomize as kus
import nuvolaris.time_util as tutil
import nuvolaris.template as ntp
import urllib.parse
import nuvolaris.kube as kube

from nuvolaris.util import nuv_retry

class CephCosUserData:
    _data = {}

    def __init__(self, username):
        self._data = util.get_cosi_config_data()
        self._data['username'] = username

    def dump(self):
        logging.debug(json.dumps(self._data))

    def with_quota_enabled(self,value: bool):
        self._data['quota_enabled']=value

    def with_quota_limit(self,value: str):
        self._data['quota_limit']=value

    def with_bucket_limit(self,value: int):
        self._data['max_bucket_limit']=value       

    def build_spec(self, where: str, out_template, tpl = "cosi-user-tpl.yaml"):  
        logging.info(f"*** Building CephObjectStoreUser template for user {self._data['username']} via template {tpl}")
        return kus.processTemplate(where, tpl, self._data, out_template)

    def render_template(self,tpl="cosi-user-tpl.yaml"):
        """
        uses the given template to render a CephObjectStoreUser template and returns the path to the template
        """        
        out = f"/tmp/__{self._data['username']}_{tpl}"
        file = ntp.spool_template(tpl, out, self._data)
        return os.path.abspath(file)
    
    def _get_status(self):
        statuses = kube.kubectl("get", f"cephobjectstoreusers/{self._data['username']}", jsonpath="{.status}")
        if statuses and len(statuses) > 0:
            return statuses[0]
        return None

    @nuv_retry()
    def _wait_for_secret_name(self):
        """
        Wait for the cephobjectstoreuser to become ready and return the generated secretName
        return the cephobjectstoreuser generated secret Name
        """
        status = self._get_status()
        if('phase' in status and status['phase'] in ['Ready']):
            return status['info']['secretName']

        raise Exception(f"cephobjectstoreusers/{self._data['username']} not ready yet")

    @nuv_retry()
    def _get_secret(self, secret_name):
        secrets = kube.kubectl("get", f"secret/{secret_name}", jsonpath="{.data}")
        if secrets and len(secrets) > 0:
            return secrets[0]
        
        raise Exception(f"secret/{secret_name} not found yet")        

    def _extract_cos_user_secret_data(self, secret_name):
        """
        Extract data from a secret generated when Rook deploys a CephObjectStoreUser. The secret contains a data structure with these values
        apiVersion: v1
        Kind: Secret
        data:
            AccessKey: VkIyRjU5WTZXREVZWlQyUTZJMEc=
            Endpoint: aHR0cDovL3Jvb2stY2VwaC1yZ3ctbnV2b2xhcmlzLXMzLXN0b3JlLnJvb2stY2VwaC5zdmM6ODA=
            SecretKey: M2g2QVRCOXRERFVDcURpWnpmb3hTcWhuY25HS0IzSTQ3OTlCNkZ4bw==
        return: dictionary containing {username, access_key, secret_key, endpoint}
        """
        data =  self._get_secret(secret_name)
        return {
            "username":self._data['username'],
            "access_key":util.b64_decode(data['AccessKey']),
            "secret_key":util.b64_decode(data['SecretKey']),
            "endpoint":util.b64_decode(data['Endpoint'])
        }
    
    def deploy(self):
        """
        Build a CephObjectStoreUser template and deploys it. Check that the CephObjectStoreUser user becomes Ready 
        and extract the information about the User secrets
        return: dictionary containing {username, access_key, secret_key, endpoint} attributes
        """
        try:
            logging.info(f"*** deploying CephObjectStoreUser {self._data['username']}")
            path_to_template_yaml = self.render_template()
            kube.kubectl("apply", "-f",path_to_template_yaml)
            os.remove(path_to_template_yaml)
            logging.info(f"*** CephObjectStoreUser {self._data['username']} deployed successfully.")
            
            secret_name = self._wait_for_secret_name()
            logging.info(f"found secret {secret_name} for cephobjectstoreusers/{self._data['username']}. Extracting data")
            return self._extract_cos_user_secret_data(secret_name)
        except Exception as e:
            logging.warn(e)       
            return None

    def undeploy(self):
        """
        Removes the CephObjectStoreUser 
        """
        try:
            logging.info(f"*** undeploying CephObjectStoreUser {self._data['username']}")            
            kube.kubectl("delete", f"cephobjectstoreusers/{self._data['username']}")
            return True
        except Exception as e:
            logging.warn(e)       
            return False        