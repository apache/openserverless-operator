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

"""Reach a private service in-cluster or through an authenticated local tunnel."""
import contextlib
import os
import re
import selectors
import subprocess
import time


@contextlib.contextmanager
def service_endpoint(service, port, namespace='openserverless'):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', service) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', namespace):
        raise ValueError('Invalid datastore service')
    if not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError('Invalid datastore port')
    if os.environ.get('KUBERNETES_SERVICE_HOST'):
        yield service, port
        return

    # Use the current kubeconfig and namespace, as with the operator's other
    # kubectl calls. Never expose a public listener or put credentials in argv.
    process = subprocess.Popen(
        ['kubectl', '-n', namespace, 'port-forward', '--address=127.0.0.1',
         'service/' + service, ':' + str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if selector.select(timeout=min(1, max(0, deadline-time.monotonic()))):
                    line = process.stdout.readline()
                    match = re.fullmatch(r'Forwarding from 127\.0\.0\.1:(\d+) -> ' + str(port), line.strip())
                    if match:
                        local_port = int(match.group(1))
                        if not 0 < local_port < 65536:
                            break
                        yield '127.0.0.1', local_port
                        return
                if process.poll() is not None:
                    break
        raise RuntimeError('Could not open the private datastore tunnel')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process.stdout.close()
