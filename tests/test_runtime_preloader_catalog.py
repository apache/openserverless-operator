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

"""Run the real integration assertions with catalog fixtures and Kubernetes I/O mocked."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from openserverless import config as cfg, kube, runtimes_util as runtimes, testutil, util


class RuntimePreloaderCatalogTests(unittest.TestCase):
    def catalog(self):
        def runtime(kind,prefix,name,tag,default=False):
            return {'kind':kind,'default':default,'image':{'prefix':prefix,'name':name,'tag':tag}}
        return {'runtimes':{
            'python':[runtime('python:3.12','apache','python','fixture',True),
                      runtime('python:sys','ghcr.io/example','system-python','fixture'),
                      runtime('python:3.11','apache','python','old')],
            'ruby':[runtime('ruby:2.5','openwhisk','ruby','fixture',True)],
            'unpublished':[runtime('unpublished:1','example','missing-tag','',True)]}}

    def check_integration(self,mutate=None):
        catalog=self.catalog();parse=runtimes.parse_runtimes
        def selected(value):
            result=copy.deepcopy(parse(value))
            if mutate:mutate(result['containers'])
            return result
        script=Path(__file__).parent/'kind/runtimes_preloader_test.ipy'
        with patch.object(cfg,'configure',return_value=True), \
             patch.object(testutil,'load_sample_config',return_value={}), \
             patch.object(util,'get_runtimes_json_from_config_map',return_value=json.dumps(catalog)), \
             patch.object(kube,'kubectl',side_effect=AssertionError('unexpected Kubernetes access')), \
             patch.object(runtimes,'parse_runtimes',side_effect=selected):
            exec(compile(script.read_text(),str(script),'exec'),{'get_ipython':lambda:Mock()})

    def test_mixed_registries_defaults_and_nondefault_system_runtime_are_valid(self):
        self.check_integration()

    def test_missing_default_runtime_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'must match'):
            self.check_integration(lambda rows:rows.pop(0))

    def test_missing_nondefault_system_runtime_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'must match'):
            self.check_integration(lambda rows:rows.__setitem__(slice(None),[r for r in rows if r['name']!='python-sys']))

    def test_incorrect_image_or_tag_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'must match'):
            self.check_integration(lambda rows:rows[0].update(image='apache/python:wrong-tag'))

    def test_incorrect_container_identity_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'must match'):
            self.check_integration(lambda rows:rows[0].update(name='wrong-family'))

    def test_duplicate_container_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'must match'):
            self.check_integration(lambda rows:rows.append(dict(rows[0])))

    def test_empty_result_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'Expected one or more'):
            self.check_integration(lambda rows:rows.clear())


if __name__=='__main__':unittest.main()
