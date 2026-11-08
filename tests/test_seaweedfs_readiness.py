# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.

import contextlib
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib3.exceptions import ConnectTimeoutError, ReadTimeoutError

import yaml
from openserverless import seaweedfs_deploy as deploy


class SeaweedFSReadinessTests(unittest.TestCase):
    def setUp(self):
        self.sts = yaml.safe_load((Path(__file__).resolve().parents[1] /
                                  'deploy/seaweedfs/seaweedfs-sts.yaml').read_text())
        self.rendered = {'items': [self.sts]}

    def test_probe_patch_contains_only_missing_probes_and_waits_for_rollout(self):
        live = copy.deepcopy(self.sts)
        container = live['spec']['template']['spec']['containers'][0]
        del container['startupProbe']
        del container['readinessProbe']
        container.update(image='private/image:pinned', env=[{'name': 'CUSTOM', 'value': 'keep'}])
        before = copy.deepcopy(live)
        with patch.object(deploy.kube, 'kubectl', side_effect=[json.dumps(live), 'ready']) as kubectl, \
                patch.object(deploy.kube, 'patch') as apply:
            deploy._reconcile_seaweedfs_probes(self.rendered)
        name, payload = apply.call_args.args
        self.assertEqual(name, 'statefulset/seaweedfs')
        self.assertEqual(apply.call_args.kwargs, {'tpe': 'strategic'})
        self.assertEqual(set(payload), {'spec'})
        self.assertEqual(set(payload['spec']), {'template'})
        self.assertEqual(set(payload['spec']['template']), {'spec'})
        self.assertEqual(set(payload['spec']['template']['spec']), {'containers'})
        self.assertEqual(set(payload['spec']['template']['spec']['containers'][0]),
                         {'name', 'startupProbe', 'readinessProbe'})
        self.assertEqual(live, before)
        self.assertEqual(kubectl.call_args.args,
                         ('rollout', 'status', 'statefulset/seaweedfs', '--timeout=240s'))
        self.assertEqual(kubectl.call_args.kwargs, {'timeout': 250})

    def test_present_custom_probes_are_not_overwritten_or_restarted(self):
        self.sts['spec']['template']['spec']['containers'][0]['readinessProbe'] = {
            'tcpSocket': {'port': 9000}, 'periodSeconds': 15}
        with patch.object(deploy.kube, 'kubectl', side_effect=[json.dumps(self.sts), 'ready']), \
                patch.object(deploy.kube, 'patch') as apply:
            deploy._reconcile_seaweedfs_probes(self.rendered)
        apply.assert_not_called()

    def test_partial_probe_patch_keeps_existing_custom_probe(self):
        live = copy.deepcopy(self.sts)
        del live['spec']['template']['spec']['containers'][0]['startupProbe']
        with patch.object(deploy.kube, 'kubectl', side_effect=[json.dumps(live), 'ready']), \
                patch.object(deploy.kube, 'patch') as apply:
            deploy._reconcile_seaweedfs_probes(self.rendered)
        self.assertEqual(set(apply.call_args.args[1]['spec']['template']['spec']['containers'][0]),
                         {'name', 'startupProbe'})

    def test_lookup_failure_never_becomes_a_replacement_workload(self):
        with patch.object(deploy.kube, 'kubectl', side_effect=RuntimeError('unavailable')), \
                patch.object(deploy.kube, 'patch') as apply:
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                deploy._reconcile_seaweedfs_probes(self.rendered)
        apply.assert_not_called()

    def test_missing_container_is_rejected_without_patch(self):
        live = copy.deepcopy(self.sts)
        live['spec']['template']['spec']['containers'][0]['name'] = 'unexpected'
        with patch.object(deploy.kube, 'kubectl', return_value=json.dumps(live)), \
                patch.object(deploy.kube, 'patch') as apply:
            with self.assertRaisesRegex(RuntimeError, 'identify'):
                deploy._reconcile_seaweedfs_probes(self.rendered)
        apply.assert_not_called()

    def test_ondelete_does_not_silently_leave_old_pod_without_probes(self):
        live = copy.deepcopy(self.sts)
        live['spec']['updateStrategy'] = {'type': 'OnDelete'}
        del live['spec']['template']['spec']['containers'][0]['startupProbe']
        with patch.object(deploy.kube, 'kubectl', return_value=json.dumps(live)), \
                patch.object(deploy.kube, 'patch') as apply:
            with self.assertRaisesRegex(RuntimeError, 'operator-managed rollout'):
                deploy._reconcile_seaweedfs_probes(self.rendered)
        apply.assert_not_called()

    def test_iam_failure_after_readiness_is_not_retried(self):
        with patch.object(deploy, 'service_endpoint',
                          side_effect=lambda *args: contextlib.nullcontext(('seaweedfs', 9090))) as endpoint, \
                patch.object(deploy.util, 'wait_for_http') as wait:
            with self.assertRaisesRegex(RuntimeError, 'IAM mismatch'):
                with deploy._ready_private_filer({'name': 'seaweedfs'}):
                    raise RuntimeError('IAM mismatch')
        self.assertEqual(endpoint.call_count, 1)
        self.assertEqual(wait.call_count, 1)

    def test_probe_connection_and_read_timeouts_are_retried(self):
        with patch.object(deploy, 'service_endpoint', side_effect=lambda *args:
                          contextlib.nullcontext(('seaweedfs', 9090))) as endpoint, \
                patch.object(deploy.util, 'wait_for_http', side_effect=[
                    ConnectTimeoutError('delayed service routing'),
                    ReadTimeoutError(None, '/', 'starting filer'), None]) as wait, \
                patch.object(deploy.time, 'sleep'):
            with deploy._ready_private_filer({'name': 'seaweedfs'}) as url:
                self.assertEqual(url, 'http://seaweedfs:9090')
        self.assertEqual(endpoint.call_count, 3)
        self.assertEqual(wait.call_count, 3)

    def test_timeout_in_iam_body_is_not_retried_as_readiness(self):
        with patch.object(deploy, 'service_endpoint', side_effect=lambda *args:
                          contextlib.nullcontext(('seaweedfs', 9090))) as endpoint, \
                patch.object(deploy.util, 'wait_for_http'):
            with self.assertRaises(ConnectTimeoutError):
                with deploy._ready_private_filer({'name': 'seaweedfs'}):
                    raise ConnectTimeoutError('IAM transport failure')
        self.assertEqual(endpoint.call_count, 1)

    def test_lost_tunnel_is_recreated_before_caller_runs(self):
        def endpoint(*args):
            if endpoint_mock.call_count == 1:
                raise RuntimeError('lost port-forward')
            return contextlib.nullcontext(('127.0.0.1', 41238))
        with patch.object(deploy, 'service_endpoint', side_effect=endpoint) as endpoint_mock, \
                patch.object(deploy.util, 'wait_for_http'), \
                patch.object(deploy.time, 'sleep'):
            with deploy._ready_private_filer({'name': 'seaweedfs'}) as url:
                self.assertEqual(url, 'http://127.0.0.1:41238')
        self.assertEqual(endpoint_mock.call_count, 2)

    def test_deadline_prevents_iam_or_ingress(self):
        deploy.cfg.configure({'components': {'seaweedfs': True}})
        self.addCleanup(deploy.cfg.clean)
        service = {'kind': 'Service', 'metadata': {'name': 'seaweedfs'}}
        with patch.object(deploy.util, 'get_seaweedfs_config_data', return_value={'name': 'seaweedfs'}), \
                patch.object(deploy, '_render_seaweedfs_spec', return_value={'items': [service]}), \
                patch.object(deploy.datastore_security, 'apply'), \
                patch.object(deploy.kube, 'apply'), \
                patch.object(deploy, '_reconcile_seaweedfs_probes'), \
                patch.object(deploy, 'service_endpoint', side_effect=lambda *args:
                             contextlib.nullcontext(('seaweedfs', 9090))), \
                patch.object(deploy.util, 'wait_for_http', side_effect=TimeoutError('not ready')), \
                patch.object(deploy.time, 'monotonic', side_effect=[0, 0, 31, 31]), \
                patch.object(deploy, 'reconcile_anonymous_web_access') as iam, \
                patch.object(deploy.seaweedfs_ingress, 'create_seaweedfs_ingresses') as ingress:
            with self.assertRaisesRegex(TimeoutError, 'Filer|filer'):
                deploy.reconcile({'metadata': {'uid': 'synthetic'}})
        iam.assert_not_called()
        ingress.assert_not_called()

    def test_rollout_failure_prevents_iam(self):
        with patch.object(deploy.kube, 'kubectl', side_effect=[json.dumps(self.sts), TimeoutError('rollout')]), \
                patch.object(deploy, 'reconcile_anonymous_web_access') as iam:
            with self.assertRaisesRegex(TimeoutError, 'rollout'):
                deploy._reconcile_seaweedfs_probes(self.rendered)
        iam.assert_not_called()


if __name__ == '__main__':
    unittest.main()
