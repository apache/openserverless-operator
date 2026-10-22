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

"""Authenticated etcd 3.5 administration without shell interpolation."""
import base64
import contextlib
import logging
import re
import requests
import openserverless.util as util
from openserverless.datastore_connection import service_endpoint

def _post(session, endpoint, path, body, allowed=()):
    for attempt in range(2):
        try:
            r=session.post(endpoint+'/v3/'+path,json=body,timeout=8)
            result=r.json()
        except (requests.RequestException,ValueError):
            raise RuntimeError('etcd administration request failed') from None
        error=result.get('error') or result.get('message','')
        credentials=getattr(session,'_ops_etcd_credentials',None)
        if attempt==0 and credentials and error in (
                'etcdserver: revision of auth store is old', 'etcdserver: invalid auth token'):
            # Auth-store updates can invalidate a JWT between admin operations.
            # Refresh only this authenticated session, never substitute root for a tenant.
            try:
                auth=session.post(endpoint+'/v3/auth/authenticate',json=credentials,timeout=8)
                token=auth.json().get('token') if auth.ok else None
            except (requests.RequestException,ValueError): token=None
            if not token: raise RuntimeError('Could not renew etcd administration authentication')
            session.headers['Authorization']=token
            continue
        if error in allowed: return result
        if not r.ok or error:
            raise RuntimeError('etcd administration request was rejected')
        return result


@contextlib.contextmanager
def _admin():
    data = util.get_etcd_config_data()
    with service_endpoint(data['name'], 2379) as (host, port), requests.Session() as session:
        endpoint = 'http://' + host + ':' + str(port)
        session.trust_env = False
        session._ops_etcd_credentials = {'name': 'root', 'password': data['root_password']}
        session.headers['Authorization'] = _post(session, endpoint, 'auth/authenticate',
                                                 session._ops_etcd_credentials)['token']
        yield session, endpoint


def create_etcd_user(username, password, prefix, readonly_keys=()):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',username) or username=='root' or not prefix.strip('/'):
        raise ValueError('Invalid etcd user or key prefix')
    try:
        with _admin() as (session,endpoint):
            result=_post(session,endpoint,'auth/user/add',{'name':username,'password':password},
                         allowed=('etcdserver: user name already exists',))
            if result.get('error') or result.get('message'):
                _post(session,endpoint,'auth/authenticate',{'name':username,'password':password})
            role=username+'_role'
            _post(session,endpoint,'auth/role/add',{'name':role},
                  allowed=('etcdserver: role name already exists',))
            key=(prefix.rstrip('/')+'/').encode()
            end=bytearray(key);end[-1]+=1
            _post(session,endpoint,'auth/role/grant',{'name':role,'perm':{'permType':'READWRITE',
                'key':base64.b64encode(key).decode(),'range_end':base64.b64encode(end).decode()}})
            for exact_key in readonly_keys:
                _post(session, endpoint, 'auth/role/grant', {'name': role, 'perm': {
                    'permType': 'READ', 'key': base64.b64encode(exact_key.encode()).decode()}})
            _post(session,endpoint,'auth/user/grant',{'user':username,'role':role})
            identity = _post(session, endpoint, 'auth/user/get', {'name': username})
            permissions = _post(session, endpoint, 'auth/role/get', {'role': role}).get('perm', [])
            expected = {'permType': 'READWRITE', 'key': base64.b64encode(key).decode(),
                        'range_end': base64.b64encode(end).decode()}
            expected_permissions = [expected] + [
                {'permType': 'READ', 'key': base64.b64encode(k.encode()).decode()}
                for k in readonly_keys]
            def normalized(values):
                return sorted((v.get('permType', 'READ'), v['key'], v.get('range_end', '')) for v in values)
            if identity.get('roles') != [role] or normalized(permissions) != normalized(expected_permissions):
                raise RuntimeError('Existing etcd account exceeds the required prefix scope')
        return True
    except RuntimeError:
        logging.error('Could not provision the etcd user')
        return False


def delete_db_user(username):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',username) or username=='root':
        raise ValueError('Invalid etcd user')
    try:
        with _admin() as (session,endpoint):
            _post(session,endpoint,'auth/user/delete',{'name':username},
                  allowed=('etcdserver: user name not found',))
            _post(session,endpoint,'auth/role/delete',{'role':username+'_role'},
                  allowed=('etcdserver: role name not found',))
        return True
    except RuntimeError:
        logging.error('Could not remove the etcd user')
        return False
