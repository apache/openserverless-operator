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

"""Messaging isolation contract and component lifecycle regression tests."""

import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

from openserverless import config, kafka, main, messaging_security, zookeeper

ROOT = Path(__file__).resolve().parents[1]


def policy(component):
    return yaml.safe_load(next((ROOT / 'deploy' / component).glob('*networkpolicy.yaml')).read_text())


def matches(selector, labels):
    if any(labels.get(k) != v for k, v in selector.get('matchLabels', {}).items()):
        return False
    for expression in selector.get('matchExpressions', []):
        key, op = expression['key'], expression['operator']
        if op == 'In' and labels.get(key) not in expression['values']:
            return False
        if op == 'DoesNotExist' and key in labels:
            return False
    return True


def allowed(component, labels, port, namespace='openserverless'):
    # Ingress peers without namespaceSelector select only the policy namespace.
    if namespace != 'openserverless':
        return False
    return any(any(p['port'] == port for p in rule['ports']) and
               any(matches(peer['podSelector'], labels) for peer in rule['from'])
               for rule in policy(component)['spec']['ingress'])


class MessagingSecurityTests(unittest.TestCase):
    def tearDown(self):
        config.clean()

    def test_existing_cluster_resume_installs_isolation_before_post_resume(self):
        events = []
        owner = {'metadata': {'name': 'controller', 'uid': 'synthetic'}}
        def configure(spec, **kwargs):
            config.configure(spec)
        with patch.object(main.operator_util, 'config_from_spec', side_effect=configure), \
             patch.object(main.kube, 'get', return_value=owner), \
             patch.object(zookeeper, 'create', side_effect=lambda obj: events.append(('zookeeper', obj))), \
             patch.object(kafka, 'create', side_effect=lambda obj: events.append(('kafka', obj))), \
             patch.object(main.operator_util, 'whisk_post_resume', side_effect=lambda name: events.append(('post', name))):
            main.whisk_resume({'components': {'kafka': True, 'zookeeper': True}}, {}, 'controller')
        self.assertEqual(events, [('zookeeper', owner), ('kafka', owner), ('post', 'controller')])

    def test_resume_failure_propagates_and_never_reports_post_resume_success(self):
        config.configure({'components': {'kafka': True, 'zookeeper': True}})
        with patch.object(main.operator_util, 'config_from_spec'), \
             patch.object(main.kube, 'get', return_value={'metadata': {'uid': 'synthetic'}}), \
             patch.object(zookeeper, 'create', side_effect=RuntimeError('policy denied')), \
             patch.object(kafka, 'create') as broker, \
             patch.object(main.operator_util, 'whisk_post_resume') as post:
            with self.assertRaisesRegex(RuntimeError, 'policy denied'):
                main.whisk_resume({}, {}, 'controller')
        broker.assert_not_called()
        post.assert_not_called()

    def test_configuration_update_reconciles_before_existing_patcher(self):
        events = []
        config.configure({'components': {'kafka': True}})
        owner = {'metadata': {'uid': 'synthetic'}}
        with patch.object(main.operator_util, 'config_from_spec'), \
             patch.object(main.kube, 'get', return_value=owner), \
             patch.object(kafka, 'create', side_effect=lambda obj: events.append(('kafka', obj))), \
             patch.object(zookeeper, 'create') as zoo, \
             patch.object(main.patcher, 'patch', side_effect=lambda *args: events.append(('patch', args))):
            main.whisk_update({}, {}, 'openserverless', (), 'controller')
        self.assertEqual(events, [('kafka', owner), ('patch', ((), {}, owner, 'controller'))])
        zoo.assert_not_called()

    def test_missing_owner_aborts_before_any_component_mutation(self):
        config.configure({'components': {'kafka': True, 'zookeeper': True}})
        with patch.object(kafka, 'create') as broker, patch.object(zookeeper, 'create') as zoo:
            for owner in [None, {}, {'metadata': {}}, {'metadata': {'name': 'controller'}}]:
                with self.assertRaisesRegex(RuntimeError, 'Whisk owner'):
                    messaging_security.reconcile(owner)
        broker.assert_not_called()
        zoo.assert_not_called()

    def test_slim_resume_does_not_query_owner_or_create_messaging(self):
        config.configure({'components': {'kafka': False, 'zookeeper': False}})
        with patch.object(main.operator_util, 'config_from_spec'), \
             patch.object(main.kube, 'get') as get, \
             patch.object(kafka, 'create') as broker, \
             patch.object(zookeeper, 'create') as zoo, \
             patch.object(main.operator_util, 'whisk_post_resume') as post:
            main.whisk_resume({}, {}, 'controller')
            messaging_security.reconcile(None)
        get.assert_not_called()
        broker.assert_not_called()
        zoo.assert_not_called()
        post.assert_called_once_with('controller')

    def test_kafka_rollout_failure_stops_update_processing(self):
        config.configure({'components': {'kafka': True}})
        with patch.object(main.operator_util, 'config_from_spec'), \
             patch.object(main.kube, 'get', return_value={'metadata': {'uid': 'synthetic'}}), \
             patch.object(kafka, 'create', side_effect=RuntimeError('rollout timed out')), \
             patch.object(main.patcher, 'patch') as patcher:
            with self.assertRaisesRegex(RuntimeError, 'rollout timed out'):
                main.whisk_update({}, {}, 'openserverless', (), 'controller')
        patcher.assert_not_called()

    def test_tenant_and_unrelated_pods_denied_on_all_ports(self):
        for component, ports in [('kafka', [9092, 9071, 9888]),
                                 ('zookeeper', [2181, 2888, 3888])]:
            for labels in [{}, {'user-action-pod': 'true'},
                           {'name': 'guest'}, {'name': 'openserverless-system-api'}]:
                for port in ports:
                    with self.subTest(component=component, labels=labels, port=port):
                        self.assertFalse(allowed(component, labels, port))

    def test_action_cannot_impersonate_trusted_peer_or_monitoring(self):
        for component, ports in [('kafka', [9092, 9071, 9888]),
                                 ('zookeeper', [2181, 2888, 3888])]:
            for name in ['controller', 'invoker', 'scheduler', 'kafka', 'zookeeper']:
                for marker in ['true', 'false', '']:
                    labels = {'name': name, 'user-action-pod': marker,
                              'app.kubernetes.io/name': 'prometheus',
                              'app.kubernetes.io/instance': 'openserverless-prometheus'}
                    for port in ports:
                        self.assertFalse(allowed(component, labels, port))

    def test_same_labels_in_other_namespace_are_denied(self):
        for component in ['kafka', 'zookeeper']:
            for name in ['controller', 'invoker', 'kafka', 'zookeeper']:
                self.assertFalse(allowed(component, {'name': name}, 9092, namespace='other'))
                self.assertFalse(allowed(component, {'name': name}, 2181, namespace='other'))

    def test_control_plane_clients_preserve_required_connections(self):
        for name in ['controller', 'invoker', 'scheduler', 'kafka']:
            self.assertTrue(allowed('kafka', {'name': name}, 9092))
        for name in ['kafka', 'invoker', 'zookeeper']:
            self.assertTrue(allowed('zookeeper', {'name': name}, 2181))
        for port in [2888, 3888]:
            self.assertTrue(allowed('zookeeper', {'name': 'zookeeper'}, port))
            for name in ['controller', 'invoker', 'scheduler', 'kafka']:
                self.assertFalse(allowed('zookeeper', {'name': name}, port))

    def test_metrics_does_not_grant_broker_access(self):
        labels = {'app.kubernetes.io/name': 'prometheus',
                  'app.kubernetes.io/instance': 'openserverless-prometheus'}
        for port in [9071, 9888]:
            self.assertTrue(allowed('kafka', labels, port))
        self.assertFalse(allowed('kafka', labels, 9092))
        self.assertFalse(allowed('zookeeper', labels, 2181))

    def test_all_policy_rules_have_scoped_peers_and_ports(self):
        for component in ['kafka', 'zookeeper']:
            obj = policy(component)
            self.assertEqual(obj['spec']['podSelector']['matchLabels'], {'name': component})
            self.assertEqual(obj['spec']['policyTypes'], ['Ingress'])
            for rule in obj['spec']['ingress']:
                self.assertTrue(rule['ports'])
                self.assertTrue(rule['from'])
                for peer in rule['from']:
                    self.assertEqual(set(peer), {'podSelector'})
                    self.assertTrue(peer['podSelector'])

    def test_policy_apply_failure_never_applies_workloads(self):
        for component in ['kafka', 'zookeeper']:
            p = policy(component)
            workload = {'kind': 'StatefulSet', 'metadata': {'name': component}}
            spec = {'apiVersion': 'v1', 'kind': 'List', 'items': [workload, p]}
            with patch.object(messaging_security.kube, 'apply', side_effect=RuntimeError('denied')) as apply:
                with self.assertRaisesRegex(RuntimeError, 'denied'):
                    messaging_security.apply(spec, component)
                self.assertEqual(apply.call_count, 1)
                self.assertEqual(apply.call_args.args[0]['items'], [p])

    def test_missing_policy_fails_before_any_kubernetes_mutation(self):
        for component in ['kafka', 'zookeeper']:
            with patch.object(messaging_security.kube, 'apply') as apply:
                with self.assertRaisesRegex(RuntimeError, 'Missing'):
                    messaging_security.apply({'items': []}, component)
                apply.assert_not_called()

    def test_component_reconciliation_and_saved_deletion_spec_include_policy(self):
        for component, module in [('kafka', kafka), ('zookeeper', zookeeper)]:
            for owner in [None, {'apiVersion': 'openserverless.org/v1', 'kind': 'Whisk',
                                 'metadata': {'name': 'test', 'uid': 'synthetic'}}]:
                config.clean()
                config.put('openserverless.zookeeper.url', 'zookeeper-0.zookeeper:2181')
                spec = {'apiVersion': 'v1', 'kind': 'List',
                        'items': [{'kind': 'StatefulSet', 'metadata': {'name': component}},
                                  policy(component)]}
                calls = []
                with patch.object(module.cfg_util, 'get_' + component + '_config_data',
                                  return_value={'affinity': False, 'tolerations': False}), \
                     patch.object(module.kus, 'patchTemplates', return_value=''), \
                     patch.object(module.kus, 'kustom_list', return_value=spec), \
                     patch.object(module.util, 'wait_for_pod_ready'), \
                     patch.object(module, 'get_' + component + '_connect_data', return_value=component + ':2181'), \
                     patch.object(messaging_security.kube, 'kubectl') as kubectl, \
                     patch.object(messaging_security.kube, 'apply',
                                  side_effect=lambda obj: calls.append(copy.deepcopy(obj)) or 'applied'):
                    self.assertEqual(module.create(owner), 'applied')
                self.assertTrue(all(item['kind'] == 'NetworkPolicy' for item in calls[0]['items']))
                self.assertEqual(calls[1]['items'], spec['items'])
                kubectl.assert_called_once_with('rollout', 'status', 'statefulset/' + component, '--timeout=300s')
                if owner:
                    self.assertTrue(all(item['metadata'].get('ownerReferences') for item in calls[0]['items']))
                else:
                    saved = config.get('state.' + component + '.spec')
                    self.assertTrue(any(item['kind'] == 'NetworkPolicy' for item in saved['items']))
                    with patch.object(module.security, 'delete', return_value='deleted') as delete:
                        self.assertEqual(module.delete(), 'deleted')
                        self.assertEqual(delete.call_args.args[0], saved)

    def test_legacy_sessions_are_closed_by_statefulset_rollout(self):
        for component in ['kafka', 'zookeeper']:
            path = next((ROOT / 'deploy' / component).glob('*sts.yaml'))
            obj = next(item for item in yaml.safe_load_all(path.read_text())
                       if item and item['kind'] == 'StatefulSet')
            self.assertEqual(obj['spec']['template']['metadata']['annotations']
                             ['openserverless.org/messaging-isolation'], 'v1')

    def test_deletion_keeps_policy_until_all_component_pods_are_gone(self):
        for component in ['kafka', 'zookeeper']:
            p = policy(component)
            sts = {'kind': 'StatefulSet', 'metadata': {'name': component}}
            events = []
            def kubectl(*args):
                events.append(args[0])
                return 'pod/' + component + '-0' if args[0] == 'get' else ''
            def delete(spec):
                events.append(spec['items'][0]['kind'])
                return 'deleted'
            with patch.object(messaging_security.kube, 'kubectl', side_effect=kubectl), \
                 patch.object(messaging_security.kube, 'delete', side_effect=delete):
                messaging_security.delete({'items': [p, sts]}, component)
            self.assertEqual(events, ['StatefulSet', 'get', 'wait', 'NetworkPolicy'])

    def test_delete_timeout_keeps_policy(self):
        with patch.object(messaging_security.kube, 'kubectl',
                          side_effect=['pod/kafka-0', RuntimeError('still terminating')]), \
             patch.object(messaging_security.kube, 'delete', return_value='deleted') as delete:
            with self.assertRaisesRegex(RuntimeError, 'still terminating'):
                messaging_security.delete({'items': [policy('kafka'), {'kind': 'StatefulSet'}]}, 'kafka')
            self.assertEqual(delete.call_count, 1)

    def test_legacy_saved_spec_without_policy_can_still_be_deleted(self):
        with patch.object(messaging_security.kube, 'kubectl', return_value=''), \
             patch.object(messaging_security.kube, 'delete', return_value='deleted') as delete:
            self.assertEqual(messaging_security.delete({'items': [{'kind': 'StatefulSet'}]}, 'kafka'), 'deleted')
            self.assertEqual(delete.call_count, 1)


if __name__ == '__main__':
    unittest.main()
