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
import itertools
import unittest
from pathlib import Path
import jinja2
import yaml

class AlertmanagerConfigTests(unittest.TestCase):
    def test_receiver_exists_for_every_notification_combination(self):
        template = jinja2.Template((Path(__file__).resolve().parents[1] / "openserverless/templates/alert-manager-02-cm.yaml").read_text())
        for slack, gmail, slack_default, gmail_default in itertools.product([False, True], repeat=4):
            with self.subTest(slack=slack, gmail=gmail, slack_default=slack_default, gmail_default=gmail_default):
                rendered = template.render(slack=slack, gmail=gmail, slack_default=slack_default, gmail_default=gmail_default,
                    slack_api_url="https://example.test", slack_channel_name="#test", email_recipients="test@example.test",
                    email_from="test@example.test", gmail_username="test@example.test", gmail_password="test")
                config = yaml.safe_load(yaml.safe_load(rendered)["data"]["alertmanager.yml"])
                names = {r["name"] for r in config["receivers"]}
                expected = "email-receiver" if gmail and gmail_default else "slack-notifications" if slack and slack_default else "discard"
                self.assertEqual(config["route"]["receiver"], expected)
                for route in config["route"].get("routes", []): self.assertIn(route["receiver"], names)
                discard = next(r for r in config["receivers"] if r["name"] == "discard")
                self.assertEqual(discard, {"name": "discard"})
