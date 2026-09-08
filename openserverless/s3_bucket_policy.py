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
import json

class S3BucketStatement:

    def __init__(self):
        """
        Simple wrapper around an S3 Bucket Policy        
        """
        self._statement = {
            "Resource": [],
            "Action":"s3:*"
        }

    def with_allow(self):
        self._statement["Effect"]="Allow"

    def with_deny(self):
        self._statement["Effect"]="Deny"        

    def with_aws_principal(self, principal_arn):
        """
        uses the given arn principal to create set an AWS "Principal":{"AWS":["arn:aws:iam:::user/franztt"]}
        """
        self._statement["Principal"]={"AWS":[principal_arn]}

    def with_all_principal(self):
        """
        uses the given arn principal to create set an AWS "Principal":"*"
        """
        self._statement["Principal"]="*"

    def with_s3_action(self, s3_action):
        """
        set an s3 action, defaults to s3:*
        """
        self._statement["Action"]=s3_action

    def with_resource(self, s3_resource_arn):
        self._statement["Resource"].append(s3_resource_arn)
        

class S3BucketPolicy:

    def __init__(self):
        """
        Simple wrapper around an S3 Bucket Policy        
        """
        self._policy = {
            "Version": "2012-10-17",
            "Statement": [                      
            ]
        }

    def with_statement(self, stm: S3BucketStatement):
        self._policy["Statement"].append(stm._statement)

    def to_json(self):
        """
        Convert it to JSON
        >>> sample_policy = S3BucketPolicy()
        >>> web_statement = S3BucketStatement()
        >>> web_statement.with_allow()
        >>> web_statement.with_aws_principal("arn:aws:iam:::user/franztt")
        >>> web_statement.with_resource("arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721/*")
        >>> web_statement.with_resource("arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721")
        >>> sample_policy.with_statement(web_statement)
        >>> sample_policy.to_json()
        '{"Version": "2012-10-17", "Statement": [{"Resource": ["arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721/*", "arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721"], "Action": "s3:*", "Effect": "Allow", "Principal": {"AWS": ["arn:aws:iam:::user/franztt"]}}]}'
        >>> pub_statement = S3BucketStatement()
        >>> pub_statement.with_allow()
        >>> pub_statement.with_all_principal()
        >>> pub_statement.with_s3_action("s3:GetObject")
        >>> pub_statement.with_resource("arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721/*")
        >>> pub_statement.with_resource("arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721")
        >>> sample_policy.with_statement(pub_statement)
        >>> sample_policy.to_json()
        '{"Version": "2012-10-17", "Statement": [{"Resource": ["arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721/*", "arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721"], "Action": "s3:*", "Effect": "Allow", "Principal": {"AWS": ["arn:aws:iam:::user/franztt"]}}, {"Resource": ["arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721/*", "arn:aws:s3:::franztt-data-5cfa001e-3679-4eed-902b-c18784c09721"], "Action": "s3:GetObject", "Effect": "Allow", "Principal": "*"}]}'
        """
        return json.dumps(self._policy)