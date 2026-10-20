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

"""Private application of datastore credentials and narrow ingress policies."""
import base64
import json
import subprocess

import openserverless.kube as kube


def apply_private(spec, namespace='openserverless'):
    # The generic wrapper includes stdin and stderr in error logs.
    result = subprocess.run(['kubectl', '-n', namespace, 'apply', '-f', '-'],
                            input=json.dumps(spec), text=True, capture_output=True,
                            timeout=60)
    if result.returncode:
        raise RuntimeError('Could not apply private datastore resources')


def apply(spec):
    items = spec.get('items', [spec])
    private = [item for item in items if item['kind'] == 'Secret']
    public = [item for item in items if item['kind'] != 'Secret']
    if private:
        apply_private({'apiVersion': 'v1', 'kind': 'List', 'items': private})
    return kube.apply({'apiVersion': 'v1', 'kind': 'List', 'items': public})


def ensure_jwt_key(owner=None):
    """Keep a per-installation key; never reuse the legacy repository key."""
    name = 'openserverless-etcd-jwt-token-v2'
    raw = kube.kubectl('get', 'secret', name, '--ignore-not-found', '-o', 'json',
                       debugresult=False)
    if raw.strip():
        key = base64.b64decode(json.loads(raw)['data']['jwt-token.pem'], validate=True)
        check = subprocess.run(['openssl', 'rsa', '-check', '-noout'], input=key,
                               capture_output=True, timeout=30)
        if check.returncode:
            raise RuntimeError('Invalid etcd signing key; refusing implicit rotation')
        return name
    # A missing key on an already patched cluster is a security state error.
    current = kube.kubectl('get', 'sts', 'openserverless-etcd', '--ignore-not-found',
                           '-o', 'json', debugresult=False)
    if current.strip():
        volumes = json.loads(current)['spec']['template']['spec'].get('volumes', [])
        if any(v.get('secret', {}).get('secretName') == name for v in volumes):
            raise RuntimeError('Missing etcd signing key; refusing implicit rotation')
    result = subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA',
                             '-pkeyopt', 'rsa_keygen_bits:3072'],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Could not generate etcd signing key')
    resource = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                'metadata': {'name': name, 'namespace': 'openserverless'},
                'data': {'jwt-token.pem': base64.b64encode(result.stdout).decode()}}
    if owner:
        import kopf
        kopf.append_owner_reference([resource], owner)
    apply_private(resource)
    return name


def policy(component):
    if component == 'etcd':
        selector = {'app.kubernetes.io/name': 'openserverless-etcd'}
        ingress = [
            {'from': [{'podSelector': {'matchLabels': selector}}],
             'ports': [{'port': 2379, 'protocol': 'TCP'}, {'port': 2380, 'protocol': 'TCP'}]},
            {'from': [{'podSelector': {'matchLabels': {'name': 'openserverless-operator'}}},
                      {'podSelector': {'matchLabels': {'name': 'openserverless-milvus'}}}],
             'ports': [{'port': 2379, 'protocol': 'TCP'}]}]
    elif component == 'milvus':
        selector = {'name': 'openserverless-milvus'}
        ingress = [
            {'ports': [{'port': 19530, 'protocol': 'TCP'}]},
            {'from': [{'podSelector': {'matchLabels': {
                'app.kubernetes.io/name': 'prometheus',
                'app.kubernetes.io/instance': 'openserverless-prometheus'}}},
                      {'podSelector': {'matchLabels': {'name': 'openserverless-operator'}}}],
             'ports': [{'port': 9091, 'protocol': 'TCP'}]}]
    else:
        raise ValueError('Unknown datastore component')
    return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
            'metadata': {'name': 'openserverless-'+component+'-isolation', 'namespace': 'openserverless'},
            'spec': {'podSelector': {'matchLabels': selector},
                     'policyTypes': ['Ingress'], 'ingress': ingress}}


def finish_milvus_reconcile():
    kube.kubectl('rollout', 'status', 'deployment/openserverless-milvus-standalone', '--timeout=300s')
    # Remove the old ConfigMap AND its last-applied annotation by deleting it.
    # Its contents include S3 and Milvus admin credentials as well as etcd root.
    kube.kubectl('delete', 'configmap', 'openserverless-milvus', '--ignore-not-found')
