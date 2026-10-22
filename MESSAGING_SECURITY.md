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

# Kafka and ZooKeeper tenant isolation

The full deployment runs untrusted action pods alongside the shared Kafka and
ZooKeeper services. Those services are private control-plane endpoints; tenant
actions must not connect to them, even when the action knows their DNS names or
pod IPs.

The operator installs ingress NetworkPolicies before reconciling either
component. Kafka's broker port accepts only controller, invoker, scheduler and
Kafka pods in the same namespace. Kafka metrics accept only the installation's
Prometheus pods. ZooKeeper's client port accepts Kafka, invoker and ZooKeeper
pods; quorum ports accept only ZooKeeper peers. Every allowed peer selector
also excludes pods carrying the `user-action-pod` label, regardless of its value.
The invoker controls action pod labels; action annotations cannot grant these
network permissions.

The policies are included in rendered and saved component specs and inherit the
Whisk owner reference. Policy application failure stops workload reconciliation.
A pod-template revision rolls legacy Kafka and ZooKeeper pods once, closing
connections established before the boundary was installed. Reconciliation waits
for the rollout. When called with a saved component spec, the explicit deletion
helper keeps the policy until all component pods have disappeared; a deletion
timeout retains the policy.

Normal owner-backed Whisk deletion currently relies on Kubernetes owner garbage
collection, which does not guarantee that the policy outlives the messaging pods.
The ordered helper is not reached when the process-local saved spec is absent.
This teardown race is a known, accepted limitation of this change; policy-last
deletion is not guaranteed during Whisk uninstall. Normal operation and automatic
upgrade isolation are covered by the verification below.

## Deployment requirements

The cluster must enforce Kubernetes NetworkPolicy. The presence of a policy API
object alone is not proof of enforcement. K3s with its network-policy controller
enabled is supported by this boundary; an installation with
`--disable-network-policy`, or a CNI without policy support, needs an enforcing
network provider before this protection is effective. Do not claim tenant
isolation on such a cluster without a live denied-connection test.

For an existing full installation, the patched operator automatically reconciles
enabled ZooKeeper and Kafka components when it resumes or processes a Whisk
configuration update. The supported `ops update operator` flow therefore installs
the boundary without manual internal calls. Reconciliation applies ZooKeeper
before Kafka, propagates errors to the operator handler, and waits for each
StatefulSet rollout before continuing normal post-resume or update processing.
A missing Whisk owner aborts reconciliation. Slim installations do not deploy
messaging components. Repeating a restart preserves existing policies and does
not roll unchanged pod templates. Plan for the single-replica service restart on
the first upgrade that installs this boundary. Do not remove the policies to work
around an unrelated connectivity failure. Kubernetes NetworkPolicies are
additive: an administrator-installed broad allow policy can reopen access.

This patch preserves broker protocols, component versions and PVC contents. It
enforces the ordinary tenant-action boundary at the network layer; it does not
add TLS, Kafka SASL/ACLs or ZooKeeper authentication. Host/node administrators,
Kubernetes administrators and compromised allowed control-plane pods remain
trusted. Service-level credentials would provide additional protection against
those separate paths. Slim deployments do not create these messaging components.

## Verification

Run `python -m unittest discover -s tests -p test_messaging_security.py` in the
operator environment. Live acceptance must additionally demonstrate:

- A normal action in each of two tenants cannot reach Kafka or ZooKeeper by
  Service name, pod DNS name or direct pod IP, or Kafka metrics ports.
- A pod in another namespace cannot gain access by copying trusted labels.
- Action-labelled pods remain denied even with a trusted component label.
- Controller/invoker Kafka traffic, invoker ZooKeeper traffic, broker-to-
  ZooKeeper traffic and Prometheus metric scraping still work.
- Invoker restart preserves its assigned ID and successful tenant invocations.
- Updating an existing installation through `ops update operator` installs both
  policies and rolls legacy messaging pods without manual reconciliation;
  repeating the operator restart preserves the messaging pod identities.
- Alpha/Beta application, Redis Lua, Streamer and scheduled actions still work
  without editing their code.
