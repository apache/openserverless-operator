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

import unittest
from unittest.mock import Mock, patch
from openserverless import couchdb
from openserverless.couchdb_util import CouchDB

class MetadataSecurityTest(unittest.TestCase):
    @patch.object(couchdb.cfg, "get", return_value="configured_admin")
    def test_new_and_existing_database_are_restricted_without_recreation(self, config):
        for exists in (False, True):
            with self.subTest(exists=exists):
                db = Mock()
                db.check_db.return_value = exists
                self.assertTrue(couchdb.init_users_metadata(db))
                db.add_role.assert_called_once_with("users_metadata", ["configured_admin"])
                if exists:
                    db.create_db.assert_not_called()
                else:
                    db.create_db.assert_called_once_with("users_metadata")
                db.delete_db.assert_not_called()

    @patch.object(couchdb.cfg, "get", return_value="configured_admin")
    def test_acl_failure_is_not_reported_as_success(self, config):
        db = Mock()
        db.check_db.return_value = True
        db.add_role.return_value = False
        self.assertFalse(couchdb.init_users_metadata(db))

    def test_security_document_uses_explicit_members_without_public_roles(self):
        db = CouchDB.__new__(CouchDB)
        db.db_base = "http://couchdb:5984/openserverless_"
        db.db_session = Mock()
        db.db_session.put.return_value.status_code = 200
        self.assertTrue(db.add_role("users_metadata", ["configured_admin"]))
        db.db_session.put.assert_called_once_with(
            "http://couchdb:5984/openserverless_users_metadata/_security",
            json={"admins":{"names":[],"roles":[]},
                  "members":{"names":["configured_admin"],"roles":[]}})
