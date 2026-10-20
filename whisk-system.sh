#!/bin/bash
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
echo CONTROLLER: "$CONTROLLER_IMAGE:$CONTROLLER_TAG"
echo OPERATOR: "$OPERATOR_IMAGE:$OPERATOR_TAG"

echo preparing openserverless system actions....

mkdir -p ${HOME}/actions/login/openserverless
mkdir -p ${HOME}/deploy/whisk-system
cp ${HOME}/openserverless/config.py ${HOME}/openserverless/couchdb_util.py ${HOME}/openserverless/bcrypt_util.py ${HOME}/actions/login/openserverless
cd ${HOME}/actions/login
rm  -f ${HOME}/deploy/whisk-system/login.zip
zip -r ${HOME}/deploy/whisk-system/login.zip *

mkdir -p ${HOME}/actions/secrets/openserverless
cp ${HOME}/openserverless/config.py ${HOME}/openserverless/couchdb_util.py ${HOME}/openserverless/user_config.py ${HOME}/actions/secrets/openserverless
cd ${HOME}/actions/secrets
rm  -f ${HOME}/deploy/whisk-system/secrets.zip
zip -r ${HOME}/deploy/whisk-system/secrets.zip *

cd ${HOME}/actions/content
mkdir -p ${HOME}/actions/content/common
cp ${HOME}/actions/common/minio_util.py ${HOME}/actions/content/common
rm  -f ${HOME}/deploy/whisk-system/content.zip
zip -r ${HOME}/deploy/whisk-system/content.zip *

mkdir -p ${HOME}/actions/devel/redis/openserverless
mkdir -p ${HOME}/actions/devel/redis/common
cp ${HOME}/openserverless/config.py ${HOME}/openserverless/couchdb_util.py ${HOME}/actions/devel/redis/openserverless
cp ${HOME}/actions/common/*.py ${HOME}/actions/devel/redis/common
cd ${HOME}/actions/devel/redis
rm  -f ${HOME}/deploy/whisk-system/redis.zip
zip -r ${HOME}/deploy/whisk-system/redis.zip *

mkdir -p ${HOME}/actions/devel/psql/openserverless
mkdir -p ${HOME}/actions/devel/psql/common
cp ${HOME}/openserverless/config.py ${HOME}/openserverless/couchdb_util.py ${HOME}/actions/devel/psql/openserverless
cp ${HOME}/actions/common/*.py ${HOME}/actions/devel/psql/common
cd ${HOME}/actions/devel/psql
rm  -f ${HOME}/deploy/whisk-system/psql.zip
zip -r ${HOME}/deploy/whisk-system/psql.zip *

mkdir -p ${HOME}/actions/devel/minio/openserverless
mkdir -p ${HOME}/actions/devel/minio/common
cp ${HOME}/openserverless/config.py ${HOME}/openserverless/couchdb_util.py ${HOME}/actions/devel/minio/openserverless
cp ${HOME}/actions/common/*.py ${HOME}/actions/devel/minio/common
cd ${HOME}/actions/devel/minio
rm  -f ${HOME}/deploy/whisk-system/minio.zip
zip -r ${HOME}/deploy/whisk-system/minio.zip *

mkdir -p ${HOME}/actions/devel/ferretdb/openserverless
mkdir -p ${HOME}/actions/devel/ferretdb/common
cp ${HOME}/openserverless/config.py ${HOME}/openserverless/couchdb_util.py ${HOME}/actions/devel/ferretdb/openserverless
cp ${HOME}/actions/common/*.py ${HOME}/actions/devel/ferretdb/common
cd ${HOME}/actions/devel/ferretdb
rm  -f ${HOME}/deploy/whisk-system/ferretdb.zip
zip -r ${HOME}/deploy/whisk-system/ferretdb.zip *

mkdir -p ${HOME}/actions/devel/download/openserverless
mkdir -p ${HOME}/actions/devel/download/common
cp ${HOME}/openserverless/config.py ${HOME}/openserverless/couchdb_util.py ${HOME}/actions/devel/download/openserverless
cp ${HOME}/actions/common/*.py ${HOME}/actions/devel/download/common
cd ${HOME}/actions/devel/download
rm  -f ${HOME}/deploy/whisk-system/devel_download.zip
zip -r ${HOME}/deploy/whisk-system/devel_download.zip *

mkdir -p ${HOME}/actions/devel/upload/openserverless
mkdir -p ${HOME}/actions/devel/upload/common
cp ${HOME}/openserverless/config.py ${HOME}/openserverless/couchdb_util.py ${HOME}/actions/devel/upload/openserverless
cp ${HOME}/actions/common/*.py ${HOME}/actions/devel/upload/common
cd ${HOME}/actions/devel/upload
rm  -f ${HOME}/deploy/whisk-system/devel_upload.zip
zip -r ${HOME}/deploy/whisk-system/devel_upload.zip *
