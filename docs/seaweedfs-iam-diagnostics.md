<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# Private Filer IAM verification diagnostics

Persisted anonymous grants still have to match the public web allowlist exactly.
Failure raises `RuntimeError` and stops reconciliation before ingress publication.
The readiness wait and retry ordering remain those of the existing deployment
flow; this diagnostic change does not retry or accept an invalid policy.

Errors keep their original message prefix and add a safe, fixed classification:

```text
Could not verify anonymous S3 web-only grants [phase=read_policy category=http_error status=503]
```

| Category | Phase | Meaning |
| --- | --- | --- |
| `transport_timeout` | `read_policy` | Request connection/read timeout |
| `transport_error` | `read_policy` | Other request/connection error |
| `http_error` | `read_policy` | HTTP error; includes validated numeric status or `unknown` |
| `json_error` | `decode_policy` | Response is not decodable JSON |
| `schema_error` | `validate_policy` | Invalid IAM document/action structure |
| `anonymous_identity` | `validate_policy` | Missing or duplicated anonymous identity |
| `grant_mismatch` | `validate_policy` | Persisted grants differ from the exact expected set |

Response bodies, exception messages, URLs, credentials, expected bucket names and
IAM documents are not included. Underlying exception chaining is suppressed.
Consumers must accept the old generic message too; its cause is unclassified.
An observed error in historical logs alone does not establish present health or
the outcome of the handler's subsequent retry.

The unit suite covers valid/scoped policies, malformed documents, duplicated
identities, incorrect grants, transport failures and safe diagnostic output.
Normal and optimized Python runs pass the 167-test suite. Runtime qualification
uses synthetic loopback HTTP responses and a read-only check of the actual Filer
policy; synthetic invalid policies are never installed in the real datastore.

On Linux AMD64 WSL2, the exact candidate module passed nine synthetic loopback
cases plus the actual policy readback. Operator resume succeeded, all 18
persistent pods remained Ready, and all 11 PVC UIDs were preserved. No historical
Job or pod was removed. This is focused diagnostic/readback qualification, not
full application acceptance, fresh-installation or ARM64 qualification.
