/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

{% if mode == 'create' %}
SELECT 'CREATE DATABASE {{database}}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{{database}}')\gexec

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{{username}}') THEN
        ALTER USER {{username}} WITH PASSWORD '{{password}}';
    ELSE
        CREATE USER {{username}} WITH PASSWORD '{{password}}';
    END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE {{database}} to {{username}};
REVOKE CONNECT ON DATABASE {{database}} from public;
{% endif %}

{% if mode == 'delete' %}
DROP DATABASE IF EXISTS {{database}};

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{{username}}') THEN
        DROP OWNED BY {{username}};
        DROP USER {{username}};
    END IF;
END
$$;
{% endif %}
