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

import json
import unittest
from unittest.mock import Mock, patch

import openserverless.actionexecutor as executor


def action(namespace, name, annotations):
    return {
        "name": name,
        "entityType": "action",
        "namespace": namespace,
        "parameters": [],
        "annotations": annotations,
    }


class CronTenantIsolationTest(unittest.TestCase):
    def test_invalid_cron_values_are_skipped_before_parsing(self):
        for value in (None, False, 42, [], {}, "", "x" * 4097):
            with self.subTest(value=value):
                with patch.object(executor.cn.croniter, "is_valid") as is_valid, self.assertLogs(level="WARNING"):
                    result = executor.should_trigger(
                        "tenant-a", "broken", value, executor.datetime.now(), 60
                    )
                self.assertEqual(result, "no_execution")
                is_valid.assert_not_called()

    def test_malformed_actions_do_not_stop_other_tenants(self):
        actions = [
            action("tenant-a", "null-cron", [{"key": "cron", "value": None}]),
            action("tenant-a", "missing-value", [{"key": "cron"}]),
            action("tenant-b", "healthy", [{"key": "cron", "value": "* * * * *"}]),
            action("tenant-b", "one-shot", [{"key": "autoexec", "value": True}]),
        ]
        subjects = [
            {"name": "tenant-a", "uuid": "a", "key": "a-secret"},
            {"name": "tenant-b", "uuid": "b", "key": "b-secret"},
        ]
        config = {
            "scheduler.schedule": "* * * * *",
            "controller.protocol": "http",
            "controller.host": "controller",
            "controller.port": "3233",
            "couchdb.controller.user": "controller",
            "couchdb.controller.password": "secret",
        }
        db = Mock()
        db.wait_db_ready.return_value = True
        batches = {
            "whisks": [
                {"docs": actions, "bookmark": "next-actions"},
                {"docs": [], "bookmark": ""},
            ],
            "subjects": [
                {"docs": [{"namespaces": subjects}], "bookmark": "next-subjects"},
                {"docs": [], "bookmark": ""},
            ],
        }

        def find_doc(database, selector, username, password):
            self.assertEqual((username, password), ("controller", "secret"))
            self.assertIn("selector", json.loads(selector))
            return batches[database].pop(0)

        db.find_doc.side_effect = find_doc

        with (
            patch.dict(executor.os.environ, {"SCHEDULER_CONFIG": json.dumps(config)}),
            patch.object(executor.cu, "CouchDB", return_value=db),
            patch.object(executor.req, "post", return_value=Mock(status_code=202, text="")) as invoke,
            patch.object(executor.req, "put", return_value=Mock(status_code=200, text="")) as unschedule,
            self.assertLogs(level="WARNING") as logs,
        ):
            executor.start()

        self.assertTrue(any("Failed to process scheduled action" in line for line in logs.output))
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in invoke.call_args_list],
            [
                "http://controller:3233/api/v1/namespaces/tenant-b/actions/healthy?blocking=false&result=false",
                "http://controller:3233/api/v1/namespaces/tenant-b/actions/one-shot?blocking=false&result=false",
            ],
        )
        self.assertEqual(
            [call.kwargs["auth"] for call in invoke.call_args_list],
            [("b", "b-secret"), ("b", "b-secret")],
        )
        unschedule.assert_called_once()
        self.assertEqual(unschedule.call_args.kwargs["auth"], ("b", "b-secret"))


if __name__ == "__main__":
    unittest.main()
