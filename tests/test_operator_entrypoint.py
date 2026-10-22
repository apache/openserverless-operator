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

"""Exercise the actual Kopf entrypoint, not a clean-process operator import."""
import subprocess
import sys
import unittest


class OperatorEntrypointTest(unittest.TestCase):
    def test_kopf_loading_preserves_third_party_redis_driver(self):
        code = r'''from pathlib import Path
import shlex
from contextlib import nullcontext
from unittest.mock import patch
from kopf._cogs.helpers.loaders import preload
line = next(line for line in Path("run.sh").read_text().splitlines() if 'exec "$KOPF" run' in line)
args = shlex.split(line.split("exec ", 1)[1])
modules = [args[i+1] for i, arg in enumerate(args[:-1]) if arg == "-m"]
paths = [arg for arg in args if arg.endswith(".py")]
preload(paths=paths, modules=modules)
from openserverless import redis as operator
import redis as driver
assert operator.redislib is driver and hasattr(driver, "Redis"), "Kopf shadowed the Redis driver"
with patch.object(operator.util, "get_redis_config_data", return_value={"redis_password":"synthetic"}), patch.object(operator, "service_endpoint", return_value=nullcontext(("127.0.0.1",6379))):
    client=operator.admin_client()
    assert client.connection_pool.connection_kwargs["host"]=="127.0.0.1"
    client.close()
'''
        result=subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == "__main__":unittest.main()
