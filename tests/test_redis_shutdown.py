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

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

from jinja2 import Template
import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ('deploy/redis/redis-set.yaml', 'openserverless/templates/redis-set.yaml')


@unittest.skipUnless(os.name == 'posix', 'Container shutdown requires POSIX signals')
class RedisShutdownTest(unittest.TestCase):
    def test_server_receives_sigterm_through_each_configured_entrypoint(self):
        for name in MANIFESTS:
            with self.subTest(manifest=name), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                binary = work / 'redis-server'
                ready, stopped = work / 'ready', work / 'stopped'
                binary.write_text("""#!/usr/bin/env python3
import os
from pathlib import Path
import signal
import sys

def stop(signum, frame):
    Path(os.environ['OPS_TEST_STOPPED']).write_text('SIGTERM')
    raise SystemExit(0)

assert sys.argv[1:] == ['/redis-master/redis.conf']
signal.signal(signal.SIGTERM, stop)
Path(os.environ['OPS_TEST_READY']).write_text('ready')
while True:
    signal.pause()
""")
                binary.chmod(0o755)
                document = yaml.safe_load(Template((ROOT / name).read_text()).render(
                    applypodsecurity=False, persistence=False))
                container = next(c for c in document['spec']['template']['spec']['containers']
                                 if c['name'] == 'redis')
                env = dict(os.environ, PATH=str(work) + os.pathsep + os.environ.get('PATH', ''),
                           OPS_TEST_READY=str(ready), OPS_TEST_STOPPED=str(stopped))
                process = subprocess.Popen(container['command'], env=env, start_new_session=True,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and time.monotonic() < deadline:
                        self.assertIsNone(process.poll(), 'Configured Redis entrypoint exited before readiness')
                        time.sleep(0.01)
                    self.assertTrue(ready.exists(), 'Configured Redis entrypoint did not start the server')
                    process.send_signal(signal.SIGTERM)
                    process.wait(timeout=5)
                    self.assertTrue(stopped.exists(), 'Redis server did not receive the container stop signal')
                    self.assertEqual(stopped.read_text(), 'SIGTERM')
                    self.assertEqual(process.returncode, 0)
                finally:
                    # The old shell command leaves its child alive after TERM.
                    # Reap only the isolated process group created by this test.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                    process.stderr.close()


if __name__ == '__main__':
    unittest.main()
