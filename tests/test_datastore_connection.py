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


import io
import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from openserverless import datastore_connection as connection


class PrivateServiceConnectionTests(unittest.TestCase):
    def process(self, line='Forwarding from 127.0.0.1:41237 -> 2379\n'):
        process = MagicMock()
        process.stdout = io.StringIO(line)
        process.poll.return_value = None
        return process

    def test_in_cluster_uses_service_without_starting_a_tunnel(self):
        with patch.dict(os.environ, {'KUBERNETES_SERVICE_HOST': 'cluster'}, clear=True), \
                patch.object(connection.subprocess, 'Popen') as spawn:
            with connection.service_endpoint('openserverless-etcd', 2379) as endpoint:
                self.assertEqual(endpoint, ('openserverless-etcd', 2379))
        spawn.assert_not_called()
    def test_external_tunnel_binds_only_loopback_and_closes(self):
        process = self.process()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(connection.subprocess, 'Popen', return_value=process) as spawn, \
                patch.object(connection.selectors, 'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value.select.return_value = [object()]
            with connection.service_endpoint('openserverless-etcd', 2379) as endpoint:
                self.assertEqual(endpoint, ('127.0.0.1', 41237))
            command = spawn.call_args.args[0]
            self.assertIn('--address=127.0.0.1', command)
            self.assertIn('service/openserverless-etcd', command)
            self.assertIn(':2379', command)
            self.assertFalse(any('password' in item for item in command))
        process.terminate.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_consumer_error_still_closes_tunnel(self):
        process = self.process()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(connection.subprocess, 'Popen', return_value=process), \
                patch.object(connection.selectors, 'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value.select.return_value = [object()]
            with self.assertRaisesRegex(ValueError, 'consumer failed'):
                with connection.service_endpoint('openserverless-etcd', 2379):
                    raise ValueError('consumer failed')
        process.terminate.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_failed_tunnel_does_not_report_process_output(self):
        process = self.process('credential-bearing diagnostic must stay private\n')
        process.poll.return_value = 1
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(connection.subprocess, 'Popen', return_value=process), \
                patch.object(connection.selectors, 'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value.select.return_value = [object()]
            with self.assertRaisesRegex(RuntimeError, '^Could not open the private datastore tunnel$'):
                with connection.service_endpoint('openserverless-etcd', 2379):
                    self.fail('A failed tunnel must not yield an endpoint')

    def test_a_stuck_tunnel_is_killed_during_cleanup(self):
        process = self.process()
        process.wait.side_effect = [subprocess.TimeoutExpired('kubectl', 5), None]
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(connection.subprocess, 'Popen', return_value=process), \
                patch.object(connection.selectors, 'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value.select.return_value = [object()]
            with connection.service_endpoint('openserverless-etcd', 2379):
                pass
        process.kill.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_invalid_targets_cannot_be_kubectl_options(self):
        with patch.object(connection.subprocess, 'Popen') as spawn:
            for service, port in [('--all-namespaces', 2379), ('service;command', 2379),
                                  ('redis', 0), ('redis', 65536)]:
                with self.assertRaises(ValueError):
                    with connection.service_endpoint(service, port):
                        self.fail('Invalid target accepted')
        spawn.assert_not_called()
