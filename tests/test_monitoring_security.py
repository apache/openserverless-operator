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

"""Tenant isolation and upgrade/creation contracts for shared monitoring."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml
from openserverless import config, main, monitoring

ROOT = Path(__file__).resolve().parents[1]


def documents(component):
    return list(yaml.safe_load_all(next((ROOT / 'deploy' / component).glob('*networkpolicy.yaml')).read_text()))


def accepts(policy, labels, port, namespace='openserverless'):
    if namespace != 'openserverless':
        return False
    for rule in policy['spec']['ingress']:
        if not any(item['port'] == port for item in rule['ports']):
            continue
        for peer in rule['from']:
            selector = peer['podSelector']
            if any(labels.get(k) != v for k, v in selector.get('matchLabels', {}).items()):
                continue
            if any(e['key'] in labels for e in selector.get('matchExpressions', [])
                   if e['operator'] == 'DoesNotExist'):
                continue
            return True
    return False


class MonitoringSecurityTests(unittest.TestCase):
    def tearDown(self):
        config.clean()

    def test_tenants_cannot_read_or_mutate_any_monitoring_listener(self):
        for component in ['monitoring', 'alert-manager']:
            for policy in documents(component):
                for labels in [{}, {'user-action-pod': 'true'},
                               {'name': 'controller'}, {'name': 'invoker'}]:
                    for port in [9999, 9093, 9094, 8080, 8081]:
                        self.assertFalse(accepts(policy, labels, port))

    def test_trusted_labels_never_override_action_marker_or_namespace(self):
        for policy in documents('monitoring') + documents('alert-manager'):
            for name in ['prometheus', 'alertmanager']:
                labels = {'app.kubernetes.io/name': name,
                          'app.kubernetes.io/instance': 'openserverless-prometheus'}
                for port in [9999, 9093, 9094, 8080, 8081]:
                    self.assertFalse(accepts(policy, labels, port, 'foreign'))
                    for marker in ['true', 'false', '']:
                        self.assertFalse(accepts(policy, dict(labels, **{'user-action-pod': marker}), port))

    def test_prometheus_retains_scraping_and_alert_delivery_only(self):
        labels = {'app.kubernetes.io/name': 'prometheus',
                  'app.kubernetes.io/instance': 'openserverless-prometheus'}
        server, metrics = documents('monitoring')
        alertmanager = documents('alert-manager')[0]
        self.assertFalse(accepts(server, labels, 9999))
        self.assertTrue(accepts(metrics, labels, 8080))
        self.assertFalse(accepts(metrics, labels, 8081))
        self.assertTrue(accepts(alertmanager, labels, 9093))
        self.assertFalse(accepts(alertmanager, labels, 9094))

    def test_no_public_nodeport_or_destructive_admin_api(self):
        service = yaml.safe_load((ROOT / 'deploy/monitoring/prometheus-04-svc.yaml').read_text())
        self.assertEqual(service['spec']['type'], 'ClusterIP')
        self.assertTrue(all('nodePort' not in p for p in service['spec']['ports']))
        deployment = yaml.safe_load((ROOT / 'deploy/monitoring/prometheus-03-dep.yaml').read_text())
        containers = deployment['spec']['template']['spec']['containers']
        self.assertNotIn('--web.enable-admin-api', containers[0]['args'])
        self.assertIn('--web.enable-lifecycle', containers[0]['args'])
        self.assertIn('--reload-url=http://127.0.0.1:9999/-/reload', containers[1]['args'])

    def test_secret_collection_and_rbac_are_removed(self):
        deployment = yaml.safe_load((ROOT / 'deploy/monitoring/kubestate-03-dep.yaml').read_text())
        args = deployment['spec']['template']['spec']['containers'][0]['args']
        resources = next(a.split('=', 1)[1] for a in args if a.startswith('--resources='))
        self.assertNotIn('secrets', resources.split(','))
        roles = list(yaml.safe_load_all((ROOT / 'deploy/openserverless-permissions/openserverless-monitoring-01-roles.yaml').read_text()))
        self.assertTrue(all('secrets' not in r.get('resources', []) for role in roles for r in role.get('rules', [])))

    def test_policy_failure_stops_all_workloads(self):
        for component in ['monitoring', 'alert-manager']:
            spec = {'items': documents(component) + [{'kind': 'Deployment'}]}
            with patch.object(monitoring.kube, 'apply', side_effect=RuntimeError('denied')) as apply:
                with self.assertRaisesRegex(RuntimeError, 'denied'):
                    monitoring._apply(spec, component)
            self.assertEqual(apply.call_count, 1)
            self.assertTrue(all(o['kind'] == 'NetworkPolicy' for o in apply.call_args.args[0]['items']))

    def test_missing_policy_stops_before_any_mutation(self):
        with patch.object(monitoring.kube, 'apply') as apply:
            for component in ['monitoring', 'alert-manager']:
                with self.assertRaisesRegex(RuntimeError, 'Missing'):
                    monitoring._apply({'items': []}, component)
        apply.assert_not_called()

    def test_rendered_specs_and_saved_state_keep_owned_policies(self):
        for enabled in [False, True]:
            for owned in [False, True]:
                config.configure({'monitoring': {'alert-manager': {'enabled': enabled}}})
                owner = {'apiVersion': 'openserverless.org/v1', 'kind': 'Whisk',
                         'metadata': {'name': 'controller', 'uid': 'synthetic'}} if owned else None
                calls = []
                def rendered(where, *args, **kwargs):
                    return {'apiVersion': 'v1', 'kind': 'List', 'items': copy.deepcopy(documents(where))}
                data = {'affinity': False, 'tolerations': False, 'applypodsecurity': False}
                with patch.object(monitoring.ent_util, 'get_am_config_data', return_value=data), \
                     patch.object(monitoring.ent_util, 'get_prometheus_config_data', return_value=data), \
                     patch.object(monitoring.kus, 'renderTemplate'), \
                     patch.object(monitoring.kus, 'patchTemplates', return_value=''), \
                     patch.object(monitoring.kus, 'kustom_list', side_effect=rendered), \
                     patch.object(monitoring.kube, 'apply', side_effect=lambda obj: calls.append(copy.deepcopy(obj)) or 'ok'), \
                     patch.object(monitoring.kube, 'kubectl'), \
                     patch.object(monitoring.util, 'wait_for_pod_ready'):
                    self.assertEqual(monitoring.create(owner), 'ok')
                self.assertEqual(len(calls), 4 if enabled else 2)
                if owned:
                    self.assertTrue(all(o['metadata'].get('ownerReferences') for c in calls for o in c['items']))
                else:
                    self.assertTrue(config.get('state.prometheus.spec'))
                    if enabled:
                        self.assertTrue(config.get('state.alertmanager.spec'))

    def test_resume_and_update_reconcile_before_success(self):
        config.configure({'components': {'monitoring': True}})
        owner = {'metadata': {'uid': 'synthetic'}}
        with patch.object(main.operator_util, 'config_from_spec'), \
             patch.object(main.kube, 'get', return_value=owner), \
             patch.object(monitoring, 'create', side_effect=RuntimeError('denied')), \
             patch.object(main.operator_util, 'whisk_post_resume') as post, \
             patch.object(main.patcher, 'patch') as patcher:
            with self.assertRaisesRegex(RuntimeError, 'denied'):
                main.whisk_resume({}, {}, 'controller')
            with self.assertRaisesRegex(RuntimeError, 'denied'):
                main.whisk_update({}, {}, 'openserverless', (), 'controller')
        post.assert_not_called()
        patcher.assert_not_called()

    def test_monitoring_disabled_and_missing_owner(self):
        config.configure({'components': {'monitoring': False}})
        with patch.object(monitoring, 'create') as create:
            monitoring.reconcile(None)
            create.assert_not_called()
            config.put('components.monitoring', True)
            with self.assertRaisesRegex(RuntimeError, 'Whisk owner'):
                monitoring.reconcile(None)
            create.assert_not_called()

    def test_deletion_timeout_retains_policy(self):
        spec = {'items': documents('monitoring') + [{'kind': 'Deployment'}]}
        with patch.object(monitoring.kube, 'delete', return_value='deleted') as delete, \
             patch.object(monitoring.kube, 'kubectl', side_effect=['pod/synthetic', RuntimeError('timeout')]):
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                monitoring._delete(spec)
        self.assertEqual(delete.call_count, 1)
        self.assertTrue(all(o['kind'] != 'NetworkPolicy' for o in delete.call_args.args[0]['items']))


if __name__ == '__main__':
    unittest.main()
