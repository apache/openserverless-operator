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
import nuvolaris.util as util
import nuvolaris.template as ntp

class OpaqueSecret:
    _data = {}

    def __init__(self, name: str, namespace="nuvolaris"):
        self._data = {
            "namespace":namespace,
            "name":name,
            "secrets":[]
        }

    def add_secret_entry(self, key: str, value: str):
        """
        append an entry to the secret metadata with this structure {"key":key, "value":value}
        value is stored as base64 string
        """
        logging.debug(f"adding ({key}={value})")
        self._data['secrets'].append({"key":key, "value":util.b64_encode(value)})

    def dump(self):
        logging.debug(json.dumps(self._data))

    def deploy_template(self,where,tpl= "opaque-secret-tpl.yaml"):
        """
        uses the given template to render a final opaque secret template and returns the path to the template
        """
        dir = f"deploy/{where}"
        out = tgt = f"{dir}/_{self._data['name']}.yaml"
        ntp.spool_template(tpl, out, self._data)              