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

import json
import unittest
from unittest.mock import Mock, call, patch

from openserverless import seaweedfs_deploy


class AnonymousS3AccessTest(unittest.TestCase):
    def test_grants_are_bucket_scoped_and_reject_invalid_names(self):
        client = seaweedfs_deploy.SeaweedfsClient.__new__(seaweedfs_deploy.SeaweedfsClient)
        client._exec_weed_command = Mock(return_value=True)
        self.assertTrue(client.add_anonymous_access(["beta-web", "alpha-web"]))
        client._exec_weed_command.assert_called_once_with(
            "s3.configure -user=anonymous -actions=Read -buckets=alpha-web,beta-web -apply")
        for buckets in ([], ["bad,bucket"], ["bad\n-command"]):
            client._exec_weed_command.reset_mock()
            with self.assertRaises(ValueError):
                client.add_anonymous_access(buckets)
            client._exec_weed_command.assert_not_called()

    def test_bucket_revocation_does_not_remove_other_public_grants(self):
        client = seaweedfs_deploy.SeaweedfsClient.__new__(seaweedfs_deploy.SeaweedfsClient)
        client._exec_weed_command = Mock(return_value=True)
        self.assertTrue(client.remove_anonymous_access("alpha-web"))
        client._exec_weed_command.assert_called_once_with(
            "s3.configure -user=anonymous -actions=Read -buckets=alpha-web -delete -apply")

    @patch.object(seaweedfs_deploy, "_configured_storage_buckets", return_value=({"alpha-web"}, {"alpha-data"}))
    def test_failed_legacy_revoke_never_adds_grants(self, buckets):
        client = Mock()
        client.delete_user.return_value = False
        with self.assertRaises(RuntimeError):
            seaweedfs_deploy.reconcile_anonymous_web_access(client)
        client.add_anonymous_access.assert_not_called()

    @patch.object(seaweedfs_deploy, "SeaweedfsClient")
    def test_failed_revoke_preserves_web_bucket_and_identity_until_retry(self, factory):
        config = Mock()
        config.get.side_effect = {
            "namespace": "alpha",
            "object-storage.data.enabled": False,
            "object-storage.route.enabled": True,
            "object-storage.route.bucket": "alpha-web",
        }.get
        client = factory.return_value
        for failure in (False, RuntimeError("S3 unavailable")):
            with self.subTest(failure=failure):
                client.reset_mock()
                client.remove_anonymous_access.side_effect = None
                client.remove_anonymous_access.return_value = False
                if isinstance(failure, Exception):
                    client.remove_anonymous_access.side_effect = failure
                with self.assertRaises(RuntimeError):
                    seaweedfs_deploy.delete_ow_storage(config)
                client.force_bucket_remove.assert_not_called()
                client.delete_user.assert_not_called()

        client.reset_mock()
        client.remove_anonymous_access.side_effect = None
        client.remove_anonymous_access.return_value = True
        client.delete_user.return_value = True
        self.assertTrue(seaweedfs_deploy.delete_ow_storage(config))
        self.assertEqual(client.mock_calls, [
            call.remove_anonymous_access("alpha-web"),
            call.force_bucket_remove("alpha-web"),
            call.delete_user("alpha"),
        ])

    @patch.object(seaweedfs_deploy, "SeaweedfsClient")
    def test_revoke_precedes_data_deletion_and_shared_bucket_is_deleted_once(self, factory):
        config = Mock()
        values = {
            "namespace": "legacy",
            "object-storage.data.enabled": True,
            "object-storage.data.bucket": "shared",
            "object-storage.route.enabled": True,
            "object-storage.route.bucket": "shared",
        }
        config.get.side_effect = values.get
        client = factory.return_value
        client.remove_anonymous_access.return_value = False
        with self.assertRaises(RuntimeError):
            seaweedfs_deploy.delete_ow_storage(config)
        client.force_bucket_remove.assert_not_called()
        client.delete_user.assert_not_called()

        client.reset_mock()
        client.remove_anonymous_access.return_value = True
        client.delete_user.return_value = True
        self.assertTrue(seaweedfs_deploy.delete_ow_storage(config))
        self.assertEqual(client.mock_calls, [
            call.remove_anonymous_access("shared"),
            call.force_bucket_remove("shared"),
            call.delete_user("legacy"),
        ])

    @patch.object(seaweedfs_deploy, "SeaweedfsClient")
    def test_failed_revoke_preserves_distinct_private_and_public_buckets(self, factory):
        config = Mock()
        config.get.side_effect = {
            "namespace": "alpha",
            "object-storage.data.enabled": True,
            "object-storage.data.bucket": "alpha-data",
            "object-storage.route.enabled": True,
            "object-storage.route.bucket": "alpha-web",
        }.get
        client = factory.return_value
        client.remove_anonymous_access.return_value = False
        with self.assertRaises(RuntimeError):
            seaweedfs_deploy.delete_ow_storage(config)
        client.force_bucket_remove.assert_not_called()
        client.delete_user.assert_not_called()

    @patch.object(seaweedfs_deploy.kube, "kubectl")
    def test_reconcile_legacy_grant_preserves_only_public_buckets(self, kubectl):
        kubectl.return_value = json.dumps({"items": [
            {"spec": {"object-storage": {"data": {"enabled": True, "bucket": "alpha-data"},
                                          "route": {"enabled": True, "bucket": "alpha-web"}}}},
            {"spec": {"object-storage": {"data": {"enabled": True, "bucket": "beta-data"},
                                          "route": {"enabled": False, "bucket": "beta-web"}}}},
        ]})
        client = Mock()
        client.delete_user.return_value = True
        client.add_anonymous_access.return_value = True
        seaweedfs_deploy.reconcile_anonymous_web_access(client)
        client.delete_user.assert_called_once_with("anonymous")
        client.add_anonymous_access.assert_called_once_with({"openserverless-web", "alpha-web"})

    @patch.object(seaweedfs_deploy.kube, "kubectl")
    def test_rejects_bucket_used_for_both_data_and_web(self, kubectl):
        kubectl.return_value = json.dumps({"items": [
            {"spec": {"object-storage": {"data": {"enabled": True, "bucket": "shared"},
                                          "route": {"enabled": True, "bucket": "shared"}}}},
        ]})
        client = Mock()
        client.delete_user.return_value = True
        client.add_anonymous_access.return_value = True
        with self.assertRaisesRegex(ValueError, "overlap"):
            seaweedfs_deploy.reconcile_anonymous_web_access(client)
        client.delete_user.assert_called_once_with("anonymous")
        client.add_anonymous_access.assert_called_once_with({"openserverless-web"})

    @patch.object(seaweedfs_deploy.SeaweedfsClient, "__init__", return_value=None)
    @patch.object(seaweedfs_deploy.kube, "kubectl")
    def test_new_route_cannot_expose_another_tenants_private_bucket(self, kubectl, client_init):
        kubectl.return_value = json.dumps({"items": [
            {"spec": {"object-storage": {"data": {"enabled": True, "bucket": "alpha-data"}}}},
        ]})
        config = Mock()
        config.get.side_effect = lambda key: {
            "namespace": "beta", "object-storage.password": "unused",
            "object-storage.route.enabled": True,
            "object-storage.route.bucket": "alpha-data",
            "object-storage.data.enabled": False,
        }.get(key)
        with self.assertRaisesRegex(ValueError, "overlap"):
            seaweedfs_deploy.create_ow_storage({}, config, Mock())
        client_init.assert_called_once_with()

    @patch.object(seaweedfs_deploy.SeaweedfsClient, "__init__", return_value=None)
    @patch.object(seaweedfs_deploy.kube, "kubectl")
    def test_new_data_cannot_reuse_public_bucket(self, kubectl, client_init):
        kubectl.return_value = json.dumps({"items": [
            {"spec": {"object-storage": {"route": {"enabled": True, "bucket": "alpha-web"}}}},
        ]})
        config = Mock()
        config.get.side_effect = lambda key: {
            "namespace": "beta", "object-storage.password": "unused",
            "object-storage.route.enabled": False,
            "object-storage.data.enabled": True,
            "object-storage.data.bucket": "alpha-web",
        }.get(key)
        with self.assertRaisesRegex(ValueError, "overlap"):
            seaweedfs_deploy.create_ow_storage({}, config, Mock())
        client_init.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
