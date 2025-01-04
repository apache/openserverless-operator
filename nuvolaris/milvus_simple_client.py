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
from types import NoneType
from typing import Optional

import requests


class MilvusSimpleException(Exception):
    def __init__(self, code: int, message: str):
        self.message = message
        self.code = code

    def __str__(self):
        return f"{self.message} ({self.code})"


class MilvusSimpleClient:

    def __init__(self, uri: str, token: str, db_name: str = None):
        self.milvus_url = uri
        self.token = token
        self.db_name = db_name

    def _request(self, endpoint: str, json=None, method: str = "POST", api_level="v2"):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        }
        url = f"{self.milvus_url}/{api_level}/vectordb/{endpoint}"
        if json is None:
            json = {}
        response = requests.request(method, url, headers=headers, json=json)
        response.raise_for_status()
        res = response.json()
        if type(res.get('data')) is not NoneType:
            return res['data']
        else:
            raise MilvusSimpleException(code=res.get('code'), message=res.get('message'))

    def close(self):
        pass

    # User operations
    def create_user(self, user_name: str, password: str):
        payload = {"userName": user_name, "password": password}
        return self._request("users/create", json=payload)

    def describe_user(self, user_name: str):
        payload = {"userName": user_name}
        return self._request(f"users/describe", json=payload)

    def update_password(self, user_name: str, old_password: str, new_password: str):
        payload = {"userName": user_name, "password": old_password, "newPassword": new_password}
        return self._request("users/update_password", json=payload)

    def drop_user(self, user_name: str):
        payload = {"userName": user_name}
        return self._request(f"users/drop", json=payload)

    def list_users(self):
        return self._request("users/list")

    def grant_role(self, role_name: str, user_name: str, db_name: Optional[str] = None):
        payload = {"roleName": role_name, "userName": user_name}
        if db_name is not None:
            payload["dbName"] = db_name
        return self._request(f"users/grant_role", json=payload)

    def revoke_role(self, role_name: str, user_name: str, db_name: Optional[str] = None):
        payload = {"roleName": role_name, "userName": user_name}
        if db_name is not None:
            payload["dbName"] = db_name
        return self._request(f"users/revoke_role", json=payload)

    # Database operations
    def alter_database(self, db_name: str, properties: dict):
        payload = {"dbName": db_name, "properties": properties}
        return self._request("databases/alter", json=payload)

    def create_database(self, db_name: str, properties: Optional[dict] = None, **kwargs):
        payload = {"dbName": db_name}
        if properties is not None:
            payload["properties"] = properties

        for k, v in kwargs.items():
            payload[k] = v

        return self._request("databases/create", json=payload)

    def describe_database(self, db_name: str):
        payload = {"dbName": db_name}
        return self._request(f"databases/describe", json=payload)

    def drop_database(self, db_name: str):
        payload = {"dbName": db_name}
        return self._request(f"databases/drop", json=payload)

    def list_databases(self):
        return self._request(f"databases/list")

    # Role operations
    def create_role(self, role_name: str, db_name: Optional[str] = None):
        payload = {"roleName": role_name}
        if db_name is not None:
            payload["dbName"] = db_name

        return self._request("roles/create", json=payload)

    def drop_role(self, role_name: str, db_name: Optional[str] = None):
        payload = {"roleName": role_name}
        if db_name is not None:
            payload["dbName"] = db_name
        return self._request(f"roles/drop", json=payload)

    def list_roles(self, db_name: Optional[str] = None):
        payload = {}
        if db_name is not None:
            payload["dbName"] = db_name
        return self._request(f"roles/list", json=payload)

    def describe_role(self, role_name: str, db_name: Optional[str] = None):
        payload = {"roleName": role_name}
        if db_name is not None:
            payload["dbName"] = db_name
        return self._request(f"roles/describe", json=payload)

    def grant_privilege(self, role_name: str, object_type: str, object_name: str, privilege: str, db_name: Optional[str] = None):
        payload = {
            "roleName": role_name,
            "objectType": object_type,
            "objectName": object_name,
            "privilege": privilege
        }
        if db_name is not None:
            payload["dbName"] = db_name
        return self._request(f"roles/grant_privilege", json=payload)

    def revoke_privilege(self, role_name: str, object_type: str, object_name: str, privilege: str, db_name: Optional[str] = None):
        payload = {
            "roleName": role_name,
            "objectType": object_type,
            "objectName": object_name,
            "privilege": privilege
        }
        if db_name is not None:
            payload["dbName"] = db_name
        return self._request(f"roles/revoke_privilege", json=payload)

    # Collection operations

    def create_collection(self,
                          collection_name: str,
                          db_name: Optional[str] = None,
                          dimension: Optional[int] = None,
                          primary_field_name: str = "id",  # default is "id"
                          id_type: str = "Int64",  # or "string",
                          vector_field_name: str = "vector",  # default is  "vector"
                          metric_type: str = "COSINE",
                          auto_id: bool = False,
                          ):
        if db_name is None:
            db_name = self.db_name

        payload = {
            "dbName": db_name,
            "collectionName": collection_name,
            "dimension": dimension,
            "metricType": metric_type,
            "idType": id_type,
            "autoID": auto_id,
            "primaryFieldName": primary_field_name,
            "vectorFieldName": vector_field_name,
        }
        return self._request(f"collections/create", json=payload)

    def drop_collection(self, collection_name: str, db_name: Optional[str] = None, **kwargs):
        payload = {
            "collectionName": collection_name,
        }
        if db_name is not None:
            payload["dbName"] = db_name
        else:
            payload["dbName"] = self.db_name

        for k, v in kwargs.items():
            payload[k] = v

        return self._request(f"collections/drop", json=payload)

    def list_collections(self, db_name: Optional[str] = None, **kwargs):
        payload = {
        }
        if db_name is not None:
            payload["dbName"] = db_name
        else:
            payload["dbName"] = self.db_name

        for k, v in kwargs.items():
            payload[k] = v

        return self._request(f"collections/list", json=payload)
