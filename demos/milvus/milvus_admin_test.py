
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

import os
from nuvolaris.milvus_simple_client import MilvusSimpleClient as MilvusClient

# for this test minioClient should see this env variable
os.environ['MILVUS_ROOT_USER']='root'
os.environ['MILVUS_API_HOST']='localhost'
os.environ['MILVUS_API_PORT']='19530'
os.environ['MILVUS_ROOT_PASSWORD']='x£VqD7G6712o'

#client = MilvusAdminClient()
#client.setup_user("userA","Afrodite1972#123")
#client.setup_user("userB","Afrodite1972#123")

client3 = MilvusClient(uri="http://localhost:19530",token="nuvolaris:Nuv0therPa55",db_name="nuvolaris")
print(client3.create_collection(collection_name="userA_collection", dimension=100))
print(client3.list_collections())

client3 = MilvusClient(uri="http://localhost:19530",token="franztt:milvusPwd",db_name="franztt")
print(client3.create_collection(collection_name="fttA_collection", dimension=100))
print(client3.create_collection(collection_name="fttB_collection", dimension=100))
print(client3.list_collections())