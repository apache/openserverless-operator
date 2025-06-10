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
import requests as req
import json
import urllib
import os

from .config_exception import ConfigException
from base64 import b64decode


SERVICE_CERT_FILENAME = "/tmp/custom_ca.crt"

class KubeApiClient:

    def __init__(self, kube_host, kube_port, base64_accesstoken, base64_crt):
        """
        param: kube_host
        param: kube_port
        param: base64_accesstoken base64 encodied token of a service account capable to deploy whisk users
        param: base64_crt 
        """
        self._load_config(kube_host, kube_port,base64_accesstoken, base64_crt)

    def _parse_b64(self, encoded_str):
        """
        Decode b64 encoded string
        param: encoded_str a Base64 encoded string
        return: decoded string
        """                      
        try:
            return b64decode(encoded_str).decode()
        except:
            raise ConfigException("Could not decode base64 encoded value")

    def _load_config(self,kube_host, kube_port,base64_accesstoken, base64_crt):
        """
        Load this Kube Client configuration parameters
        param: base64_accesstoken as service account access token to be used by this client when running inside an action
        param: base64_crt a ca certificate passed as base64 encoded string
        """

        if (not kube_host or not kube_port):
            raise ConfigException("Kubernetes service host/port are not set.")

        self.host = f"https://{kube_host}:{kube_port}"
        self.token = f"Bearer {self._parse_b64(base64_accesstoken)}"
        self.crt = self._parse_b64(base64_crt)

        # write certificate to a tmp file
        if not os.path.exists(SERVICE_CERT_FILENAME):
            with open(SERVICE_CERT_FILENAME, "w") as crt:
                crt.write(self.crt)

    def create_whisk_user(self, whisk_user_dict, namespace="nuvolaris"):
        """"
        Creates a whisk user using a POST operation
        param: whisk_user_dict a dictionary representing the whisksusers resource to create
        param: namespace default to nuvolaris
        return: True if the operation is successfully, False otherwise
        """
        url = f"{self.host}/apis/nuvolaris.org/v1/namespaces/{namespace}/whisksusers"
        headers = {'Authorization': self.token}

        try:
            print(f"POST request to {url}")
            response = None        
            response = req.post(url, headers=headers, data=json.dumps(whisk_user_dict), verify=False)

            if (response.status_code in [200,202]):
                print(f"POST to {url} succeeded with {response.status_code}. Body {response.text}")
                return True
                
            print(f"POST to {url} failed with {response.status_code}. Body {response.text}")
            return False
        except Exception as ex:
            print(ex)
            return False

    def delete_whisk_user(self, username, namespace="nuvolaris"):
        """"
        Delete a whisk user using a DELETE operation
        param: username of the whisksusers resource to delete
        param: namespace default to nuvolaris
        return: True if the operation is successfully, False otherwise
        """
        url = f"{self.host}/apis/nuvolaris.org/v1/namespaces/{namespace}/whisksusers/{username}"
        headers = {'Authorization': self.token}

        try:
            print(f"DELETE request to {url}")
            response = None        
            response = req.delete(url, headers=headers, verify=False)

            if (response.status_code in [200,202]):
                print(f"DELETE to {url} succeeded with {response.status_code}. Body {response.text}")
                return True
                
            print(f"DELETE to {url} failed with {response.status_code}. Body {response.text}")
            return False
        except Exception as ex:
            print(ex)
            return False    

    def get_whisk_user(self, username, namespace="nuvolaris"):
        """"
        Get a whisk user using a GET operation
        param: username of the whisksusers resource to delete
        param: namespace default to nuvolaris
        return: a dictionary representing the existing user, None otherwise
        """
        url = f"{self.host}/apis/nuvolaris.org/v1/namespaces/{namespace}/whisksusers/{username}"
        headers = {'Authorization': self.token}

        try:
            print(f"GET request to {url}")
            response = None        
            response = req.get(url, headers=headers, verify=False)

            if (response.status_code in [200,202]):
                print(f"GET to {url} succeeded with {response.status_code}. Body {response.text}")
                return json.loads(response.text)
                
            print(f"GET to {url} failed with {response.status_code}. Body {response.text}")
            return None
        except Exception as ex:
            print(ex)
            return None           
