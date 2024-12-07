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
import logging
import nuvolaris.config as cfg
from pymilvus import MilvusClient

class MilvusAdminClient:
    """
    Simple Milvus Client used to perform Mivlus administration Tasks
    """
    def __init__(self, db_name="default"):
        self.admin_username   = cfg.get("milvus.admin.user", "MILVUS_ROOT_USER", "root")
        self.milvus_api_host  = cfg.get("milvus.host", "MILVUS_API_HOST", "nuvolaris-milvus")            
        self.milvus_api_port  = cfg.get("milvus.host", "MILVUS_API_PORT", "19530")
        self.admin_password   = cfg.get("milvus.password.root", "MILVUS_ROOT_PASSWORD", "An0therPa55")

        self.milvus_api_url   = f"http://{self.milvus_api_host}:{self.milvus_api_port}"
        self.client = MilvusClient(
            uri=self.milvus_api_url,
            token=f"{self.admin_username}:{self.admin_password}",
            db_name=db_name
        )

        print(f"{self.admin_username}:{self.admin_password}")

    def close_connection(self):
        try:
            self.client.close()
            logging.info("MILVUS client connection closed")
        except Exception as ex:
            logging.warning("cannot close MILVUS client connection", ex)

    def add_user(self, username, password):
        """
        adds a new MILVUS user to the predefined
        param: username
        param: password
        return: True if user has been successfully created
        """
        try:
            self.client.create_user(username, password)
            created_user = self.client.describe_user(username)
            return 'user_name' in created_user
        except Exception as ex:
            logging.error(f"Could not create milvus user {username}", ex)
            return False
        
    def add_role(self, role):
        """
        adds a new MILVUS role 
        param: role        
        return: True if role has been successfully created
        """
        try:
            self.client.create_role(role)
            created_role = self.client.describe_role(role)
            return 'role_name' in created_role
        except Exception as ex:
            logging.error(f"Could not create milvus role {role}", ex)
            return False 

    def add_default_privileges_to_role(self, role):
        """
        adds default privileges to a role
        param: role        
        return: True if role has been successfully created
        """
        try:
            self.client.grant_privilege(
                role_name=role,
                object_type='Global',  # value here can be Global, Collection or User, object type also depends on the API defined in privilegeName
                object_name='*',  # value here can be * or a specific user name if object type is 'User'
                privilege='CreateCollection'
            )

            self.client.grant_privilege(
                role_name=role,
                object_type='Collection',  # value here can be Global, Collection or User, object type also depends on the API defined in privilegeName
                object_name='*',  # value here can be * or a specific user name if object type is 'User'
                privilege='*'
            )

            return True
        except Exception as ex:
            logging.error(f"Could not create milvus role {role}", ex)
            return False 
    
    def assign_role(self, username, role):
        """
        assign a tole to a user
        param: username
        param: role        
        return: True if role has been successfully created
        """
        try:
            self.client.grant_role(user_name=username,role_name=role)
            user_detail = self.client.describe_user(username)
            return role in user_detail['roles']
        except Exception as ex:
            logging.error(f"Could not assign MILVUS role {role}", ex)
            return False 

    def setup_user(self, username, password):
        """
        Creates a user into MILVUS and assign permission on collection
        param: username
        param: role        
        return: True if role has been successfully created
        """
        role = f"{username}_role"
        self.add_user(username,password)
        self.add_role(role)
        self.add_default_privileges_to_role(role)
        self.assign_role(username, role)
