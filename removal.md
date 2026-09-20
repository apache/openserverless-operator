# Plan: Remove MongoDB support (retain FerretDB)

Status: **implemented**. Option A (keep `mongodb.*` names) was chosen; see
[Decision required](#decision-required). Also includes the qdrant and s3ninja
removal in the [addendum](#addendum-qdrant-and-s3ninja-removal).

Scope: the `oplugins-op` repository (Apache OpenServerless operator).

## Summary

Remove the native MongoDB deployment support — both the *standalone* StatefulSet flavour
and the *community operator* flavour — while keeping FerretDB, which provides the
MongoDB wire-protocol interface backed by PostgreSQL.

## Key finding: this code is already unreachable

Every live entry point was switched to FerretDB at some earlier point, via an
import alias that keeps the old name:

| File | Line | Import |
|---|---|---|
| `openserverless/main.py` | 28 | `import openserverless.ferretdb as mongodb` |
| `openserverless/patcher.py` | 20 | `import openserverless.ferretdb as mongodb` |
| `openserverless/user_handlers.py` | 27 | `import openserverless.ferretdb as mdb` |

Consequently `mongodb.create(owner)` at `main.py:196` and `mongodb.patch(...)` at
`patcher.py:132` both dispatch to **FerretDB**, not to MongoDB.

No production module imports `openserverless.mongodb`. The only importers are three
test notebooks under `tests/kind/`. The three MongoDB Python modules and all their
Kubernetes descriptors are dead code at runtime.

**Implication:** this is a low-risk deletion. It is not a behavioural change to a
running cluster, because none of the deleted code executes today. The main risk is
in the shared *configuration surface*, not in the code — see
[Decision required](#decision-required).

The `as mongodb` aliases are actively misleading and should be renamed as part of
this work, so the code says what it does.

## FerretDB is independent

`openserverless/ferretdb.py` depends on `postgres_operator` and
`util.get_postgres_config_data()`. It shares **no** code with the MongoDB modules.
It owns its own descriptors in `deploy/ferretdb/` and its own template
`openserverless/templates/ferretdb-sts.yaml`. No MongoDB template appears in any
FerretDB `patchTemplates` list.

The boundary is clean; nothing below needs FerretDB to be modified to compensate.

## Removal steps

### 1. Delete Python modules

- `openserverless/mongodb.py`
- `openserverless/mongodb_operator.py`
- `openserverless/mongodb_standalone.py`

### 2. Delete Kubernetes descriptors

Directories:

- `deploy/mongodb-operator/` — CustomResourceDefinition, operator Deployment, RBAC
  (2x ServiceAccount, 2x Role, 2x RoleBinding)
- `deploy/mongodb-operator-deploy/` — `MongoDBCommunity` CR, 2x Secret, Service
- `deploy/mongodb-standalone/` — Secret, ConfigMap, PVC, StatefulSet, Service

Templates under `openserverless/templates/`:

- `mongodb-auth.yaml`
- `mongodb-auth-openserverless.yaml`
- `mongodb-cm.yaml`
- `mongodb-config.yaml`
- `mongodb-sts.yaml`
- `mongodb_manage_user_tpl.js`

Keep `deploy/ferretdb/` and `openserverless/templates/ferretdb-sts.yaml`.

### 3. Rename the misleading aliases

In `main.py` and `patcher.py`, change `import openserverless.ferretdb as mongodb`
to `as ferretdb`, and update the call sites (`main.py:196`, `main.py:333`,
`patcher.py:132`). In `user_handlers.py` the alias `mdb` is neutral and can stay.

This is a pure rename with no behavioural effect, but it is what stops the next
reader concluding that MongoDB is still deployed.

### 4. Remove the now-unused config helper

`util.get_mongodb_config_data()` (`openserverless/util.py:306-317`) is called only
by the three deleted modules. Delete it.

Note it is *not* the same as `get_postgres_config_data()`, which FerretDB uses and
which must stay.

### 5. Tests

- Delete `tests/kind/mongodb_op_test.ipy` and `tests/kind/mongodb_std_test.ipy`.
- Delete `tests/kind/mongodb_user_test.ipy` — see the coverage gap below.
- `TaskfileTest.yml:160-161` reads the `mongodb_url` annotation. **Keep it**:
  FerretDB still writes that annotation (`ferretdb.update_system_cm_for_mdb`).

### 6. TaskfileDev.yml

Delete the `mongodb:` task (`TaskfileDev.yml:93-95`). It applies
`deploy/mongodb-operator` and `deploy/mongodb` — the latter does not exist, so the
task is already broken.

## Test coverage gap (needs attention)

`tests/kind/mongodb_user_test.ipy` cannot simply be repointed at FerretDB. It calls
`mdb.create()`, sets `mongodb.useOperator`, and asserts on the
`openserverless.mongodb.flavour == "standalone"` pod label — all specific to the
standalone MongoDB deployment being removed.

More importantly, `tests/kind/ferretdb_test.ipy` **is entirely commented out**, and
even when re-enabled it only covers `create`/`delete` — it never exercises
`create_db_user` / `delete_db_user`.

So deleting the MongoDB tests leaves the FerretDB **user-provisioning path with no
test coverage at all**, despite that path being live in `user_handlers.py:79-84`
and `:133-135`.

Recommended: before or alongside the deletion, port the user-provisioning
assertions from `mongodb_user_test.ipy` into `ferretdb_test.ipy` (against
`ferretdb.create_db_user` / `delete_db_user`, which need a running PostgreSQL) and
uncomment that file. Otherwise this removal is a net loss of coverage.

## Decision required

Two config surfaces are **shared with FerretDB** and cannot simply be deleted:

| Key | Still used by |
|---|---|
| `components.mongodb` | Gates FerretDB (`main.py:195`) and PostgreSQL (`main.py:188`) |
| `mongodb.enabled`, `mongodb.database`, `mongodb.password` | `ferretdb.create_db_user()` |
| `mongodb.volume-size` | `ferretdb.enrich_ferretdb_data()` |
| `MONGODB_URL` annotation / user metadata | Emitted by FerretDB |

Only these two become genuinely unused:

- `mongodb.useOperator`
- `mongodb.exposedExternally`

They appear in `deploy/openserverless-permissions/whisk-crd.yaml:225-229` and are
set to `False` in roughly 30 test fixtures under `tests/`.

### Option A — keep `mongodb.*` names (CHOSEN)

Drop only `useOperator` and `exposedExternally` from the CRD and the fixtures.
Keep everything else as the stable user-facing API.

**As implemented, this went slightly further than planned.** Once
`get_mongodb_config_data()` was deleted, `mongodb.host`, `mongodb.admin` and
`mongodb.openserverless` also had no remaining readers, so they were removed from
the CRD too. The CRD's `required:` list named `host`, `admin` and `openserverless`,
so leaving it untouched would have made every existing `whisk.yaml` fail validation;
the list was reduced to `volume-size` and
`x-kubernetes-preserve-unknown-fields: true` was added to the `mongodb` object so
manifests still carrying the old keys are accepted rather than rejected. 32 fixtures
were updated. `mongodb.volume-size` is retained (read by
`ferretdb.enrich_ferretdb_data()`).

Rationale: FerretDB deliberately presents a MongoDB-compatible interface, so the
naming remains accurate. Renaming would break every existing user `whisk.yaml` for
no functional gain.

### Option B — rename to `ferretdb.*` (not taken)

Rename `components.mongodb` -> `components.ferretdb` and `mongodb.*` -> `ferretdb.*`
throughout the CRDs, the operator code and all fixtures.

This is a **breaking change** to every deployed `whisk.yaml`. If chosen, it needs a
deprecation path: accept both spellings for at least one release, preferring the new
one, and log a warning on the old. Whether `MONGODB_URL` is also renamed is a
further, separately breaking question, since user actions read it.

## Suggested order

1. Port user-provisioning tests to `ferretdb_test.ipy` and enable it (closes the gap first).
2. Rename the `as mongodb` aliases (pure rename, independently reviewable).
3. Delete modules, descriptors, templates, `get_mongodb_config_data()`, tests, Taskfile task.
4. Apply the chosen config option from [Decision required](#decision-required).

## Verification

After the change:

- `grep -rn "openserverless.mongodb\|mongodb_operator\|mongodb_standalone" --include="*.py" .`
  returns nothing.
- `grep -rn "get_mongodb_config_data" .` returns nothing.
- `deploy/` contains no `mongodb-*` directory; `deploy/ferretdb/` is intact.
- A kind deployment with `components.mongodb: true` still brings up
  `pod/openserverless-mongodb-0` (the FerretDB pod reuses that name and the
  `openserverless-mongodb-svc` Service) and still annotates `mongodb_url`.

## Addendum: qdrant and s3ninja removal

Folded into the same change, as unused components.

### qdrant

`deploy/qdrant/` (ConfigMap, StatefulSet, Service). Verified **zero** references
anywhere in the repository — no Python, no YAML, no Taskfile. Straight deletion.

### s3ninja

Not merely an unused directory: it had a live-looking but unreachable call chain,
all of which is removed.

- `deploy/s3ninja/` — StatefulSet, Service
- `openserverless/bucket.py` — its only content was `create()`/`delete()` calling
  `kustom_list("s3ninja")`
- the `import openserverless.bucket as bucket` line in `main.py` — the module was
  imported but **never called**
- `components.s3bucket` (always `false`) and its `# start s3ninja` comment, from
  `deploy/openserverless-operator/whisk.yaml` and 5 test fixtures

`components.s3bucket` was read by no Python code and was not declared in the CRD
schema, so removing it is not a schema change.

Deliberately **kept**: `openserverless/s3_bucket_policy.py` and the `S3BucketPolicy`
usage in `s3_client.py`. Despite the similar name these belong to the SeaweedFS
object-store path and are actively used.
