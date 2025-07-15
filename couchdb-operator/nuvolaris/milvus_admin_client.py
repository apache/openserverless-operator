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
from nuvolaris.milvus_simple_client import MilvusSimpleClient as MilvusClient


class MilvusAdminClient:
    """
    Simple Milvus Client used to perform Milvus administration Tasks
    """
    def __init__(self, db_name="default"):
        self.admin_username   = cfg.get("milvus.admin.user", "MILVUS_ROOT_USER", "root")
        self.milvus_api_host  = cfg.get("milvus.host", "MILVUS_API_HOST", "nuvolaris-milvus")            
        self.milvus_api_port  = cfg.get("milvus.host", "MILVUS_API_PORT", "19530")
        self.admin_password   = cfg.get("milvus.password.root", "MILVUS_ROOT_PASSWORD", "An0therPa55")
        self.milvus_url   = f"http://{self.milvus_api_host}:{self.milvus_api_port}"
        self.milvus_admin_token = f"root:{self.admin_password}"

        #self.global_privileges_v1 = ['CreateCollection', 'DropCollection', 'DescribeCollection', 'ShowCollections',
        #                 'RenameCollection']
        self.global_privileges_v1 = []

        # references:
        # https://milvus.io/docs/privilege_group.md
        # https://milvus.io/docs/grant_privileges.md#Grant-a-privilege-or-a-privilege-group-to-a-role
        self.global_privileges_v2 = ['CollectionAdmin','DatabaseAdmin']

    def setup_user(self, username, password,database):
        """
        Creates a user into MILVUS, creates a corresponding database
        param: username
        param: password
        param: database        
        return: True if role has been successfully created
        """
        role = f"{username}_role"

        try:
            # create the user and the database
            client = MilvusClient(uri=self.milvus_url,token=self.milvus_admin_token)
            client.create_user(username, password)
            client.create_database(db_name=database)
            client.close()

            # rest of action are performed specifying the database
            client = MilvusClient(uri=self.milvus_url,token=self.milvus_admin_token, db_name=database)
            client.create_role(role_name=role,db_name=database)
            for priv in self.global_privileges_v1:
                client.grant_privilege(role_name=role, object_type='Global',  object_name='*', privilege=priv, db_name=database)
            for priv in self.global_privileges_v2:
                client.grant_privilege_v2(role_name=role, object_type='Global',  object_name='*', collection_name='*', privilege=priv, db_name=database)

            client.grant_role(user_name=username,role_name=role,db_name=database)
            client.close()
            return True
        except Exception as ex:
            logging.error(f"Error adding MILVUS user {username}",ex)
            return False

    def remove_user(self, username, database):
        """
        Removes a user from MILVUS, dropping corresponding database and roles
        param: username
        return: True if role has been successfully created
        """
        role = f"{username}_role"

        try:
            # create the user and the database
            client = MilvusClient(uri=self.milvus_url,token=self.milvus_admin_token, db_name=database)            
            collections = client.list_collections()
            for collection in collections:
                client.drop_collection(collection_name=collection)
            client.close()

            client = MilvusClient(uri=self.milvus_url,token=self.milvus_admin_token)

            for privilege in self.global_privileges_v1:
                client.revoke_privilege(role_name=role, object_type='Global', object_name='*', privilege=privilege,
                                       db_name=database)
            for privilege in self.global_privileges_v2:
                client.revoke_privilege_v2(role_name=role, object_type='Global', object_name='*', collection_name='*',
                                          privilege=privilege, db_name=database)


            client.drop_role(role_name=role,db_name=database)
            client.drop_user(user_name=username)                
            client.drop_database(db_name=database)
            client.close()
            return True
        except Exception as ex:
            logging.error(f"Error removing MILVUS user {username}",ex)
            return False
