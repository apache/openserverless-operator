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

import pg8000.dbapi
import common.util as ut

from common.command_data import CommandData
from urllib.parse import urlparse, unquote
import json

class Psql():
    """
    Implementation of a Postgres Command executor. It will require
    a user_data dictionary linked to a specific user.
    """

    def __init__(self, user_data):
        self._user_data = user_data        
        self._postgres_url= ut.get_env_value(user_data,"POSTGRES_URL")        
        self.validate()

    def validate(self):
        """
        Validate that the provided user_data contains the appropriate
        metadata for being able to submit a postgres command.
        """
        if not self._postgres_url: 
            raise Exception("user does not have valid POSTGRES environment set")


    def _connect(self):
        """
        Opens a pg8000 connection from the configured postgres URL. pg8000 takes
        connection arguments as keywords, so the URL is parsed here.
        """
        url = urlparse(self._postgres_url)
        return pg8000.dbapi.connect(
            host=url.hostname,
            port=url.port or 5432,
            user=unquote(url.username) if url.username else None,
            password=unquote(url.password) if url.password else None,
            database=url.path.lstrip("/") or None,
        )

    def _query(self, input:CommandData):
        """
        Queries for matching query records and returns datas in a key, value format.
        """
        query = input.command()
        conn = self._connect()
        try:
            # Open a cursor to perform database operations
            cur = conn.cursor()
            try:
                cur.execute(query)
                columns = [desc[0] for desc in cur.description]
                result = [dict(zip(columns, row)) for row in cur.fetchall()]
                input.result(json.dumps(result, default=str))
                input.status(200)
                return input
            finally:
                cur.close()
        finally:
            conn.close()

    def _script(self, input:CommandData):
        script = input.command()
        conn = self._connect()
        try:
            # Open a cursor to perform database operations
            cur = conn.cursor()
            try:
                cur.execute(script)
                conn.commit()
                input.result(f"{cur.rowcount} row(s) affected")
                input.status(200)
                return input
            finally:
                cur.close()
        finally:
            conn.close()
            
    def _is_a_query(self, input:CommandData):        
        return 'select' in input.command().lower()

    def execute(self, input:CommandData):
        print(f"**** Psql command to execute {input.command()}")        
        try:
            if self._is_a_query(input):
                return self._query(input)
            else:
                return self._script(input)
        except Exception as e:
            input.result(f"could not execute psql command {e}")
            input.status(400)

        return input