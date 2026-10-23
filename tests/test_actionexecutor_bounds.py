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
import threading
import time
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import yaml
from jinja2 import Template

import openserverless.actionexecutor as executor
from openserverless.couchdb_util import CouchDB


class PaginationTest(unittest.TestCase):
    def find(self, db, **kwargs):
        return executor.find_docs(db, 'whisks', '{"selector":{}}', 'u', 'p', **kwargs)

    def test_multiple_pages_and_empty_final_page(self):
        db = Mock()
        db.find_doc.side_effect = [
            {'docs': [{'_id': 'a'}], 'bookmark': 'a'},
            {'docs': [{'_id': 'b'}], 'bookmark': 'b'}, {'docs': []}]
        self.assertEqual(self.find(db), [{'_id': 'a'}, {'_id': 'b'}])
        self.assertEqual(json.loads(db.find_doc.call_args_list[1].args[1])['bookmark'], 'a')
        self.assertTrue(db.find_doc.call_args.kwargs['raise_on_error'])

    def test_invalid_pages_and_bookmarks_fail(self):
        for page in (None, [], {}, {'docs': {}}, {'docs': [1]},
                     {'docs': [{}]}, {'docs': [{}], 'bookmark': ''},
                     {'docs': [{}], 'bookmark': False}):
            with self.subTest(page=page):
                db = Mock(); db.find_doc.return_value = page
                with self.assertRaises(RuntimeError): self.find(db)

    def test_repeated_bookmark_and_cycle_fail(self):
        for bookmarks in (('a', 'a'), ('a', 'b', 'a')):
            db = Mock()
            db.find_doc.side_effect = [{'docs': [{}], 'bookmark': b} for b in bookmarks]
            with self.assertRaisesRegex(RuntimeError, 'did not advance'): self.find(db)
            self.assertEqual(db.find_doc.call_count, len(bookmarks))

    def test_forever_advancing_bookmarks_are_bounded(self):
        db = Mock()
        db.find_doc.side_effect = [{'docs': [{}], 'bookmark': str(i)} for i in range(5)]
        with patch.object(executor, 'MAX_QUERY_PAGES', 3):
            with self.assertRaisesRegex(RuntimeError, 'page limit'): self.find(db)
        self.assertEqual(db.find_doc.call_count, 3)

    def test_document_and_byte_limits_fail_without_truncation(self):
        for limit in ('MAX_QUERY_DOCUMENTS', 'MAX_QUERY_BYTES'):
            db = Mock(); db.find_doc.return_value = {'docs': [{}], 'bookmark': 'a'}
            with patch.object(executor, limit, 0):
                with self.assertRaisesRegex(RuntimeError, 'limit'): self.find(db)

    def test_expired_budget_prevents_request(self):
        db = Mock()
        with self.assertRaisesRegex(RuntimeError, 'time budget'):
            self.find(db, deadline=time.monotonic() - 1)
        db.find_doc.assert_not_called()


