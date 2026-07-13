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
from unittest.mock import patch

import nuvolaris.registry_deploy as registry_deploy


def registry_data(pull="auto"):
    return {
        "mode": "internal",
        "repoHostname": "auto",
        "repoPullHostname": pull,
        "repoSvcHostname": "nuvolaris-registry-svc:5000",
        "ingressEnabled": False,
    }


class RegistryEndpointTest(unittest.TestCase):
    @patch.object(registry_deploy, "assign_registry_hostname")
    @patch.object(registry_deploy.kube, "detect_kind", return_value=True)
    @patch.object(registry_deploy.cfg, "get", return_value="kind")
    def test_kind_uses_service_for_push_and_node_port_for_pull(
        self, _cfg_get, _detect_kind, _assign_hostname
    ):
        data = registry_data()

        registry_deploy.assign_registry_endpoints(data)

        self.assertEqual("nuvolaris-registry-svc:5000", data["repoPushHostname"])
        self.assertEqual("127.0.0.1:32000", data["repoPullHostname"])

    @patch.object(registry_deploy, "assign_registry_hostname")
    @patch.object(registry_deploy.kube, "detect_kind", return_value=False)
    @patch.object(registry_deploy.cfg, "get", return_value="k3s")
    def test_k3s_preserves_configured_node_reachable_host(
        self, _cfg_get, _detect_kind, _assign_hostname
    ):
        data = registry_data("192.0.2.10:32000")

        registry_deploy.assign_registry_endpoints(data)

        self.assertEqual("nuvolaris-registry-svc:5000", data["repoPushHostname"])
        self.assertEqual("192.0.2.10:32000", data["repoPullHostname"])

    @patch.object(registry_deploy, "assign_registry_hostname")
    @patch.object(registry_deploy.kube, "detect_kind", return_value=False)
    @patch.object(registry_deploy.cfg, "get", return_value="k3s")
    @patch.object(registry_deploy, "_k3s_node_registry_host", return_value="192.0.2.20:32000")
    def test_k3s_can_derive_pull_host_from_node_address(
        self, _node_host, _cfg_get, _detect_kind, _assign_hostname
    ):
        data = registry_data()

        registry_deploy.assign_registry_endpoints(data)

        self.assertEqual("192.0.2.20:32000", data["repoPullHostname"])


if __name__ == "__main__":
    unittest.main()
