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
import nuvolaris.kustomize as kus
import nuvolaris.template as ntp
import bcrypt
import base64   

class SecretHtpasswordData:

    def __init__(self, username, password):
        self._data = {            
            "htpasswd":self.generate_htpasswd(username, password),
            'namespace':'nuvolaris'               
        }

    def generate_htpasswd_lines(self, username: str, password: str):
        htpasswd_lines = []        
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        htpasswd_lines.append(f"{username}:{hashed.decode()}")
        return "\n".join(htpasswd_lines)

    # base64 encode the content of htpasswd file       
    def generate_htpasswd(self, username: str, password: str):
        htpasswd_lines = self.generate_htpasswd_lines(username, password)        
        return base64.b64encode(htpasswd_lines.encode()).decode()

    def dump(self):
        logging.debug(json.dumps(self._data))

    def with_secret_name(self,value: str):
        self._data['secret_name']=value

    def with_namespace(self,value: str):
        self._data['namespace']=value                                                             

    def build_secret_spec(self, where: str, out_template=None, tpl = "generic-secret-htpassword-tpl.yaml"):        
        logging.info(f"*** Building htpassword secret template with name {self._data['secret_name']} via template {tpl}")
        return kus.processTemplate(where, tpl, self._data, out_template)

    def render_template(self,namespace,tpl= "generic-secret-htpassword-tpl.yaml"):
        """
        uses the given template to render a final htpassword secret template and returns the path to the template
        """
        logging.info(f"*** Rendering htpassword secret template with name {self._data['secret_name']} via template {tpl}")
        out = f"/tmp/__{namespace}_{tpl}"
        file = ntp.spool_template(tpl, out, self._data)
        return os.path.abspath(file)
    
    def generateHtPasswordPatch(self):
        """
        generate a patch entry for this secret
        """
        return kus.patchGenericEntry("Secret", self._data['secret_name'],"/data/htpasswd", self._data['htpasswd'])
    