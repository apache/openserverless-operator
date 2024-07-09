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
import re
import common.whisk_user_generator as wsku
import common.html_response_generator as html

from base64 import b64decode
from common.github_client import GithubClient
from common.kube_api_client import KubeApiClient

class ApiError(Exception):
    pass

def build_error(message: str):
    return {
        "statusCode": 400,
        "body": message
    }

def build_response(data):    
    return {
        "statusCode": 200,
        "body": data
    }

def _is_valid_username(username):
    pat = re.compile(r"^[a-z0-9](?:[a-z0-9]{0,61}[a-z0-9])?$")
    if re.fullmatch(pat, username):
        return True
    else:
        return False

def main(args):
    """
    Action implementing the callback activated when a user subscribe to the nuv-github-app.
    This implementation will use the code parameter to retrieve access_token and refresh_token representing the user
    and will create a nuvolaris user having an openwhisk namespace and minio bucket with 100m quota.
    """
    print(args)
    
    code = args['code']
    setup_action = args['setup_action']
    installation_id = args['installation_id']
    client_id = args['client_id']
    client_secret = args['client_secret']

    try:
        github_client = GithubClient()
        kube_client = KubeApiClient(args['kube_host'],args['kube_port'],args['sa_token'],args['sa_crt'])
        
        token_data = github_client.github_code_exchange(client_id,client_secret,code)

        if token_data:
            user_data = github_client.github_user_detail(token_data['access_token'])

            if not 'login' in user_data:
                return build_error(html.generate_html_error(args['apihost'],"Nuvolaris it is not able to validate your GITHUB account. Account creation stopped."))

            username = user_data['login']
            #check that the provided github login it is compliant to nuvolaris standard
            if len(username) < 5:
                return build_error(html.generate_html_error(args['apihost'],f"Your GITHUB account {username} does not match Nuvolaris account criteria. It should be at least 5 characters."))
            
            if not _is_valid_username(username):
                return build_error(html.generate_html_error(args['apihost'],f"Your GITHUB account {username} does not match Nuvolaris account criteria. User name must consist of only lower case characters (max 61 chars)"))

            #check that there is no wsk user already existing with the same login
            exiting_whisk_user = kube_client.get_whisk_user(user_data['login'])
            if exiting_whisk_user:
                return build_error(html.generate_html_error(args['apihost'],f"There is already a {username} account on domain {args['apihost']}. Your free account could not be activated"))

            # deploys a whisk user using login and email address extracted from the GITHUB user.
            whisk_user = wsku.generate_whisk_user_yaml(username,user_data['email'])
            kube_client.create_whisk_user(whisk_user)
            
            return build_response(html.generate_html_response(args['apihost'],whisk_user,user_data))
        else:
            return build_error(html.generate_html_error(args['apihost'],"Nuvolaris it is not able to validate your GITHUB account. GITHUB code token is not valid anymore, please try to activate the nuvolaris GITHUB app again."))
    except Exception as ex:
        print(ex)

    return build_error(html.generate_html_error(args['apihost'],"Un-expected error detected attempting to setup you free account"))