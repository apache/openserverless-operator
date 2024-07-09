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
import logging, json,  os

import nuvolaris.redis as redis
import nuvolaris.util as util
import nuvolaris.kube as kube
import nuvolaris.template as ntp

class RedisClient:
    """
    Simple Redis Client Used by the quota cheker
    """

    def __init__(self, redis_password: str):
        redis.wait_for_redis_ready()
        self._data = {
            "name": "redis",
            "container": "redis",
            "redis_password": redis_password
        }
        self.prepare_scripts()

    def prepare_scripts(self):
        """
        Prepare the initial script to be used to interact with REDIS
        """
        logging.info("***** uploading REDIS quota scripts *****")
        self._data['path_to_lua_script']= self.render_script("redis_quota_checker.lua",self._data)
        self._data['path_to_script'] = self.render_script("redis_quota_checker.sh",self._data)
        self._data['pod_name'] = util.get_pod_name("{.items[?(@.metadata.labels.name == 'redis')].metadata.name}")

        kube.kubectl("cp",self._data['path_to_lua_script'],f"{self._data['pod_name']}:{self._data['path_to_lua_script']}")
        kube.kubectl("cp",self._data['path_to_script'],f"{self._data['pod_name']}:{self._data['path_to_script']}")
        kube.kubectl("exec","-it",self._data['pod_name'],"--","/bin/bash","-c",f"chmod 700 {self._data['path_to_script']}")
        logging.info("***** uploading REDIS quota scripts completed *****")


    def render_script(self, template,data):
        """
        uses the given template to render a redis-cli script to be executed.
        """  
        out = f"/tmp/__{template}"
        file = ntp.spool_template(template, out, data)
        return os.path.abspath(file)      

    def exec_lua_script(self, prefix):
        """
        Eecute a Lua script
        """
        logging.info("executing script %s on pod %s", self._data['path_to_script'], self._data['pod_name'])
        res = kube.kubectl("exec","-it",self._data['pod_name'],"--","/bin/bash","-c",f"{self._data['path_to_script']} {prefix}")
        return res 

    def calculate_prefix_allocated_size(self, prefix):
        """
        Evaluate a LUA script to calculate the prefix allocated size in bytes
        """
        logging.info("checking redis/valkey allocated size with prefix %s", prefix)

        try:                           
            prefix_allocated_size = self.exec_lua_script(prefix)
            logging.info("prefix %s calculated size=%s", prefix, prefix_allocated_size)
            if "(integer)" in prefix_allocated_size:
                return int(prefix_allocated_size.replace("(integer)",""))
            else:
                return int(prefix_allocated_size)
        except Exception as e:
            logging.error("failed to check redis/valkey allocated size for prefix %s %s", prefix, e)
            return None

    def set_prefix_readonly(self, namespace, prefix):
        """
        Submit the redis script to revoke namespace write rights on the given prefix
        """        
        self._data['prefix']=prefix
        self._data['namespace']=namespace
        self._data['mode']='readonly'
        logging.info("setting redis/valkey %s with @READ ACL", prefix)

        try:
            redis.wait_for_redis_ready()
            path_to_script = redis.render_redis_script(namespace,"redis_manage_user_tpl.txt",self._data)
            pod_name = util.get_pod_name("{.items[?(@.metadata.labels.name == 'redis')].metadata.name}")

            if(pod_name):
                res = redis.exec_redis_command(pod_name,path_to_script)              
                return res
            return None
        except Exception as e:
            logging.error("failed to set redis/valkey %s with @READ ACL: %s", prefix, e)
            return None 

    def set_prefix_all(self, namespace, prefix):
        """
        Submit the redis script to re-enable namespace write rights on the given prefix
        """
        
        self._data['prefix']=prefix
        self._data['namespace']=namespace
        self._data['mode']='readandwrite'
        logging.info("setting redis/valkey %s with +@ALL ACL", prefix)

        try:
            redis.wait_for_redis_ready()
            path_to_script = redis.render_redis_script(namespace,"redis_manage_user_tpl.txt",self._data)
            pod_name = util.get_pod_name("{.items[?(@.metadata.labels.name == 'redis')].metadata.name}")

            if(pod_name):
                res = redis.exec_redis_command(pod_name,path_to_script)              
                return res
            return None
        except Exception as e:
            logging.error("failed to set redis/valkey %s with +@ALL ACL: %s", prefix, e)
            return None