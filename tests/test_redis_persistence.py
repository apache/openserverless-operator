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

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import yaml
from openserverless import redis, util
from openserverless.template import expand_template


class RedisAclPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.data = {'persistence': True, 'redis_password': 'synthetic + > password',
                     'redis_password_sha256': hashlib.sha256(b'synthetic + > password').hexdigest()}
        self.config = patch.object(redis.util, 'get_redis_config_data', return_value=self.data)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.client = MagicMock()
        self.client.__enter__.return_value = self.client
        self.client.config_get.return_value = {'aclfile': redis.ACL_FILE}

    def test_persistent_installation_bootstraps_current_acl_state(self):
        self.client.config_get.return_value = {'aclfile': ''}
        with patch.object(redis, '_write_acl_snapshot') as snapshot:
            self.assertEqual(redis._save_acl_if_configured(self.client), redis.ACL_FILE)
        snapshot.assert_called_once_with(self.client)
        self.client.config_set.assert_not_called()
        self.client.acl_save.assert_not_called()
        self.client.acl_setuser.assert_not_called()
        self.client.acl_deluser.assert_not_called()

    def test_ephemeral_installation_does_not_enable_acl_storage(self):
        self.data['persistence'] = False
        self.client.config_get.return_value = {'aclfile': ''}
        self.assertFalse(redis._save_acl_if_configured(self.client))
        self.client.config_set.assert_not_called()
        self.client.acl_save.assert_not_called()

    def test_explicit_acl_file_is_preserved(self):
        self.client.config_get.return_value = {'aclfile': '/custom/users.acl'}
        self.assertEqual(redis._save_acl_if_configured(self.client), '/custom/users.acl')
        self.client.config_set.assert_not_called()
        self.client.acl_save.assert_called_once()

    def test_revocation_is_saved_before_reporting_success(self):
        self.client.config_get.return_value = {'aclfile': redis.ACL_FILE}
        with patch.object(redis, 'admin_client', return_value=self.client):
            self.assertTrue(redis.delete_db_user('synthetic'))
        calls = self.client.method_calls
        self.assertLess(next(i for i,c in enumerate(calls) if c[0]=='acl_deluser'),
                        next(i for i,c in enumerate(calls) if c[0]=='acl_save'))

    def test_failed_revocation_save_does_not_report_success(self):
        self.client.acl_save.side_effect = redis.redislib.RedisError('synthetic failure')
        with patch.object(redis, 'admin_client', return_value=self.client):
            self.assertIsNone(redis.delete_db_user('synthetic'))

    def test_bootstrap_write_failure_closes_new_grant(self):
        self.client.config_get.return_value = {'aclfile': ''}
        self.client.acl_getuser.return_value = None
        with patch.object(redis, 'admin_client', return_value=self.client), patch.object(redis, '_write_acl_snapshot', side_effect=RuntimeError('Could not persist Redis ACL state')):
            with self.assertRaisesRegex(RuntimeError, 'Could not persist'):
                redis.provision_user('synthetic', 'synthetic-password', 'synthetic:')
        self.client.acl_deluser.assert_called_once_with('synthetic')
        self.client.config_set.assert_not_called()

    def test_quota_modes_save_without_rotating_credentials(self):
        self.client.acl_getuser.return_value = {'passwords': ['original']}
        with patch.object(redis, 'admin_client', return_value=self.client):
            for readonly in (True, False):
                self.assertTrue(redis.set_user_readonly('synthetic', 'synthetic:', readonly))
        self.assertEqual(self.client.acl_save.call_count, 2)
        for call in self.client.execute_command.call_args_list:
            self.assertFalse(any(str(arg).startswith('#') for arg in call.args))

    def existing(self, cm=None):
        self.client.config_get.return_value = {'aclfile': redis.ACL_FILE}
        if cm is None:
            cm = {'metadata': {'resourceVersion': '42'}, 'data': {'redis-conf': 'requirepass synthetic\ndir /bitnami/redis/data\n'}}
        return (patch.object(redis.kube, 'kubectl', return_value='statefulset.apps/redis'),
                patch.object(redis.kube, 'get', return_value=cm),
                patch.object(redis, 'wait_for_redis_ready'),
                patch.object(redis, 'admin_client', return_value=self.client))

    def test_existing_acl_is_saved_before_configuration_changes(self):
        first, second, third, fourth = self.existing()
        events = []
        self.client.acl_save.side_effect = lambda: events.append('save')
        with first as kubectl, second, third, fourth:
            kubectl.side_effect = lambda *a, **kw: events.append('patch' if a[0]=='patch' else 'get') or 'statefulset.apps/redis'
            redis._prepare_existing_acl_storage(self.data)
        self.assertLess(events.index('save'), events.index('patch'))
        args = kubectl.call_args
        payload = json.loads(args.kwargs['input'])
        self.assertEqual(payload['metadata']['resourceVersion'], '42')
        self.assertIn('aclfile ' + redis.ACL_FILE, payload['data']['redis-conf'])
        self.assertNotIn('spec', payload)

    def test_failed_snapshot_does_not_change_config_or_restart_redis(self):
        first, second, third, fourth = self.existing()
        self.client.acl_save.side_effect = redis.redislib.RedisError('synthetic failure')
        with first as kubectl, second, third, fourth:
            with self.assertRaises(redis.redislib.RedisError):
                redis._prepare_existing_acl_storage(self.data)
        self.assertEqual(kubectl.call_count, 1)

    def test_existing_configuration_is_idempotent(self):
        cm = {'metadata': {'resourceVersion': '42'}, 'data': {'redis-conf': 'aclfile ' + redis.ACL_FILE + '\n'}}
        first, second, third, fourth = self.existing(cm)
        with first as kubectl, second, third, fourth:
            redis._prepare_existing_acl_storage(self.data)
        self.assertEqual(kubectl.call_count, 1)
        self.client.acl_save.assert_called_once()

    def test_equivalent_quoted_acl_directives_are_preserved(self):
        for directive in ['aclfile "' + redis.ACL_FILE + '"', 'ACLFILE\t' + redis.ACL_FILE]:
            with self.subTest(directive=directive):
                cm = {'metadata': {'resourceVersion': '42'}, 'data': {'redis-conf': directive + '\n'}}
                first, second, third, fourth = self.existing(cm)
                with first as kubectl, second, third, fourth:
                    redis._prepare_existing_acl_storage(self.data)
                self.assertEqual(kubectl.call_count, 1)

    def test_conflicting_file_configuration_is_not_overwritten(self):
        cm = {'metadata': {'resourceVersion': '42'}, 'data': {'redis-conf': 'aclfile /another/users.acl\n'}}
        first, second, third, fourth = self.existing(cm)
        with first as kubectl, second, third, fourth:
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                redis._prepare_existing_acl_storage(self.data)
        self.assertEqual(kubectl.call_count, 1)

    def test_fresh_installation_does_not_connect_to_missing_redis(self):
        with patch.object(redis.kube, 'kubectl', return_value=''), patch.object(redis, 'admin_client') as admin:
            redis._prepare_existing_acl_storage(self.data)
        admin.assert_not_called()

    def test_unconfigured_acl_export_is_atomic_and_keeps_hashes_on_stdin(self):
        self.client.acl_list.return_value = ['user synthetic on #privatehash ~synthetic:* -@all +get']
        with patch.object(redis.util, 'get_pod_name', return_value='redis-0'), patch.object(redis.subprocess, 'run') as run:
            run.return_value.returncode = 0
            redis._write_acl_snapshot(self.client)
        self.assertIn(b'#privatehash', run.call_args.kwargs['input'])
        self.assertNotIn('privatehash', str(run.call_args.args))
        self.assertIn('mktemp', run.call_args.args[0][-1])
        self.assertIn('mv ', run.call_args.args[0][-1])

    def test_acl_export_failure_does_not_expose_hashes(self):
        self.client.acl_list.return_value = ['user synthetic on #privatehash ~synthetic:* -@all +get']
        with patch.object(redis.util, 'get_pod_name', return_value='redis-0'), patch.object(redis.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stderr = b'privatehash'
            with self.assertRaisesRegex(RuntimeError, '^Could not persist Redis ACL state$'):
                redis._write_acl_snapshot(self.client)

    def test_operator_resume_prepares_storage_before_system_account(self):
        with patch.object(redis, '_prepare_existing_acl_storage') as prepare, patch.object(redis, 'create_openserverless_db_user') as system:
            order = MagicMock(); order.attach_mock(prepare, 'prepare'); order.attach_mock(system, 'system')
            redis.restore_openserverless_db_user()
        self.assertEqual([c[0] for c in order.mock_calls], ['prepare', 'system'])

    def manifest(self, persistent):
        return yaml.safe_load(expand_template('redis-set.yaml', dict(self.data, persistence=persistent)))

    def test_fresh_init_is_only_used_with_a_persistent_volume(self):
        self.assertNotIn('initContainers', self.manifest(False)['spec']['template']['spec'])
        spec = self.manifest(True)['spec']['template']['spec']
        init = spec['initContainers'][0]
        self.assertEqual(init['image'], spec['containers'][0]['image'])
        self.assertEqual(init['volumeMounts'][0]['name'], 'redis-pvc')
        self.assertNotIn(self.data['redis_password'], init['command'][2])

    def test_fresh_init_keeps_existing_acl_file_and_rejects_empty_file(self):
        command = self.manifest(True)['spec']['template']['spec']['initContainers'][0]['command'][2]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'users.acl'
            command = command.replace('/bitnami/redis/data/users.acl', str(target))
            subprocess.run(['/bin/sh', '-ec', command], check=True)
            self.assertEqual(target.read_text(), 'user default on #' + self.data['redis_password_sha256'] + ' ~* &* +@all\n')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            original = 'user synthetic on #original ~synthetic:* -@all +get\n'
            target.write_text(original)
            subprocess.run(['/bin/sh', '-ec', command], check=True)
            self.assertEqual(target.read_text(), original)
            target.write_text('')
            self.assertNotEqual(subprocess.run(['/bin/sh', '-ec', command]).returncode, 0)
            self.assertEqual(target.read_text(), '')

    def test_redis_configuration_loads_acl_file_only_with_persistence(self):
        for persistent in (True, False):
            text = yaml.safe_load(expand_template('redis-conf.yaml', dict(self.data, persistence=persistent)))['data']['redis-conf']
            self.assertEqual('aclfile ' + redis.ACL_FILE in text, persistent)

    def test_system_account_mutation_is_saved(self):
        self.client.config_get.return_value = {'aclfile': redis.ACL_FILE}
        data = dict(self.data, namespace='openserverless', password='synthetic-system', prefix='openserverless:')
        with patch.object(redis, 'render_redis_script', return_value='/synthetic'), patch.object(redis.util, 'get_pod_name', return_value='redis-0'), patch.object(redis, 'exec_redis_command', return_value=True), patch.object(redis, 'admin_client', return_value=self.client), patch.object(redis.util, 'get_service', return_value=None):
            self.assertTrue(redis.create_openserverless_db_user(data))
        self.client.acl_save.assert_called_once()


if __name__ == '__main__':
    unittest.main()
