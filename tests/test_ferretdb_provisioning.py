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

"""Exercise FerretDB provisioning with the real namespace validator and renderer."""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, unquote

from openserverless import ferretdb as mongo, postgres_operator as postgres, util


class FerretDBProvisioningTests(unittest.TestCase):
    def setUp(self):
        stack=ExitStack();self.addCleanup(stack.close)
        self.values={'namespace':'fixtureuser','mongodb.database':'fixturedb','mongodb.password':'synthetic'}
        self.user=SimpleNamespace(get=self.values.get)
        self.metadata=Mock()
        stack.enter_context(patch.object(util,'get_postgres_config_data',return_value={}))
        self.primary=stack.enter_context(patch.object(util,'get_pod_name_by_selector',return_value='postgres-primary'))
        stack.enter_context(patch.object(util,'get_pod_name',side_effect=AssertionError('ambiguous pod lookup')))
        self.service=stack.enter_context(patch.object(util,'get_service',return_value={'metadata':{'name':'mongo-svc','namespace':'openserverless'}}))
        stack.enter_context(patch.object(mongo,'get_ferret_pod_name',return_value='mongo-0'))
        # Keep the actual renderer and validator; mock only filesystem and Kubernetes I/O.
        self.spool=stack.enter_context(patch.object(postgres.ntp,'spool_template',side_effect=lambda template,path,data:path))
        self.render=stack.enter_context(patch.object(postgres,'render_postgres_script',wraps=postgres.render_postgres_script))
        self.sql=stack.enter_context(patch.object(postgres,'exec_psql_command',return_value='SQL completed'))

    def assert_primary_and_names(self,mode):
        self.primary.assert_called_once_with('app=openserverless-postgres',"{.items[?(@.metadata.labels.replicationRole == 'primary')].metadata.name}")
        self.sql.assert_called_once()
        self.assertEqual(self.sql.call_args.args[0],'postgres-primary')
        self.assertEqual(len(self.render.call_args_list),2)
        for call in self.render.call_args_list:
            namespace,template,data=call.args
            self.assertEqual(namespace,'fixtureuser')
            self.assertEqual(data['database'],'fixturedb_ferretdb')
            self.assertEqual(data['username'],'fixtureuser_ferretdb')
            self.assertEqual(data['mode'],mode)

    def test_create_keeps_sql_suffix_and_uses_real_kubernetes_namespace(self):
        self.assertTrue(mongo.create_db_user(self.user,self.metadata))
        self.assert_primary_and_names('create')
        name,uri=self.metadata.add_metadata.call_args.args
        self.assertEqual(name,'MONGODB_URL')
        self.assertEqual(unquote(urlsplit(uri).username),'fixtureuser_ferretdb')
        self.assertEqual(urlsplit(uri).path,'/fixturedb_ferretdb')

    def test_delete_uses_primary_and_the_same_existing_sql_names(self):
        self.assertTrue(mongo.delete_db_user('fixtureuser','fixturedb'))
        self.assert_primary_and_names('delete')

    def test_invalid_database_is_rejected_before_rendering_or_sql(self):
        self.values['mongodb.database']='bad;name'
        self.assertFalse(mongo.create_db_user(self.user,self.metadata))
        self.render.assert_not_called();self.sql.assert_not_called()

    def test_invalid_delete_database_is_rejected_before_rendering_or_sql(self):
        self.assertFalse(mongo.delete_db_user('fixtureuser','bad;name'))
        self.render.assert_not_called();self.sql.assert_not_called()

    def test_real_namespace_validation_remains_strict(self):
        self.assertFalse(util.validate_namespace('fixtureuser_ferretdb'))
        self.values['namespace']='fixture_user'
        self.assertFalse(mongo.create_db_user(self.user,self.metadata))
        self.render.assert_not_called()
        self.sql.assert_not_called()

    def test_invalid_delete_namespace_is_rejected_before_rendering_or_sql(self):
        self.assertFalse(mongo.delete_db_user('fixture_user','fixturedb'))
        self.render.assert_not_called();self.sql.assert_not_called()

    def test_failed_sql_does_not_publish_connection_metadata(self):
        self.sql.return_value=''
        self.assertFalse(mongo.create_db_user(self.user,self.metadata))
        self.metadata.add_metadata.assert_not_called()

    def test_missing_service_does_not_report_provisioning_success(self):
        self.service.return_value=None
        self.assertFalse(mongo.create_db_user(self.user,self.metadata))
        self.metadata.add_metadata.assert_not_called()

    def test_metadata_publication_failure_does_not_report_success(self):
        self.metadata.add_metadata.side_effect=RuntimeError('synthetic metadata failure')
        self.assertFalse(mongo.create_db_user(self.user,self.metadata))


if __name__=='__main__':unittest.main()
