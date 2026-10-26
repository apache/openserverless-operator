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

"""Explicit lab-only network boundary test; no application code is deployed."""
import argparse
import datetime
import json
import socket
import subprocess
import time
import urllib.request

NS = 'openserverless'
CHECKS = []


def kubectl(*args, namespace=NS, data=None):
    return subprocess.run(['kubectl', '-n', namespace, *args], input=data,
                          capture_output=True, text=True, timeout=180, check=True).stdout


def obj(*args, namespace=NS):
    return json.loads(kubectl(*args, '-o', 'json', namespace=namespace))


def check(name, passed):
    CHECKS.append({'name': name, 'pass': bool(passed)})
    if not passed:
        raise AssertionError(name)


def pod_for(name):
    pods = obj('get', 'pods', '-l', 'app.kubernetes.io/name=' + name)['items']
    return next(p['metadata']['name'] for p in pods if p.get('status', {}).get('phase') == 'Running')


def fetch(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read()


def wget(pod, url, payload=None):
    args = ['exec', pod, '-c', 'prometheus-server', '--', '/bin/wget', '-q', '-T', '10', '-O', '-']
    if payload is not None:
        args += ['--header=Content-Type: application/json', '--post-data=' + json.dumps(payload)]
    return kubectl(*args, url)


def negative_matrix(pod, endpoints, namespace=NS, container=None):
    code = '''import concurrent.futures,json,socket
targets=json.loads(TARGETS)
def probe(target):
 try:
  with socket.create_connection((target['host'],target['port']),1.5): return dict(target, denied=False)
 except (TimeoutError,socket.timeout,ConnectionRefusedError,OSError): return dict(target,denied=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
 print(json.dumps(list(executor.map(probe,targets))))
'''.replace('TARGETS', repr(json.dumps(endpoints)))
    args = ['exec', pod]
    if container:
        args += ['-c', container]
    rows = json.loads(kubectl(*args, '--', 'python3', '-c', code, namespace=namespace))
    for row in rows:
        check(namespace + '/' + pod + ':' + row['name'], row['denied'])


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lab', action='store_true', required=True,
                        help='Authorize temporary synthetic pods and one resolved test alert in a lab.')
    parser.parse_args()
    pods = obj('get', 'pods')['items']
    tenants = [next(p for p in pods if ('-' + tenant + '-') in p['metadata']['name']
                    and p['status']['phase'] == 'Running') for tenant in ['opsvalalpha', 'opsvalbeta']]
    services = {}
    endpoints = []
    for component, name, port in [
        ('prometheus', 'openserverless-prometheus-server', 9999),
        ('kube-state-metrics', 'openserverless-prometheus-kube-state-metrics', 8080),
        ('alertmanager', 'openserverless-prometheus-alertmanager', 9093)]:
        service = obj('get', 'service', name)
        services[component] = service
        check(component + ':ClusterIP-only', service['spec']['type'] == 'ClusterIP')
        p = obj('get', 'pod', pod_for(component))
        for label, host in [('service', name + '.openserverless.svc.cluster.local'), ('pod', p['status']['podIP'])]:
            endpoints.append({'name': component + ':' + label, 'host': host, 'port': port})
        if component in ['kube-state-metrics', 'alertmanager']:
            endpoints.append({'name': component + ':secondary-listener',
                              'host': p['status']['podIP'],
                              'port': 8081 if component == 'kube-state-metrics' else 9094})
    for tenant in tenants:
        negative_matrix(tenant['metadata']['name'], endpoints, container='user-action')

    labels = {'app.kubernetes.io/name': 'prometheus',
              'app.kubernetes.io/instance': 'openserverless-prometheus'}
    image = tenants[0]['spec']['containers'][0]['image']
    foreign = 'ops-monitoring-security-test'
    fixture = 'ops-monitoring-forged-action'
    # Abort instead of reusing/deleting an existing fixture owned by someone else.
    existing = subprocess.run(['kubectl', 'get', 'namespace', foreign, '-o', 'name'], capture_output=True)
    if existing.returncode == 0:
        raise RuntimeError('Synthetic namespace already exists')
    existing = subprocess.run(['kubectl', '-n', NS, 'get', 'job', fixture, '-o', 'name'], capture_output=True)
    if existing.returncode == 0:
        raise RuntimeError('Synthetic job already exists')
    try:
        kubectl('create', 'namespace', foreign)
        def pod_spec():
            return {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                    'containers': [{'name': 'probe', 'image': image, 'imagePullPolicy': 'IfNotPresent',
                                    'command': ['python3', '-c', 'import time;time.sleep(600)']}]}
        foreign_pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'probe', 'namespace': foreign, 'labels': labels}, 'spec': pod_spec()}
        kubectl('apply', '-f', '-', namespace=foreign, data=json.dumps(foreign_pod))
        job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': fixture, 'namespace': NS},
               'spec': {'backoffLimit': 0, 'template': {'metadata': {'labels': dict(labels, **{'user-action-pod': 'false'})}, 'spec': pod_spec()}}}
        kubectl('apply', '-f', '-', data=json.dumps(job))
        kubectl('wait', '--for=condition=Ready', 'pod/probe', '--timeout=90s', namespace=foreign)
        time.sleep(2)
        fake = obj('get', 'pods', '-l', 'job-name=' + fixture)['items'][0]['metadata']['name']
        kubectl('wait', '--for=condition=Ready', 'pod/' + fake, '--timeout=90s')
        negative_matrix('probe', endpoints, namespace=foreign)
        negative_matrix(fake, endpoints)
    finally:
        kubectl('delete', 'job', fixture, '--ignore-not-found', '--wait=true')
        kubectl('delete', 'namespace', foreign, '--ignore-not-found', '--wait=true')

    prom = pod_for('prometheus')
    ksm = 'http://openserverless-prometheus-kube-state-metrics:8080/metrics'
    metrics = wget(prom, ksm)
    check('trusted:ksm-scrape', 'kube_pod_info' in metrics)
    check('trusted:no-secret-series-from-collector', 'kube_secret_' not in metrics)
    am = 'http://openserverless-prometheus-alertmanager:9093'
    check('trusted:alertmanager-status', 'config' in json.loads(wget(prom, am + '/api/v2/status')))
    now = datetime.datetime.now(datetime.timezone.utc)
    marker = 'OpsMonitoringBoundarySynthetic' + str(int(time.time()))
    alert = {'labels': {'alertname': marker, 'service': 'synthetic-lab'},
             'startsAt': (now - datetime.timedelta(seconds=1)).isoformat(),
             'endsAt': (now + datetime.timedelta(minutes=1)).isoformat()}
    try:
        wget(prom, am + '/api/v2/alerts', [alert])
        active = json.loads(wget(prom, am + '/api/v2/alerts'))
        check('trusted:alert-delivery', any(a['labels'].get('alertname') == marker for a in active))
    finally:
        alert['endsAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        wget(prom, am + '/api/v2/alerts', [alert])
    check('trusted:reload', wget(prom, 'http://127.0.0.1:9999/-/reload', {}) == '')
    flags = json.loads(wget(prom, 'http://127.0.0.1:9999/api/v1/status/flags'))['data']
    check('trusted:admin-api-disabled', flags['web.enable-admin-api'] == 'false')
    targets = json.loads(wget(prom, 'http://127.0.0.1:9999/api/v1/targets'))['data']['activeTargets']
    check('trusted:ksm-target-up', any(t['labels'].get('job') == 'kube-state-metrics' and t['health'] == 'up' for t in targets))
    rbac = subprocess.run(['kubectl', 'auth', 'can-i', '--as=system:serviceaccount:openserverless:openserverless-prometheus-kube-state-metrics', 'list', 'secrets', '--all-namespaces'], capture_output=True, text=True)
    check('rbac:collector-cannot-list-secrets', rbac.stdout.strip() == 'no')
    # Kubernetes-authenticated port-forward preserves administrator UI/query access.
    forwarding = subprocess.Popen(['kubectl', '-n', NS, 'port-forward', '--address', '127.0.0.1', 'service/openserverless-prometheus-server', '19090:9999'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for attempt in range(50):
            try:
                response = fetch('http://127.0.0.1:19090/api/v1/query?query=up')
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('Port-forward did not become ready')
        check('admin:authenticated-port-forward-query', json.loads(response)['status'] == 'success')
    finally:
        forwarding.terminate()
        forwarding.wait(timeout=10)
    try:
        with socket.create_connection(('127.0.0.1', 30299), 1):
            retired = False
    except OSError:
        retired = True
    check('admin:legacy-nodeport-removed', retired)


if __name__ == '__main__':
    try:
        run()
    finally:
        print(json.dumps({'checks': CHECKS, 'count': len(CHECKS), 'failed': sum(not c['pass'] for c in CHECKS)}))
