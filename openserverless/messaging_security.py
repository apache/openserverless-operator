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

"""Apply the messaging network boundary before creating or updating workloads."""

import openserverless.kube as kube
import openserverless.config as cfg


def reconcile(owner):
    """Install the boundary on existing clusters during operator resume/update."""
    # Import lazily: component create functions use this module's apply helper.
    from openserverless import kafka, zookeeper

    enabled = [(name, module) for name, module in
               [('zookeeper', zookeeper), ('kafka', kafka)]
               if cfg.get('components.' + name)]
    if not enabled:
        return
    # Never turn a failed owner lookup into an ownerless component deployment.
    if not owner or not owner.get('metadata', {}).get('uid'):
        raise RuntimeError('Cannot reconcile messaging isolation without the Whisk owner')
    for name, module in enabled:
        module.create(owner)


def apply(spec, component):
    policy_name = 'openserverless-' + component + '-isolation'
    policies = [item for item in spec['items']
                if item['kind'] == 'NetworkPolicy']
    if not any(item['metadata']['name'] == policy_name for item in policies):
        raise RuntimeError('Missing ' + component + ' isolation policy')
    # Do not create/reconcile an exposed service if policy application fails.
    # The complete spec still owns the policy for reconciliation and deletion.
    kube.apply({'apiVersion': 'v1', 'kind': 'List', 'items': policies})
    result = kube.apply(spec)
    # The template boundary revision rolls legacy pods to close existing
    # anonymous sessions as well as blocking new connections.
    kube.kubectl('rollout', 'status', 'statefulset/' + component, '--timeout=300s')
    return result


def delete(spec, component):
    policies = [item for item in spec['items'] if item['kind'] == 'NetworkPolicy']
    workloads = [item for item in spec['items'] if item['kind'] != 'NetworkPolicy']
    result = kube.delete({'apiVersion': 'v1', 'kind': 'List', 'items': workloads})
    # StatefulSet deletion can return while its dependent pods are terminating.
    # Keep the boundary until those pods are actually gone; fail closed on error.
    pods = kube.kubectl('get', 'pods', '-l', 'name=' + component, '-o', 'name').split()
    if pods:
        kube.kubectl('wait', '--for=delete', *pods, '--timeout=300s')
    if policies:
        result += kube.delete({'apiVersion': 'v1', 'kind': 'List', 'items': policies})
    return result
