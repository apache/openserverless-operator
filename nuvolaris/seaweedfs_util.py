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
# this module wraps mc minio client using admin credentials 
# to perform various operations

import logging
import nuvolaris.config as cfg
import nuvolaris.template as ntp
import nuvolaris.util as util
import os
import nuvolaris.kube as kube
from types import NoneType
from typing import Optional

from requests.exceptions import HTTPError

import requests

class SeaweedfsSimpleException(Exception):
    def __init__(self, code: int, message: str):
        self.message = message
        self.code = code

    def __str__(self):
        return f"{self.message} ({self.code})"

class SeaweedfsUnauthorizedException(SeaweedfsSimpleException):
    def __init__(self):
        super().__init__(0, "Unauthorized")

class SeaweedfsClient:
    
    def __init__(self):
        self.filer_url = util.get_seaweedds_filer_host()
        self.pod_name = util.get_pod_name_by_selector("app=seaweedfs","{.items[?(@.metadata.labels.app == 'seaweedfs')].metadata.name}")

    def _request(self, endpoint: str, json=None, method: str = "POST"):
        headers = {
            "Content-Type": "application/json",
        }
        url = f"{self.filer_url}/{endpoint}"
        if json is None:
            json = {}
        response = requests.request(method, url, headers=headers, json=json)
        try:
            response.raise_for_status()
            res = response.json()
            if type(res) is not NoneType:
                return res
            else:
                raise SeaweedfsSimpleException(code=res.get('code'), message=res.get('message'))
        except HTTPError as e:
            if e.response.status_code == 403:
                raise SeaweedfsUnauthorizedException() 

    def _multipart_request(self, endpoint: str, files=None, method: str = "POST"):
        url = f"{self.filer_url}/{endpoint}"
        if files is None:
            files = {}
        response = requests.request(method, url,files=files)
        try:
            response.raise_for_status()
            res = response.json()
            if type(res) is not NoneType:
                return res
            else:
                raise SeaweedfsSimpleException(code=res.get('code'), message=res.get('message'))
        except HTTPError as e:
            if e.response.status_code == 403:
                raise SeaweedfsUnauthorizedException()

    def _exec_weed_command(self,command):
        logging.debug(f"executing command: {command} inside pod {self.pod_name}")
        res = kube.kubectl("exec","-it",self.pod_name,"--","/bin/sh","-c",f"echo '{command}' | weed shell")
        return res                               

    def make_bucket(self, bucket_name, quota_in_mb=None):
        """
        adds a new bucket inside the configured seaweed instance 
        """
        res = util.check(self._exec_weed_command(f"s3.bucket.create -name {bucket_name}"),"make_bucket",True)
        if quota_in_mb:
            res = util.check(self._exec_weed_command(f"s3.bucket.quota -name {bucket_name} -op=set -sizeMB={quota_in_mb}"),"make_bucket",res)
        return res

    def force_bucket_remove(self, bucket_name):
        """
        removes unconditionally a bucket
        """
        return util.check(self._exec_weed_command(f"s3.bucket.delete -name {bucket_name}"),"force_bucket_remove",True)

    def upload_folder_content(self,local_content,bucket):
        """
        uploads the given content using a local alias for the corresponding bucket
        """
        remote_file_name = os.path.basename(local_content)
        url = f"{self.filer_url}/buckets/{bucket}/{remote_file_name}"

        with open(local_content, "rb") as f:
            files = {"file": (remote_file_name, f)}
            resp = requests.post(url, files=files)

        return util.check(resp.status_code==201,"upload_folder_content",True)
    
    def add_user(self, username, access_key, secret_key,buckets,actions="Read,Write,List,Tagging,Admin"):
        """
        adds a new seaweedfs user using the filer api
        """
        command = (
            f's3.configure -user={username} -access_key={access_key} -secret_key={secret_key} '
            f'-buckets={buckets} -actions={actions} -apply'
        )
        return util.check(self._exec_weed_command(command),"add_user",True)
    
    def add_anonymous_access(self):
        """
        adds a new seaweedfs user using the filer api
        """
        command = 's3.configure -user=anonymous -actions=Read -apply'
        return util.check(self._exec_weed_command(command),"add_user",True)  

    def make_public_bucket(self, bucket_name):
        """
        assign the specified buckets to the given users
        """       
        return util.check(self._multipart_request(f"buckets/{bucket_name}?public=1", method="PUT"),"make_public_bucket",True)

    def make_private_bucket(self, bucket_name):
        """
        assign the specified buckets to the given users
        """       
        return util.check(self._multipart_request(f"buckets/{bucket_name}/?public=0", method="PUT"),"make_private_bucket",True)
    
    def delete_user(self, username):
        """
        removes a user from seaweedfs
        """
        return util.check(self._exec_weed_command(f"s3.user.delete -name {username}"),"delete_user",True)
