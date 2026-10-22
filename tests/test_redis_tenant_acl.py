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
import unittest
from unittest.mock import MagicMock, Mock, patch

from openserverless import redis
from openserverless.redis_acl import tenant_rules
from openserverless.redis_client import RedisClient
from openserverless.user_config import UserConfig
from openserverless.user_metadata import UserMetadata
from openserverless.template import expand_template


class TenantPolicyTest(unittest.TestCase):
    def test_key_channel_and_selector_grants_are_replaced(self):
        for readonly in (True, False):
            rules=tenant_rules('team:',readonly)
            self.assertIn('-@all',rules);self.assertNotIn('+@all',rules)
            for value in ['resetkeys','resetchannels','clearselectors','~team:*','&team:*']:
                self.assertIn(value,rules)
            for value in ['+eval','+evalsha','+eval_ro','+evalsha_ro','+script|load','+script|exists']:
                self.assertIn(value,rules)
            self.assertIn('-@admin',rules);self.assertIn('-@dangerous',rules)
            if readonly:self.assertNotIn('+@write',rules)

    def test_invalid_prefixes_cannot_add_rules_or_wildcards(self):
        for prefix in ['*','team:*','team?x:','team[ab]:','team: +@all','team:\n+@all','team\\:','']:
            with self.assertRaises(ValueError):tenant_rules(prefix)

    def test_system_identities_cannot_be_managed_as_tenants(self):
        for user in ['default','openserverless','invalid user','user\non','Uppercase','under_score','x'*64]:
            with self.assertRaises(ValueError):redis._tenant_identity(user,'team:')

    def test_legacy_template_requires_explicit_internal_account(self):
        data={'namespace':'team','prefix':'team:','mode':'create','redis_password':'synthetic','password':'synthetic'}
        for mode in ['create','create_readonly','readonly','readandwrite']:
            data['mode']=mode
            self.assertNotIn('+@all',expand_template('redis_manage_user_tpl.txt',data))
            data['redis_system_account']=True
            self.assertNotIn('+@all',expand_template('redis_manage_user_tpl.txt',data))
        data.update(namespace='openserverless',mode='create',redis_system_account=True)
        self.assertIn('+@all',expand_template('redis_manage_user_tpl.txt',data))
        data['redis_system_account']=False
        self.assertNotIn('+@all',expand_template('redis_manage_user_tpl.txt',data))


class TenantLifecycleTest(unittest.TestCase):
    def test_administrator_client_keeps_the_private_endpoint_for_its_lifetime(self):
        endpoint = MagicMock()
        endpoint.__enter__.return_value = ('127.0.0.1', 41238)
        with patch.object(redis.util, 'get_redis_config_data', return_value={'redis_password': 'synthetic'}), \
                patch.object(redis, 'service_endpoint', return_value=endpoint):
            client = redis.admin_client()
            self.assertEqual(client.connection_pool.connection_kwargs['host'], '127.0.0.1')
            self.assertEqual(client.connection_pool.connection_kwargs['port'], 41238)
            endpoint.__exit__.assert_not_called()
            client.close()
            endpoint.__exit__.assert_called_once()

    def client(self):
        client=MagicMock();client.__enter__.return_value=client
        client.acl_getuser.return_value=None;client.config_get.return_value={'aclfile':''}
        return client

    def test_creation_uses_hashes_and_resets_stale_grants(self):
        client=self.client();password='synthetic with spaces > +@all'
        with patch.object(redis,'admin_client',return_value=client):
            self.assertTrue(redis.provision_user('team',password,'team:'))
        args=client.execute_command.call_args_list[0].args
        self.assertEqual(args[:5],('ACL','SETUSER','team','reset','on'))
        self.assertIn('#'+hashlib.sha256(password.encode()).hexdigest(),args)
        self.assertNotIn(password,args);self.assertNotIn('+@all',args)
        client.acl_save.assert_not_called()

    def test_reconcile_preserves_existing_0_9_0_credentials(self):
        client=self.client();client.acl_getuser.return_value={'passwords':['obsolete']}
        with patch.object(redis,'admin_client',return_value=client):redis.provision_user('team','new synthetic','team:')
        args=client.execute_command.call_args.args
        self.assertIn('#obsolete',args)
        self.assertIn('#'+hashlib.sha256(b'new synthetic').hexdigest(),args)
        self.assertNotIn('CLIENT',args)

    def test_configured_acl_storage_is_saved(self):
        client=self.client();client.config_get.return_value={'aclfile':'/synthetic/users.acl'}
        with patch.object(redis,'admin_client',return_value=client):redis.provision_user('team','synthetic','team:')
        client.acl_save.assert_called_once()

    def test_persistence_failure_closes_grant(self):
        client=self.client();client.config_get.return_value={'aclfile':'/synthetic/users.acl'}
        client.acl_save.side_effect=redis.redislib.ResponseError('synthetic failure')
        with patch.object(redis,'admin_client',return_value=client):
            with self.assertRaisesRegex(RuntimeError,'persist'):redis.provision_user('team','synthetic','team:')
        client.acl_deluser.assert_called_once_with('team')

    def test_quota_transitions_preserve_credentials_and_never_restore_all(self):
        client=self.client();client.acl_getuser.return_value={'passwords':['synthetic hash']}
        with patch.object(redis,'admin_client',return_value=client):
            for readonly in (True,False):redis.set_user_readonly('team','team:',readonly)
        for call in client.execute_command.call_args_list:
            self.assertEqual(call.args[:3],('ACL','SETUSER','team'))
            self.assertNotIn('reset',call.args);self.assertNotIn('+@all',call.args)
            self.assertFalse(any(str(arg).startswith('#') for arg in call.args[3:]))

    def test_both_quota_entrypoints_share_enforcement(self):
        obj=RedisClient.__new__(RedisClient)
        with patch.object(redis,'set_user_readonly',return_value=True) as apply:
            self.assertTrue(obj.set_prefix_readonly('team','team:'))
            self.assertTrue(obj.set_prefix_all('team','team:'))
        self.assertEqual(apply.call_args_list[0].args,('team','team:',True))
        self.assertEqual(apply.call_args_list[1].args,('team','team:',False))

    def test_create_and_reconcile_use_policy_and_preserve_metadata(self):
        for readonly in (False,True):
            cfg=UserConfig({'namespace':'team','password':'synthetic','redis':{'password':'synthetic','prefix':'team'}})
            metadata=UserMetadata(cfg)
            with patch.object(redis,'wait_for_redis_ready'),patch.object(redis,'provision_user',return_value=True) as provision,patch.object(redis,'_add_redis_user_metadata'):
                self.assertTrue(redis.create_db_user(cfg,metadata,readonly))
            provision.assert_called_once_with('team','synthetic','team:',readonly)

    def test_missing_identity_is_not_created_by_a_quota_transition(self):
        client=self.client()
        with patch.object(redis,'admin_client',return_value=client):
            with self.assertRaisesRegex(RuntimeError,'does not exist'):redis.set_user_readonly('team','team:',True)
        client.execute_command.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
