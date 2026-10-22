<!--
Licensed to the Apache Software Foundation (ASF) under one or more
contributor license agreements. See the NOTICE file distributed with this
work for additional information regarding copyright ownership. The ASF
licenses this file to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.
-->

# Monitoring access boundary

Prometheus, kube-state-metrics and Alertmanager administer shared cluster state.
Tenant actions must not reach any of their listeners, including direct pod IPs.
NetworkPolicies deny ingress to Prometheus, allow only same-namespace Prometheus
pods to scrape kube-state-metrics and send alerts to Alertmanager, and allow
Alertmanager gossip only between its own peers. Allowed selectors explicitly
exclude every pod carrying the invoker-controlled `user-action-pod` label.
Copying trusted labels in another namespace does not grant access.

Prometheus uses ClusterIP instead of the former NodePort 30299. Its destructive
admin API is disabled. Lifecycle reload remains enabled because the local config
reloader needs it; both processes communicate over loopback. The network boundary
blocks tenant access to lifecycle routes as well as to query, status and metrics
routes. No new application credentials or environment variables are required.

## Operator access

Use a Kubernetes identity authorized for pod port-forwarding:

```sh
kubectl -n openserverless port-forward --address 127.0.0.1 \
  service/openserverless-prometheus-server 9090:9999
```

Open `http://127.0.0.1:9090`. For Alertmanager, use a separate terminal:

```sh
kubectl -n openserverless port-forward --address 127.0.0.1 \
  service/openserverless-prometheus-alertmanager 9093:9093
```

Open `http://127.0.0.1:9093`. If kubectl runs on a remote server, forward its
loopback port over SSH. Keep the port-forward bound to loopback. The Kubernetes
API authorizes access; the native monitoring API does not authenticate callers.
Do not publish these listeners through an unauthenticated ingress or NodePort.

## Installation and upgrade

The cluster must enforce NetworkPolicy. K3s supports this when its network-policy
controller is enabled. A CNI without policy enforcement, K3s started with
`--disable-network-policy`, or another administrator-created broad allow policy
can leave the services accessible. Validate denial from a real action pod before
claiming tenant isolation. A pod with Kubernetes/host administration privileges,
or a compromised permitted Prometheus pod, is outside the ordinary tenant model.

Install the matching task and operator changes together. The task removes the
collector's cluster-wide Secret list/watch permissions; the matching deployment
also stops collecting Secret metadata. During an operator update the admin client
reapplies the monitoring roles before changing the operator image. The operator
itself must not receive extra cluster permissions to perform that operation.
For an image-only upgrade, an administrator must first apply the matching
`setup/kubernetes/roles/openserverless-monitoring-roles.yaml` from the task repo.

The operator reconciles monitoring on resume and configuration update, including
existing clusters. It applies isolation before workloads and propagates policy or
rollout errors. A pod-template annotation rolls legacy monitored pods once,
closing connections established before the policy. Component versions, PVC data,
receiver configuration and Alpha/Beta application source stay unchanged.
Monitoring also works when Alertmanager is disabled. Repeated reconciliation
does not roll unchanged monitored pod templates.

Explicit component deletion retains policies until monitored pods terminate.
Whole-Whisk owner garbage collection has no policy-last ordering guarantee; this
is the same accepted uninstall limitation as the messaging boundary. Policies
are not a substitute for service authentication in threat models that distrust
node administrators or permitted control-plane pods.

## Credential handling and validation

Alertmanager 0.25 redacts its password and Slack URL fields in the status API.
The template still stores receiver credentials in a ConfigMap; moving them to
Secret-backed files is a separate hardening item for principals already allowed
to read cluster configuration. Do not describe status config output alone as
evidence of credential leakage.

Run `python -m unittest discover -s tests -p test_monitoring_security.py` and
`python -m unittest discover -s tests -p test_alertmanager_config.py` in the operator
environment. Live acceptance must verify denied tenant connections by service
and pod IP, forged trusted labels, another namespace, trusted scraping and alert
delivery, reload, authenticated port-forward access, readiness, repeat resume,
RBAC reduction, and unchanged Alpha/Beta application behavior.
