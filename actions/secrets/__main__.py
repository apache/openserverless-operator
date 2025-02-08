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

import json
import logging

import nuvolaris.config as cfg
import nuvolaris.couchdb_util as cu

USER_META_DBN = "users_metadata"


def fetch_user_data(db, login: str):
    logging.info(f"searching for user {login} data")
    try:
        selector = {"selector": {"login": {"$eq": login}}}
        response = db.find_doc(USER_META_DBN, json.dumps(selector))

        if response['docs']:
            docs = list(response['docs'])
            if len(docs) > 0:
                return docs[0]

        logging.warning(f"Nuvolaris metadata for user {login} not found!")
        return None
    except Exception as e:
        logging.error(f"failed to query Nuvolaris metadata for user {login}. Reason: {e}")
        return None


def save_user_data(db, user_data):
    logging.info(f"saving user_data for user {user_data['login']}")
    try:
        response = db.update_doc(USER_META_DBN, user_data)
        return response
    except Exception as e:
        logging.error(f"failed to update user_data for user {user_data['login']}. Reason: {e}")
        return False


def handle_additional_env(user_data, env) -> [dict, list, list, list]:
    """
    Merge the old env and return new metadata

    Keyword arguments:
    key -- the key where merge the old and new env
    """
    old_env = env_to_dict(user_data, "userenv")

    # Identify added keys (exist in env but not in old_env)
    added_keys = [k for k in env if k not in old_env and env[k]]

    # Identify changed keys (exist in both but have different values)
    changed_keys = [k for k in env if k in old_env and old_env[k] != env[k] and env[k]]

    # merge old env and new env
    new_env = {
        # processed then: remove keys that doesn't exists in second dict
        **{k: v for k, v in old_env.items() if k not in env or env[k]},
        # processed first: keep keys if have a value
        **{k: v for k, v in env.items() if v}
    }

    # Identify removed keys (exist in old_env but not in new_env)
    removed_keys = [k for k in old_env if k not in new_env]

    user_data["userenv"] = dict_to_env(new_env)
    return user_data, added_keys, removed_keys, changed_keys


def map_data(user_data):
    """
    Map the internal nuvolaris user_data records to the auth response
    """
    resp = {}
    resp['login'] = user_data['login']
    resp['email'] = user_data['email']

    if 'env' in user_data:
        resp['env'] = user_data['env']

    if 'userenv' in user_data:
        resp['userenv'] = user_data['userenv']

    if 'quota' in user_data:
        resp['quota'] = user_data['quota']

    return resp


def env_to_dict(user_data, key="env"):
    """
    extract env from user_data and return it as a dict

    Keyword arguments:
    key -- the key to extract the env from
    """
    body = {}
    if key in user_data:
        envs = list(user_data[key])
    else:
        envs = []

    for env in envs:
        body[env['key']] = env['value']

    return body


def dict_to_env(env):
    """
    converts an env to a key/pair suitable for user_data storage
    """
    body = []
    for key in env:
        body.append({"key": key, "value": env[key]})

    return body


def build_response(user_data: dict, added: list = None, removed: list = None, changed: list = None):
    sysenv = env_to_dict(user_data, "env")
    userenv = env_to_dict(user_data, "userenv")

    body = {"env": {}, "sysenv": {}}
    body['env'].update(sysenv)
    body['env'].update(userenv)
    body['added'] = added
    body['removed'] = removed
    body['changed'] = changed
    for key in sysenv:
        if key in userenv:
            body['sysenv'][key] = sysenv[key]

    return {
        "statusCode": 200,
        "body": body
    }


def build_error(message: str, status_code: int = 400):
    return {
        "statusCode": status_code,
        "body": message
    }


def main(args):
    cfg.clean()
    cfg.put("couchdb.host", args['couchdb_host'])
    cfg.put("couchdb.admin.user", args['couchdb_user'])
    cfg.put("couchdb.admin.password", args['couchdb_password'])

    # Access the headers
    headers = args.get('__ow_headers', {})
    # Normalize header keys to lowercase
    normalized_headers = {key.lower(): value for key, value in headers.items()}

    # Example: Get a specific header, e.g., "Authorization"
    auth_header = normalized_headers.get('authorization', None)
    if auth_header is None:
        return build_error("missing authorization header", 401)

    if 'login' in args:
        db = cu.CouchDB()
        login = args['login']
        # retrieve user data for the login
        user_data = fetch_user_data(db, login)
        added = removed = []

        if user_data:
            # convert them in a dict
            envs = env_to_dict(user_data)

            # check authorization
            if auth_header != envs['AUTH']:
                return build_error("invalid authorization header", 401)

            if 'env' in args:
                user_data, added, removed, changed = handle_additional_env(user_data, args['env'])
                if not save_user_data(db, user_data):
                    return build_error(f"unable to save metadata for user {login}")

            return build_response(map_data(user_data), added, removed, changed)
        else:
            return build_error(f"no user {login} found")
    else:
        return build_error("please provide login parameters")

