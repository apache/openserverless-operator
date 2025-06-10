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
import uuid
import random
import string

def auth_generator():
    """
    Builds an OpenWhisk Compliant AUTH token
    """
    uid = str(uuid.uuid4())
    key = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(64))

    return f"{uid}:{key}"

def pwd_generator():
    """
    Builds an OpenWhisk Compliant AUTH token
    """        
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))


def generate_whisk_user_yaml(username,email):
    """
    Return a dictionary Object representing a whisk-user.yaml to create a user wiht OW namespace and MINIO buckets
    """
    password = pwd_generator()
    minio_secret = auth_generator()
    auth = auth_generator()

    return {
        "apiVersion":"nuvolaris.org/v1",
        "kind":"WhiskUser",
        "metadata":{
            "name": username,
            "namespace": "nuvolaris"
        },
        "spec":{
            "email": email,
            "password": password,
            "namespace": username,
            "auth": auth,
            "object-storage": {
                "password": minio_secret,
                "quota": "100",
                "data":{
                    "enabled": True,
                    "bucket": f"{username}-data"
                },
                "route":{
                    "enabled": True,
                    "bucket": f"{username}-web"
                }
            }
        }
    }