class RealHttpTest(unittest.TestCase):
    """Exercise real Requests timeouts/streaming through the production helpers."""
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self): self.respond()
            def do_PUT(self): self.respond()
            def respond(self):
                self.server.calls.append((self.command, self.path))
                try:
                    self.rfile.read(int(self.headers.get('Content-Length', '0')))
                    if self.server.mode == 'headers_stall': time.sleep(.3)
                    status = 500 if self.server.mode == 'error' else 200
                    self.send_response(status)
                    self.end_headers()
                    if self.server.mode == 'body_stall': time.sleep(.3)
                    body = {'docs': [], 'bookmark': ''}
                    if self.server.mode == 'large': body['padding'] = 'x' * 10000
                    self.wfile.write(json.dumps(body).encode())
                except (BrokenPipeError, ConnectionResetError): pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def setUp(self):
        self.server.calls = []; self.server.mode = 'healthy'
        self.db = CouchDB.__new__(CouchDB)
        self.db.db_base = self.url + '/openserverless_'
        self.db.db_auth = None

    def query(self, **kwargs):
        return self.db.find_doc('fixture', '{}', timeout=(.05, .05), **kwargs)

    def test_successful_bounded_response(self):
        self.assertEqual(self.query(raise_on_error=True, max_response_bytes=1024)['docs'], [])

    def test_http_error_strict_mode_is_opt_in(self):
        self.server.mode = 'error'
        self.assertIsNone(self.query())
        with self.assertRaisesRegex(RuntimeError, 'HTTP 500'):
            self.query(raise_on_error=True, max_response_bytes=1024)

    def test_headers_and_body_stalls_time_out(self):
        for mode in ('headers_stall', 'body_stall'):
            with self.subTest(mode=mode):
                self.server.mode = mode
                with self.assertRaises(requests.RequestException):
                    self.query(raise_on_error=True, max_response_bytes=1024)

    def test_oversized_response_fails(self):
        self.server.mode = 'large'
        with self.assertRaisesRegex(RuntimeError, 'response byte limit'):
            self.query(raise_on_error=True, max_response_bytes=100)

    def test_expired_body_budget_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'time budget'):
            self.query(max_response_bytes=1024, deadline=time.monotonic() - 1)

    def test_invocation_timeout_is_not_retried(self):
        self.server.mode = 'headers_stall'
        with patch.object(executor, 'HTTP_TIMEOUT', (.05, .05)):
            self.assertFalse(executor.call_ow_action(self.url, [], {'username': 'u', 'password': 'p'}))
        self.assertEqual(len(self.server.calls), 1)

    def test_invocation_does_not_wait_for_unneeded_body(self):
        self.server.mode = 'body_stall'
        with patch.object(executor, 'HTTP_TIMEOUT', (.05, .05)):
            self.assertTrue(executor.call_ow_action(self.url, [], {'username': 'u', 'password': 'p'}))
            self.assertTrue(executor.unschedule_autoexec_action(self.url, {'username': 'u', 'password': 'p'}))

    def test_rejected_post_and_put_fail_once(self):
        self.server.mode = 'error'
        self.assertFalse(executor.call_ow_action(self.url, [], {'username': 'u', 'password': 'p'}))
        self.assertFalse(executor.unschedule_autoexec_action(self.url, {'username': 'u', 'password': 'p'}))
        self.assertEqual([m for m, _ in self.server.calls], ['POST', 'PUT'])


class ExecutionTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            'scheduler.schedule': '* * * * *', 'controller.protocol': 'http',
            'controller.host': 'controller', 'controller.port': 3233,
            'couchdb.controller.user': 'u', 'couchdb.controller.password': 'p'}
        self.db = Mock(); self.db.wait_db_ready.return_value = True
        self.action = {'name': 'fixture', 'namespace': 'tenant', 'entityType': 'action',
                       'parameters': [], 'annotations': [{'key': 'autoexec', 'value': True}]}
        self.subjects = [{'name': 'tenant', 'uuid': 'u', 'key': 'p'}]

    def start(self):
        with (patch.dict(executor.os.environ, {'SCHEDULER_CONFIG': json.dumps(self.config)}),
              patch.object(executor.cu, 'CouchDB', return_value=self.db)):
            return executor.start()

    def test_readiness_failure_exits_nonzero(self):
        self.db.wait_db_ready.return_value = False
        self.assertEqual(self.start(), 1)
        self.db.find_doc.assert_not_called()

    def test_empty_catalog_succeeds(self):
        self.db.find_doc.return_value = {'docs': []}
        self.assertEqual(self.start(), 0)

    def test_later_action_page_failure_never_dispatches_partial_list(self):
        self.db.find_doc.side_effect = [{'docs': [self.action], 'bookmark': 'a'}, None]
        with patch.object(executor.req, 'post') as post:
            self.assertEqual(self.start(), 1)
        post.assert_not_called()

    def test_later_subject_page_failure_never_dispatches(self):
        self.db.find_doc.side_effect = [
            {'docs': [self.action], 'bookmark': 'a'}, {'docs': []},
            {'docs': [{'namespaces': self.subjects}], 'bookmark': 's'}, None]
        with patch.object(executor.req, 'post') as post:
            self.assertEqual(self.start(), 1)
        post.assert_not_called()

    def test_not_due_is_success_without_requests(self):
        self.action['annotations'] = [{'key': 'cron', 'value': '0 0 1 1 *'}]
        with patch.object(executor.req, 'post') as post:
            self.assertTrue(executor.handle_action('http://controller/', datetime(2026, 10, 23, 12),
                                                  60, self.action, self.subjects))
        post.assert_not_called()

    def test_missing_credentials_fail_without_request(self):
        with patch.object(executor.req, 'post') as post:
            self.assertFalse(executor.handle_action('http://controller/', datetime.now(),
                                                   60, self.action, []))
        post.assert_not_called()

    def test_autoexec_put_failure_is_reported_without_post_replay(self):
        with (patch.object(executor.req, 'post', return_value=Mock(status_code=202)) as post,
              patch.object(executor.req, 'put', return_value=Mock(status_code=500)) as put):
            self.assertFalse(executor.handle_action('http://controller/', datetime.now(),
                                                   60, self.action, self.subjects))
        self.assertEqual((post.call_count, put.call_count), (1, 1))

    def test_failed_invocation_does_not_stop_other_actions_or_replay(self):
        other = dict(self.action, name='other', annotations=[{'key': 'cron', 'value': '* * * * *'}])
        self.db.find_doc.side_effect = [
            {'docs': [self.action, other], 'bookmark': 'a'}, {'docs': []},
            {'docs': [{'namespaces': self.subjects}], 'bookmark': 's'}, {'docs': []}]
        with patch.object(executor.req, 'post', side_effect=[Mock(status_code=500), Mock(status_code=202)]) as post:
            self.assertEqual(self.start(), 1)
        self.assertEqual(post.call_count, 2)

    def test_total_budget_expiry_stops_before_next_action(self):
        with (patch.object(executor.time, 'monotonic', return_value=10),
              patch.dict(executor.os.environ, {'SCHEDULER_CONFIG': json.dumps(self.config)}),
              patch.object(executor.cu, 'CouchDB', return_value=self.db)):
            with self.assertRaisesRegex(RuntimeError, 'time budget'):
                executor.run(deadline=9)

    def test_missing_invalid_and_nonfinite_configuration_fails(self):
        for raw in ('', 'null', '{}', 'not-json'):
            with patch.dict(executor.os.environ, {'SCHEDULER_CONFIG': raw}):
                self.assertEqual(executor.start(), 1)
        for interval in (float('nan'), float('inf'), 0, -1):
            with patch.object(executor, 'from_cron_to_seconds', return_value=interval):
                self.assertEqual(self.start(), 1)


class ManifestTest(unittest.TestCase):
    def test_base_and_rendered_template_have_same_containment(self):
        root = Path(__file__).resolve().parents[1]
        paths = ('deploy/scheduler/cron.yaml', 'openserverless/templates/cron-init.yaml')
        for path in paths:
            text = Template((root / path).read_text()).render(schedule='* * * * *',
                                                            image='fixture:local', config='{}')
            spec = next(doc for doc in yaml.safe_load_all(text) if doc)['spec']
            self.assertEqual(spec['concurrencyPolicy'], 'Allow')
            job = spec['jobTemplate']['spec']
            self.assertEqual(job['activeDeadlineSeconds'], 120)
            self.assertEqual(job['backoffLimit'], 0)
            pod = job['template']['spec']
            self.assertEqual(pod['restartPolicy'], 'Never')
            self.assertIn('limits', pod['containers'][0]['resources'])


if __name__ == '__main__':
    unittest.main()
