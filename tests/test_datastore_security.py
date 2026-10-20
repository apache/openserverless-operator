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

import base64
import json
import logging
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from openserverless import config, datastore_security as security


class SecurityTests(unittest.TestCase):
    def test_debug_logs_never_contain_values(self):
        config.clean()
        config.configure({'etcd': {'root': {'password': 'sentinel-password'}},
                          'opaque': {'url': 'http://user:sentinel-uri@internal'},
                          'state': {'spec': {'secret': 'sentinel-nested'}}})
        with self.assertLogs(level=logging.DEBUG) as logs:
            config.dump_config()
        text = '\n'.join(logs.output)
        for value in ['sentinel-password', 'sentinel-uri', 'sentinel-nested']:
            self.assertNotIn(value, text)
        self.assertIn('etcd.root.password', text)

    def test_private_apply_does_not_report_stderr_or_payload(self):
        spec = {'kind': 'Secret', 'stringData': {'password': 'sentinel'}}
        with patch.object(security.subprocess, 'run', return_value=
                          subprocess.CompletedProcess([], 1, 'sentinel', 'sentinel')):
            with self.assertRaisesRegex(RuntimeError, '^Could not apply private datastore resources$'):
                security.apply_private(spec)

    def test_secrets_do_not_reach_public_kubectl_wrapper(self):
        secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'private'}}
        service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'public'}}
        with patch.object(security, 'apply_private') as private, patch.object(security.kube, 'apply') as public:
            security.apply({'items': [secret, service]})
        self.assertEqual(private.call_args.args[0]['items'], [secret])
        self.assertEqual(public.call_args.args[0]['items'], [service])

    def test_fresh_signing_keys_are_unique_and_private(self):
        captured = []
        with patch.object(security.kube, 'kubectl', return_value=''), \
                patch.object(security, 'apply_private', side_effect=captured.append):
            security.ensure_jwt_key()
            security.ensure_jwt_key()
        keys = [base64.b64decode(x['data']['jwt-token.pem']) for x in captured]
        self.assertNotEqual(keys[0], keys[1])
        self.assertTrue(all(b'PRIVATE KEY' in key for key in keys))

    def test_existing_key_is_preserved(self):
        key = subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA',
                              '-pkeyopt', 'rsa_keygen_bits:2048'], capture_output=True, check=True).stdout
        raw = json.dumps({'data': {'jwt-token.pem': base64.b64encode(key).decode()}})
        with patch.object(security.kube, 'kubectl', return_value=raw), \
                patch.object(security, 'apply_private') as apply:
            security.ensure_jwt_key()
        apply.assert_not_called()

    def test_invalid_key_is_not_replaced(self):
        raw = json.dumps({'data': {'jwt-token.pem': base64.b64encode(b'not-a-key').decode()}})
        with patch.object(security.kube, 'kubectl', return_value=raw), \
                patch.object(security, 'apply_private') as apply:
            with self.assertRaises(RuntimeError):
                security.ensure_jwt_key()
        apply.assert_not_called()

    def test_missing_key_on_patched_cluster_is_not_reset(self):
        sts = {'spec': {'template': {'spec': {'volumes': [
            {'secret': {'secretName': 'openserverless-etcd-jwt-token-v2'}}]}}}}
        with patch.object(security.kube, 'kubectl', side_effect=['', json.dumps(sts)]), \
                patch.object(security, 'apply_private') as apply:
            with self.assertRaises(RuntimeError):
                security.ensure_jwt_key()
        apply.assert_not_called()

    def test_monitoring_does_not_allow_all_peers(self):
        rules = security.policy('milvus')['spec']['ingress']
        metrics = [rule for rule in rules if any(p['port'] == 9091 for p in rule['ports'])]
        self.assertEqual(len(metrics), 1)
        self.assertTrue(all(peer['podSelector']['matchLabels'] for peer in metrics[0]['from']))
        self.assertFalse(any('namespaceSelector' in peer for peer in metrics[0]['from']))

    def test_etcd_peer_port_is_restricted_to_members(self):
        rules = security.policy('etcd')['spec']['ingress']
        peer_rule = [rule for rule in rules if any(p['port'] == 2380 for p in rule['ports'])]
        self.assertEqual(len(peer_rule), 1)
        self.assertEqual(peer_rule[0]['from'], [{'podSelector': {'matchLabels': {
            'app.kubernetes.io/name': 'openserverless-etcd'}}}])

    def test_secret_templates_cover_full_and_slim(self):
        import jinja2
        import jinja2.meta
        import yaml
        root = Path(__file__).resolve().parents[1]
        for mode in ['base', 'slim-base']:
            path = root/'openserverless/templates'/('milvus-cfg-'+mode+'.yaml')
            source = path.read_text()
            variables = jinja2.meta.find_undeclared_variables(jinja2.Environment().parse(source))
            data = {name: 'sentinel' for name in variables}
            data.update(etcd_range=[0, 1, 2], milvus_etcd_username='etcdmilvus',
                        milvus_etcd_password='punctuation:"\\\n', milvus_max_database_num=64,
                        milvus_max_role_num=128, milvus_max_user_num=128)
            obj = yaml.safe_load(jinja2.Template(source).render(**data))
            self.assertEqual(obj['kind'], 'Secret')
            cfg = yaml.safe_load(obj['stringData']['default.yaml'])
            self.assertEqual(cfg['etcd']['auth']['userName'], 'etcdmilvus')
            self.assertEqual(cfg['etcd']['auth']['password'], data['milvus_etcd_password'])
            self.assertNotEqual(cfg['etcd']['auth']['userName'], 'root')

    def test_existing_system_user_is_verified_without_recreation(self):
        from openserverless import milvus_standalone as milvus
        data = {'openserverless_password': 'synthetic'}
        with patch.object(milvus, 'MilvusAdminClient') as admin, \
                patch('openserverless.milvus_simple_client.MilvusSimpleClient') as client, \
                patch('requests.post') as post, patch.object(milvus, '_annotate_nuv_milvus_metadata'):
            client.return_value.list_users.return_value = ['root', 'openserverless']
            post.return_value.ok = True
            post.return_value.json.return_value = {'code': 0, 'data': []}
            self.assertTrue(milvus.create_default_milvus_database(data))
            admin.return_value.setup_user.assert_not_called()
            post.return_value.json.return_value = {'code': 1800, 'message': 'denied'}
            self.assertFalse(milvus.create_default_milvus_database(data))
            admin.return_value.setup_user.assert_not_called()

    def test_scoped_account_accepts_only_its_prefix_and_exact_health_read(self):
        import contextlib
        try:
            from openserverless import etcd_admin as admin
        except ImportError:
            from openserverless import etcd as admin
        def operation(session, endpoint, path, body, **kwargs):
            if path == 'auth/user/get': return {'roles': ['probe_role']}
            if path == 'auth/role/get': return {'perm': [
                {'key': base64.b64encode(b'health').decode()},
                {'permType': 'READWRITE', 'key': base64.b64encode(b'milvus/').decode(),
                 'range_end': base64.b64encode(b'milvus0').decode()}]}
            return {}
        with patch.object(admin, '_admin', return_value=contextlib.nullcontext((object(), 'endpoint'))), \
                patch.object(admin, '_post', side_effect=operation):
            self.assertTrue(admin.create_etcd_user('probe', 'quoted:\"\n', 'milvus', readonly_keys=('health',)))
            # The existing health permission is not silently accepted for a generic user.
            self.assertFalse(admin.create_etcd_user('probe', 'quoted', 'milvus'))

    def test_reconciliation_refuses_an_existing_root_role(self):
        import contextlib
        try:
            from openserverless import etcd_admin as admin
        except ImportError:
            from openserverless import etcd as admin
        def operation(session, endpoint, path, body, **kwargs):
            if path == 'auth/user/get': return {'roles': ['root', 'probe_role']}
            if path == 'auth/role/get': return {'perm': []}
            return {}
        with patch.object(admin, '_admin', return_value=contextlib.nullcontext((object(), 'endpoint'))), \
                patch.object(admin, '_post', side_effect=operation):
            self.assertFalse(admin.create_etcd_user('probe', 'synthetic', 'milvus'))


if __name__ == '__main__':
    import jinja2.meta
    unittest.main()
