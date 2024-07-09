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

class CephObjectBucketClaimData:
    _data = {}

    def __init__(self, bucket_name):
        self._data = util.get_cosi_config_data()
        self._data['bucket_name'] = bucket_name

    def dump(self):
        logging.debug(json.dumps(self._data))

    def with_quota_enabled(self,value: bool):
        self._data['quota_enabled']=value

    def with_quota_limit(self,value: str):
        self._data['quota_limit']=value

    def build_spec(self, where: str, out_template, tpl = "cosi-obc-tpl.yaml"):  
        logging.info(f"*** Building ObjectBucketClaim template for bucket {self._data['bucket_name']} via template {tpl}")
        return kus.processTemplate(where, tpl, self._data, out_template)

    def render_template(self,tpl = "cosi-obc-tpl.yaml"):
        """
        uses the given template to render an ObjectBucketClaim template and returns the path to the template
        """        
        out = f"/tmp/__{self._data['bucket_name']}_{tpl}"
        file = ntp.spool_template(tpl, out, self._data)
        return os.path.abspath(file)

    def _get_status(self):
        statuses = kube.kubectl("get", f"objectbucketclaim/{self._data['bucket_name']}", jsonpath="{.status}")
        if statuses and len(statuses) > 0:
            return statuses[0]
        return None        

    @nuv_retry()
    def wait_for_bucket_spec(self):
        """
        Wait for the ObjectBucketClaim to become bound and return the generated bucketName
        return the ObjectBucketClaim generated bucketName
        """
        status = self._get_status()
        if('phase' in status and status['phase'] in ['Bound']):
            bucket_names = kube.kubectl("get", f"objectbucketclaim/{self._data['bucket_name']}", jsonpath="{.spec.bucketName}")
            return bucket_names[0]

        raise Exception(f"objectbucketclaim/{self._data['bucket_name']} not bound yet")

    @nuv_retry()
    def _get_secret(self, secret_name):
        secrets = kube.kubectl("get", f"secret/{secret_name}", jsonpath="{.data}")
        if secrets and len(secrets) > 0:
            return secrets[0]
        
        raise Exception(f"secret/{secret_name} not found yet")         

    def extract_obc_secret_data(self, generated_bucket_name):
        """
        Extract data from a secret generated when Rook deploys a ObjectBucketClaim. The secret contains a data structure with these values
        apiVersion: v1
        Kind: Secret
        data:
            AWS_ACCESS_KEY_ID: QzVLSFdCVlZHOEEyTlk0RElUVEg=
            AWS_SECRET_ACCESS_KEY: V0FiTGNIa3JPMUxqSjFKcjRmTGtkYnRCa0NCdkI3SWFDSEVUeVIzdA==
        return: dictionary containing {bucket_name, access_key, secret_key}
        """
        secret = self._get_secret(self._data['bucket_name'])

        return {
            "bucket_name":generated_bucket_name,
            "access_key":util.b64_decode(secret['AWS_ACCESS_KEY_ID']),
            "secret_key":util.b64_decode(secret['AWS_SECRET_ACCESS_KEY'])            
        }
    
    def deploy(self):
        """
        Build a ObjectBucketClaim template and deploys it. Check that the ObjectBucketClaim becomes Bound 
        and extract the information about the ObjectBucketClaim secrets
        return: dictionary containing {bucket_name, access_key, secret_key} attributes
        """
        try:
            logging.info(f"*** deploying ObjectBucketClaim {self._data['bucket_name']}")
            path_to_template_yaml = self.render_template()
            kube.kubectl("apply", "-f",path_to_template_yaml)
            os.remove(path_to_template_yaml)
            logging.info(f"*** ObjectBucketClaim {self._data['bucket_name']} deployed successfully.")
            
            generated_bucket_name = self.wait_for_bucket_spec()
            logging.info(f"generated bucket name {generated_bucket_name} for objectbucketclaim/{self._data['bucket_name']}. Extracting data")
            return self.extract_obc_secret_data(generated_bucket_name)
        except Exception as e:
            logging.warn(e)       
            return None

    def undeploy(self):
        """
        Removes the ObjectBucketClaim 
        """
        try:
            logging.info(f"*** undeploying ObjectBucketClaim {self._data['bucket_name']}")            
            kube.kubectl("delete", f"objectbucketclaim/{self._data['bucket_name']}")
            return True
        except Exception as e:
            logging.warn(e)       
            return False             