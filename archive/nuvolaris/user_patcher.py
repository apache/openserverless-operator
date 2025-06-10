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
import logging, time
import nuvolaris.kopf_util as kopf_util
import nuvolaris.userdb_util as userdb

from nuvolaris.user_config import UserConfig
from nuvolaris.user_metadata import UserMetadata

def patch(ucfg: UserConfig, user_metadata: UserMetadata, diff, status, owner=None, name=None):
    """
    Implements the patching logic of the nuvolaris operator to handle chanages on the nuvolaris wsku 
    resources.
    """
    logging.info(status)
    what_to_do = kopf_util.detect_wsku_changes(diff)

    if len(what_to_do) == 0:
        logging.warn("*** no relevant changes identified by the user operator patcher. Skipping processing")
        return None
    
    for key in what_to_do.keys():
        logging.info(f"{key}={what_to_do[key]}")
 

    # supporting updating password and quota info
    if "password" in what_to_do:
        userdb.update_user_metadata_password(ucfg.get('namespace'), ucfg.get('password'))

    if "quota" in what_to_do:
        userdb.update_user_metadata_quota(ucfg.get('namespace'),user_metadata.get_metadata()["quota"])
