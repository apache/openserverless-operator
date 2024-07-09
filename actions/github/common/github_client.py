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
from urllib.parse import urlparse
from urllib.parse import parse_qs
import requests as req
import json
import urllib

class GithubClient:

    def __init__(self):
        self._github_base_url = "https://github.com"
        self._github_api_url = "https://api.github.com"
        print(f"Created a GithubClient instance pointing to {self._github_base_url}")

    def _parse_code_exchange_response(self, query):
        """
        Parses an URL containing query params access_token=...&expires_in=...&refresh_token=...&refresh_token_expires_in=...&scope=&token_type=bearer
        return: dictionary containing {'access_token':..,'refresh_token':...}
        """
        url = f"https://localhost/access_token?{query}"
        parsed = urlparse(url)

        token_data = {}
        token_data['access_token'] = parse_qs(parsed.query)['access_token'][0]
        token_data['refresh_token'] = parse_qs(parsed.query)['refresh_token'][0]
        token_data['expires_in'] = parse_qs(parsed.query)['expires_in'][0]
        token_data['refresh_token_expires_in'] = parse_qs(parsed.query)['refresh_token_expires_in'][0]
        token_data['token_type'] = parse_qs(parsed.query)['token_type'][0]

        return token_data

    def github_code_exchange(self, client_id,client_secret,code):
        """
        Exchange the code received from Github when the user activated the nuvolaris github app to
        retrieve user access tokens.
        return: access_token=...&expires_in=...&refresh_token=...&refresh_token_expires_in=...&scope=&token_type=bearer
        """
        url = f"{self._github_base_url}/login/oauth/access_token"
        print(f"POST request to {url}")
        headers = {'Content-Type': 'application/json'}

        try:
            response = None        
            response = req.post(f"{url}?client_id={client_id}&client_secret={client_secret}&code={code}", headers=headers)

            if (response.status_code in [200,202]):
                print(f"call to {url} succeeded with {response.status_code}. Body {response.text}")
                return self._parse_code_exchange_response(response.text)
                
            print(f"query to {url} failed with {response.status_code}. Body {response.text}")
            return None
        except Exception as ex:
            print(ex)
            return None

    def github_user_detail(self,access_token):
        """
        Exchange the code received from Github when the user activated the nuvolaris github app to
        retrieve user access tokens.
        """
        url = f"{self._github_api_url}/user"
        print(f"GET request to {url}")

        headers = {}
        headers['Accept']='application/vnd.github+json'
        headers['Authorization']= f"Bearer {access_token}"
        headers['X-GitHub-Api-Version']='2022-11-28'

        try:
            response = None       
            response = req.get(url, headers=headers)

            if (response.status_code in [200,202]):
                print(f"call to {url} succeeded with {response.status_code}. Body {response.text}")
                return json.loads(response.text)        
                
            print(f"query to {url} failed with {response.status_code}. Body {response.text}")
            return None
        except Exception as ex:
            return None        