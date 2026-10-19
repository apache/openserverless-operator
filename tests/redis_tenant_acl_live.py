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

"""Explicit lab-only lifecycle validation; never run by unit-test discovery."""
import json
import logging
import secrets
import sys
from urllib.parse import unquote, urlsplit


def run():
    import redis as driver
    from openserverless import config as cfg, kube, redis as ops
    from openserverless.redis_client import RedisClient
    from openserverless.user_config import UserConfig
    from openserverless.user_metadata import UserMetadata
    cfg.configure(kube.get('wsk/controller')['spec']);cfg.detect()
    admin=ops.admin_client();name='racl'+secrets.token_hex(5);peer=name+'peer'
    prefix=name+':';other_prefix=peer+':'
    password=secrets.token_urlsafe(20);peer_password=secrets.token_urlsafe(20)
    clients=[];checks={}
    def check(label,value):
        checks[label]=bool(value)
        if not value:raise AssertionError(label)
    def client(user,secret):
        value=driver.Redis(host='redis',username=user,password=secret,decode_responses=True,socket_timeout=5)
        clients.append(value);return value
    def denied(fn):
        try:fn();return False
        except driver.exceptions.NoPermissionError:return True
    def config(user,secret):return UserConfig({'namespace':user,'password':secret,'redis':{'enabled':True,'password':secret,'prefix':user+':'}})
    def denied_admin(c,user):
        check(user+'_acl_denied',denied(c.acl_users))
        check(user+'_scan_denied',denied(lambda:c.scan(0)))
        for command in [('SCRIPT','FLUSH'),('SCRIPT','KILL'),('SCRIPT','DEBUG','NO'),('FUNCTION','FLUSH'),('ACL','SETUSER',name+'nevercreated','on','nopass','+@all','~*'),('CONFIG','GET','*'),('FLUSHALL',),('SELECT',1)]:
            result=admin.execute_command('ACL','DRYRUN',user,*command)
            check(user+'_dryrun_'+':'.join(map(str,command[:2])),'no permissions' in result.lower())
    try:
        u=config(name,password);metadata=UserMetadata(u)
        check('public_tenant_create',ops.create_db_user(u,metadata))
        fields={v['key']:v['value'] for v in metadata._data['metadata']}
        check('tenant_profile_bound',fields['REDIS_PREFIX']==prefix and unquote(urlsplit(fields['REDIS_URL']).username)==name)
        check('peer_create',ops.provision_user(peer,peer_password,other_prefix))
        a=client(name,password);b=client(peer,peer_password);key=prefix+'opsval:lifecycle';other=other_prefix+'opsval:lifecycle'
        check('own_write',a.set(key,'owned',ex=120));b.set(other,'peer',ex=120)
        check('own_lua',a.eval("return redis.call('GET',KEYS[1])",1,key)=='owned')
        check('peer_read_denied',denied(lambda:a.get(other)))
        check('peer_write_denied',denied(lambda:a.set(other,'unexpected')))
        denied_admin(a,name)
        # Reconciliation must remove a previously broad command grant.
        admin.execute_command('ACL','SETUSER',name,'+@all')
        check('public_reconcile',ops.create_db_user(u,UserMetadata(u)))
        denied_admin(a,name)
        # The legacy backport must also replace old key/channel grants and selectors.
        if not hasattr(ops,'ADMIN_USER'):
            admin.execute_command('ACL','SETUSER',name,'+@all','~*','&*','(+@all ~* &*)')
            check('stale_grants_reconciled',ops.create_db_user(u,UserMetadata(u)))
            actual=admin.acl_getuser(name)
            check('stale_selectors_removed',not actual.get('selectors'))
            check('stale_global_keys_removed',actual.get('keys')==['~'+prefix+'*'])
            check('stale_global_channels_removed',actual.get('channels')==['&'+prefix+'*'])
            check('peer_still_denied_after_reconcile',denied(lambda:a.get(other)))
        hashes=admin.acl_getuser(name)['passwords']
        q=RedisClient.__new__(RedisClient)
        check('quota_readonly',q.set_prefix_readonly(name,prefix))
        check('quota_credentials_preserved',admin.acl_getuser(name)['passwords']==hashes)
        check('quota_lua_read',a.eval("return redis.call('GET',KEYS[1])",1,key)=='owned')
        check('quota_write_denied',denied(lambda:a.set(key,'unexpected')))
        check('quota_restore',q.set_prefix_all(name,prefix))
        check('quota_write_restored',a.set(key,'restored',ex=120))
        denied_admin(a,name)
        ro_name=name+'ro';ro_cfg=config(ro_name,password)
        check('create_readonly',ops.create_db_user(ro_cfg,UserMetadata(ro_cfg),True))
        ro=client(ro_name,password)
        check('new_readonly_write_denied',denied(lambda:ro.set(ro_name+':opsval:test','unexpected')))
        check('new_readonly_lua_available',ro.eval('return 1',0)==1)
        check('delete_readonly_user',ops.delete_db_user(ro_name))
        # Pub/Sub must remain usable only in the tenant's channel prefix.
        ps=a.pubsub();ps.subscribe(prefix+'events');ps.get_message(timeout=1);a.publish(prefix+'events','synthetic')
        msg=ps.get_message(timeout=2);check('own_pubsub',msg and msg.get('data')=='synthetic');ps.close()
        check('peer_pubsub_denied',denied(lambda:a.publish(other_prefix+'events','unexpected')))
        # Spaces and ACL-looking characters are password data, never ACL syntax.
        special='synthetic +@all / @ '+secrets.token_hex(8)
        rotated=config(name,special);new_metadata=UserMetadata(rotated)
        check('public_password_rotation',ops.create_db_user(rotated,new_metadata))
        if hasattr(ops,'ADMIN_USER'):
            try:client(name,password).ping();rejected=False
            except driver.exceptions.AuthenticationError:rejected=True
            check('advanced_old_password_rejected',rejected)
            try:a.get(key);old_session_denied=False
            except (driver.exceptions.AuthenticationError,driver.exceptions.ConnectionError):old_session_denied=True
            check('advanced_old_session_revoked',old_session_denied)
        else:
            check('legacy_existing_password_preserved',client(name,password).get(key)=='restored')
            check('legacy_existing_session_preserved',a.get(key)=='restored')
        params={v['key']:v['value'] for v in new_metadata._data['metadata']}
        c=driver.Redis.from_url(params['REDIS_URL'],decode_responses=True,socket_timeout=5);clients.append(c)
        check('encoded_profile_password_works',c.get(key)=='restored')
        denied_admin(c,name)
        check('delete_tenant',ops.delete_db_user(name))
        try:client(name,special).ping();deleted=False
        except driver.exceptions.AuthenticationError:deleted=True
        check('deleted_identity_rejected',deleted)
        check('deletion_retains_existing_data',admin.get(key)=='restored')
        for bad in ['*','team:*','team: +@all','team?']:
            try:ops.provision_user(name,password,bad);rejected=False
            except ValueError:rejected=True
            check('invalid_prefix_'+str(len(checks)),rejected)
    except Exception as exc:
        checks['completed_without_unexpected_'+type(exc).__name__]=False
    finally:
        for c in clients:
            try:c.close()
            except Exception:pass
        for user in [name,peer,name+'ro']:
            try:ops.delete_db_user(user)
            except Exception:checks['cleanup_identity']=False
        for pref in [prefix,other_prefix,name+'ro:']:
            keys=list(admin.scan_iter(match=pref+'*'))
            if keys:admin.delete(*keys)
        admin.close()
    return {'checks':checks,'passed':sum(checks.values()),'failed':sum(not v for v in checks.values())}


if __name__=='__main__':
    if sys.argv[1:]!=['--lab']:
        raise SystemExit('Explicit --lab is required; synthetic identities will be created and removed.')
    logging.disable(logging.CRITICAL)
    value=run();print(json.dumps(value));raise SystemExit(bool(value['failed']))
