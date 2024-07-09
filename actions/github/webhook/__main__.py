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

from base64 import b64decode
from common.kube_api_client import KubeApiClient

NON_MANAGED_EVENT_TYPE="Weebhook received a non managed event type"

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

def parse_body_as_json(args):
    try:
        json_data = b64decode(args['__ow_body']).decode().strip()
        return json.loads(json_data)        
    except Exception as e:
        print(e)
        raise ApiError("could not parse __ow_body as base64")
    
def get_github_event_type(args):
    """
    Extract the x-gihub-event header from the input parameters.
    param: args action input parameters
    return: Empty value if no x-gihub-event header is present
    """    
    if '__ow_headers' in args:
        headers = args['__ow_headers']
        if 'x-github-event' in headers:
            return headers['x-github-event']
        
    return None 

def extract_push_event_data(push_event_as_json):
    push_data = {
                "ref":push_event_as_json['ref'],
                "repository": push_event_as_json['repository']['full_name'],
                "login": push_event_as_json['repository']['owner']['login'],
                "email": push_event_as_json['repository']['owner']['email']
    }
    
    return push_data

def _delete_whisk_user(installation, kube_client: KubeApiClient):
    """"
    Uses the login attribute to delete the corresponding WhiskUser
    """
    username = installation['account']['login']
    deleted = kube_client.delete_whisk_user(username)
    print(f"username {username} deleted? {deleted}")

def main(args):
    """
    Action implementing a webhook handler activated by github every time there is a relevant event for a specific user
    who activated the nuv-github-app.
    The body payload is passed as base64 encoded string, as this action is deployed with the RAW option.
    This action checks for the header x-github-event and handles currently only these two values: push and installation
    """
    try:
        github_webhook_event_type = get_github_event_type(args)
        github_data = parse_body_as_json(args)        

        if github_webhook_event_type not in ['push','installation']:
            print(NON_MANAGED_EVENT_TYPE)
            print(args)
            return build_response(NON_MANAGED_EVENT_TYPE)

        #1st scenario. Handle a delete action, uninstalling the corresponding user if any
        if github_webhook_event_type in ['installation'] and github_data['action'] in ['deleted']:
            print("Installation deleted webhook event received")
            kube_client = KubeApiClient(args['kube_host'],args['kube_port'],args['sa_token'],args['sa_crt'])
            _delete_whisk_user(github_data['installation'], kube_client)
            return build_response("Nuvolaris githup application removal handled")

        #2nd scenario. Handle a push on an authorized repository
        if github_webhook_event_type in ['push'] and github_data['ref']:
            print("Code push webhook event received")
            push_data = extract_push_event_data(github_data)
            print(push_data)
            return build_response("Handled a push event")

        print(args)
        return build_response("OK")
    except Exception as ex:
        print(ex)
    return build_error("KO")    