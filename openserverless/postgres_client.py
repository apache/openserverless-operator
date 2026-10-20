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
import logging, json,  os
import pg8000.dbapi

class PostgresClient:
    
    def __init__(self, hostname, port, admin_username, password):
        self.hostname   = hostname
        self.port   = port        
        self.username   = admin_username
        self.password   = password

    def get_connection(self, db_name=None):
        """
        Builds a PGDB Connection, optionally to the specified database name.
        return: predefined connection for this PostgresDB client
        """
        kwargs = {
            "host": self.hostname,
            "port": int(self.port),
            "user": self.username,
            "password": self.password,
        }
        if db_name:
            kwargs["database"] = db_name
        return pg8000.dbapi.connect(**kwargs)

    def get_connection_to_db(self, db_name):
        """
        Builds a PGDB Connection to the specified database name
        return: predefined connection for this PostgresDB client
        """
        return self.get_connection(db_name)

    def _list_user_schemas(self, conn):
        """
        Returns the list of non system schema names visible on the given connection.
        """
        cur = conn.cursor()
        try:
            cur.execute("SELECT nspname FROM pg_catalog.pg_namespace where nspname not in ('information_schema','pg_catalog','pg_toast');")
            return [record[0] for record in cur.fetchall()]
        finally:
            cur.close()

    def query_all_pg_database_size(self):
        """
        Queries the configured Postgres database to retrieve all the existing database size in MB.
        return: a dictionary mapping the PG database name to the used space in bytes
        """
        pg_dbsize_list = {}
        conn = self.get_connection()
        try:
            logging.info("Querying all Postgres database used space")

            # Open a cursor to perform database operations
            cur = conn.cursor()
            try:
                cur.execute("SELECT datname as db_name, pg_database_size(datname) as db_usage FROM pg_database;")
                for record in cur.fetchall():
                    logging.info(record)
                    pg_dbsize_list[record[0]]=record[1]
            finally:
                cur.close()
        finally:
            conn.close()

        return pg_dbsize_list

    def revoke_access_from_db(self, pg_username, pg_db_name):
        """
        Revoke all privileges on given database from the user and update it with SELECT only privileges.
        This is done using postgres admin credentials to connect against the database to be capped
        param: pg_username
        param: pg_db_name database to revoke privileges from
        """
        conn = None
        try:
            conn = self.get_connection_to_db(pg_db_name)
            logging.info(f"Querying database {pg_db_name} existing schemas")

            pg_user_schema_names = self._list_user_schemas(conn)

            cur = conn.cursor()
            try:
                logging.info(f"executing REVOKE ALL PRIVILEGES ON DATABASE {pg_db_name} FROM {pg_username} and setting RO access")

                cur.execute(f"REVOKE ALL PRIVILEGES ON DATABASE {pg_db_name} FROM {pg_username};")

                for schema in pg_user_schema_names:
                    logging.info(f"processing revocation on schema {schema}")

                    # pg8000 uses the extended query protocol: one statement per execute()
                    for statement in [
                        f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {pg_username};",
                        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {pg_username};",
                        f"REVOKE ALL ON SCHEMA {schema} FROM {pg_username};",
                        f"REVOKE ALL ON SCHEMA {schema} FROM public;",
                        f"GRANT USAGE ON SCHEMA {schema} TO {pg_username};",
                        f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {pg_username};",
                        f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {pg_username};",
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {pg_username};",
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON SEQUENCES TO {pg_username};",
                    ]:
                        cur.execute(statement)

                cur.execute(f"GRANT CONNECT ON DATABASE {pg_db_name} TO {pg_username};")

                conn.commit()
                logging.info(f"user {pg_username} updated with RO access on {pg_db_name}")
                return True
            finally:
                cur.close()
        except Exception as ex:
            logging.error(f"failed to set postgres user {pg_username} in R/O mode. Reason: {ex}")
            return False
        finally:
            if conn:
                conn.close()

    def grant_access_on_db(self, pg_username, pg_db_name):
        """
        Grant all privileges on given database to the given and update it with ALL privileges.
        This is done using postgres admin credentials to connect against the database to be capped
        param: pg_username
        param: pg_db_name database to grant privileges from
        """
        conn = None
        try:
            conn = self.get_connection_to_db(pg_db_name)
            logging.info(f"Querying database {pg_db_name} existing schemas")

            pg_user_schema_names = self._list_user_schemas(conn)

            cur = conn.cursor()
            try:
                logging.info(f"executing GRANT ALL PRIVILEGES ON DATABASE {pg_db_name} FROM {pg_username} and setting RO access")

                cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {pg_db_name} TO {pg_username};")

                for schema in pg_user_schema_names:
                    logging.info(f"processing grant on schema {schema}")

                    # pg8000 uses the extended query protocol: one statement per execute()
                    for statement in [
                        f"GRANT ALL ON ALL TABLES IN SCHEMA {schema} TO {pg_username};",
                        f"GRANT ALL ON ALL SEQUENCES IN SCHEMA {schema} TO {pg_username};",
                        f"GRANT ALL ON SCHEMA {schema} TO {pg_username};",
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON TABLES TO {pg_username};",
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON SEQUENCES TO {pg_username};",
                    ]:
                        cur.execute(statement)

                conn.commit()
                logging.info(f"user {pg_username} updated with FULL access on {pg_db_name}")
                return True
            finally:
                cur.close()
        except Exception as ex:
            logging.error(f"failed to set FULL ACCESS to postgres user {pg_username}. Reason: {ex}")
            return False
        finally:
            if conn:
                conn.close()                               