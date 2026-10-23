# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.

"""Exercise actual URL builders without Kubernetes, credentials or a database."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import urllib.parse

import yaml

ROOT = Path(__file__).resolve().parents[1]


def function(module, name, namespace):
    tree = ast.parse((ROOT / 'openserverless' / module).read_text())
    node = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), module, 'exec'), namespace)
    return namespace[name]


class FerretDBAuthenticationTests(unittest.TestCase):
    def service(self):
        return {'metadata': {'name': 'postgres-primary', 'namespace': 'fixture'},
                'spec': {'ports': [{'port': 5432}]}}

    def test_gateway_url_has_no_fallback_identity_or_fixed_database(self):
        util = SimpleNamespace(get_service_by_selector=Mock(return_value=self.service()))
        build = function('postgres_operator.py', 'get_base_postgres_url',
                         {'util': util, 'urllib': urllib, 'logging': logging})
        url = build({'postgres_openserverless_password': 'synthetic-system-password'})
        parsed = urllib.parse.urlsplit(url)
        self.assertEqual(url, 'postgresql://postgres-primary.fixture.svc.cluster.local:5432')
        self.assertIsNone(parsed.username)
        self.assertIsNone(parsed.password)
        self.assertEqual(parsed.path, '')
        util.get_service_by_selector.assert_called_once_with(
            'app=openserverless-postgres',
            "{.items[?(@.metadata.labels.replicationRole == 'primary')]}")

    def test_gateway_does_not_need_system_credentials_to_build_endpoint(self):
        build = function('postgres_operator.py', 'get_base_postgres_url',
                         {'util': SimpleNamespace(get_service_by_selector=Mock(return_value=self.service())),
                          'urllib': urllib, 'logging': logging})
        self.assertEqual(build({}), 'postgresql://postgres-primary.fixture.svc.cluster.local:5432')

    def test_no_service_does_not_invent_a_backend_endpoint(self):
        build = function('postgres_operator.py', 'get_base_postgres_url',
                         {'util': SimpleNamespace(get_service_by_selector=Mock(return_value=None)),
                          'logging': logging})
        self.assertIsNone(build({}))

    def test_base_manifest_cannot_restore_fallback_credentials(self):
        manifest = yaml.safe_load((ROOT / 'deploy/ferretdb/ferretdb-sts.yaml').read_text())
        container = manifest['spec']['template']['spec']['containers'][0]
        url = next(item['value'] for item in container['env']
                   if item['name'] == 'FERRETDB_POSTGRESQL_URL')
        parsed = urllib.parse.urlsplit(url)
        self.assertIsNone(parsed.username)
        self.assertIsNone(parsed.password)
        self.assertEqual(parsed.path, '')
        self.assertEqual(parsed.port, 5432)

    def test_tenant_metadata_keeps_explicit_plain_authentication_and_database(self):
        util = SimpleNamespace(get_service=Mock(return_value={
            'metadata': {'name': 'mongo-svc', 'namespace': 'fixture'}}))
        build = function('ferretdb.py', '_add_mdb_user_metadata',
                         {'util': util, 'get_ferret_pod_name': lambda: 'mongo-0',
                          'urllib': urllib, 'logging': logging})
        metadata = Mock()
        build(metadata, {'username': 'tenant_ferretdb', 'password': 'synthetic:p@ss',
                         'database': 'tenant_ferretdb'})
        key, url = metadata.add_metadata.call_args.args
        parsed = urllib.parse.urlsplit(url)
        self.assertEqual(key, 'MONGODB_URL')
        self.assertEqual(urllib.parse.unquote(parsed.username), 'tenant_ferretdb')
        self.assertEqual(urllib.parse.unquote(parsed.password), 'synthetic:p@ss')
        self.assertEqual(parsed.path, '/tenant_ferretdb')
        self.assertEqual(urllib.parse.parse_qs(parsed.query)['authMechanism'], ['PLAIN'])

    def test_system_client_metadata_keeps_explicit_credentials(self):
        util = SimpleNamespace(
            get_service=Mock(return_value={'metadata': {'name': 'mongo-svc', 'namespace': 'fixture'}}),
            get_postgres_config_data=Mock(return_value={
                'postgres_openserverless_user': 'openserverless',
                'postgres_openserverless_password': 'synthetic:p@ss'}))
        openwhisk = SimpleNamespace(annotate=Mock())
        build = function('ferretdb.py', 'update_system_cm_for_mdb',
                         {'util': util, 'openwhisk': openwhisk,
                          'get_ferret_pod_name': lambda: 'mongo-0',
                          'urllib': urllib, 'logging': logging})
        build({})
        annotation = openwhisk.annotate.call_args.args[0]
        parsed = urllib.parse.urlsplit(annotation.split('=', 1)[1])
        self.assertEqual(parsed.username, 'openserverless')
        self.assertEqual(urllib.parse.unquote(parsed.password), 'synthetic:p@ss')
        self.assertEqual(parsed.path, '/openserverless')
        self.assertEqual(urllib.parse.parse_qs(parsed.query)['authMechanism'], ['PLAIN'])


if __name__ == '__main__':
    unittest.main()
