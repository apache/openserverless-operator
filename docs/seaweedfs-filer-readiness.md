# SeaweedFS Filer readiness on 0.9.0

An existing installation can report its SeaweedFS pod Ready before the private
Filer listener starts. Resume-time IAM reconciliation must wait for the actual
private HTTP endpoint. See [OpenServerless #286](https://github.com/apache/openserverless/issues/286).

Bootstrap and resume share the private endpoint readiness helper. Probe timeouts,
including urllib3 connection/read timeouts, are retried within the readiness
window. A failed startup port-forward is recreated. Once readiness succeeds,
bootstrap and IAM errors propagate; an incorrect persisted grant is never
accepted or retried as readiness.

New SeaweedFS StatefulSets receive HTTP startup and readiness probes on the
private Filer port 9090. Resume fills missing probes on existing StatefulSets
using a strategic merge patch to the named container. Existing custom probes,
image, arguments, environment, storage and sidecars are preserved. The resulting
rollout is awaited before IAM operations and ingress publication.

Installing missing probes causes a rolling restart of the single SeaweedFS pod
and a temporary storage interruption. Repeating reconciliation without missing
probes does not patch or restart the pod. An existing OnDelete workload requiring
new probes is rejected with an explicit operator-managed rollout requirement.
The operator does not delete its pod or change its rollout policy automatically.

The Filer root probe establishes HTTP listener readiness. It does not prove S3
authorization, backend durability, application acceptance or high availability.
Persisted IAM readback remains a separate mandatory check. Filer/master ports
remain private; Service exposure and NetworkPolicy restrictions are unchanged.

## Validation

- All 166 Python unit tests pass with the dependencies of the exact 0.9.0 image
  used for the WSL qualification. Twelve dedicated readiness tests cover timeout
  retries, tunnel recovery, error propagation, probe preservation and ordering.
- An isolated copy of the 0.9.0 laboratory using SeaweedFS 3.97 passed resume and
  coordinated SeaweedFS/operator restart checks. Repeated resume preserved the
  SeaweedFS pod UID. Only probe fields changed in its StatefulSet; all 22 PVC
  UIDs were preserved.
- The final laboratory candidate passed 12 synthetic S3 checks across Alpha and
  Beta: authenticated data/web round trips, anonymous scope and peer denial.
  Four owned synthetic objects were removed after the test. Both frontends
  returned HTTP 200. These are focused storage checks, not a full application
  regression suite.
- WSL-specific runtime evidence and candidate identities are retained separately
  from the earlier clean laboratory and historical startup logs. A first
  candidate exposed the inherited urllib3 connect-timeout gap; the final change
  adds coverage for it without weakening the IAM verifier.
- The operator-authorized WSL2 test on K3s 1.37.2 and SeaweedFS 3.97 passed both
  final-candidate resume and coordinated SeaweedFS/operator restart. The latter
  waited approximately six seconds for Filer HTTP availability and completed
  resume without a handler failure. All 18 persistent pods were Ready afterwards;
  all 11 PVC UIDs and SeaweedFS settings other than the missing probe fields were
  preserved. The final image was bound to the reviewed source hash. This WSL
  check did not read or modify application documents and is not full application
  acceptance.

Validation was performed by one agent; no independent review is claimed.
