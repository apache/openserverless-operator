# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
import kopf, os, logging, json
import nuvolaris.kustomize as kus
import nuvolaris.kube as kube
import nuvolaris.couchdb_util as cu
import nuvolaris.config as cfg
import nuvolaris.couchdb_util
import nuvolaris.util as util
import pprint

from nuvolaris.user_config import UserConfig
from nuvolaris.user_metadata import UserMetadata

from jinja2 import Environment, FileSystemLoader
loader = FileSystemLoader(["./nuvolaris/templates", "./nuvolaris/files"])
env = Environment(loader=loader)

logging.basicConfig(level=logging.DEBUG)


def update_templated_doc(db, database, template, data):
    #tpl = env.get_template(template)
    #doc = json.loads(tpl.render(data))
    #return db.update_doc(database, doc)

    tpl = env.get_template("couchdb-init.yaml")
    rendered = tpl.render(data)
    logging.info("🧪 TEMPLATE RENDERED:\n", rendered)
    doc = json.loads(rendered)




def create(owner=None):
    import pprint
    import os
    import json
    import logging
    import time

    logging.info("🚀 Avvio creazione CouchDB")

    runtime = cfg.get('nuvolaris.kube')
    u = cfg.get('couchdb.admin.user', "COUCHDB_ADMIN_USER", "whisk_admin")
    p = cfg.get('couchdb.admin.password', "COUCHDB_ADMIN_PASSWORD", "some_passw0rd")
    user = f"db_username={u}"
    pasw = f"db_password={p}"

    img = os.environ.get("OPERATOR_IMAGE", "couchdb-operator")
    tag = os.environ.get("OPERATOR_TAG", "latest")
    image = f"{img}:{tag}"
    logging.info("🎯 Operator image: %s", image)

    container_image = (
        "ghcr.io/nuvolaris/couchdb:2.3.1-nuvolaris.23101915"
        if runtime == "openshift"
        else "apache/couchdb:2.3"
    )

    config = json.dumps(cfg.getall())
    logging.info("📦 Config: %s", config)

    owner_namespace = cfg.get("nuvolaris.kube.namespace", "nuvolaris")
    if owner and owner.get("namespace"):
        owner_namespace = "nuvolaris"  # forzato

    data = {
        "runtime": runtime,
        "container_image": container_image,
        "image": image,
        "namespace": "nuvolaris",
        "config": config,
        "name": "couchdb",
        "container": "couchdb",
        "size": cfg.get("couchdb.volume-size", "COUCHDB_VOLUME_SIZE", 10),
        "dir": "/opt/couchdb/data",
        "storageClass": cfg.get("nuvolaris.storageclass"),
        "container_cpu_req": cfg.get('configs.couchdb.resources.cpu-req') or "500m",
        "container_cpu_lim": cfg.get('configs.couchdb.resources.cpu-lim') or "1",
        "container_mem_req": cfg.get('configs.couchdb.resources.mem-req') or "1G",
        "container_mem_lim": cfg.get('configs.couchdb.resources.mem-lim') or "2G",
        "container_manage_resources": cfg.exists('configs.couchdb.resources.cpu-req'),
        "index": "1",
        "replicationRole": "primary",
        "appName": "nuvolaris-couchdb"
    }

    import uuid
    data["uuid"] = str(uuid.uuid4())[:8]

    # Aggiunta safe di `meta`
    if owner:
        data["meta"] = {
            "name": owner.get("name", ""),
            "uid": owner.get("uid", "")
        }
    else:
        data["meta"] = {
            "name": "couchdb",
            "uid": "00000000-0000-0000-0000-000000000000"
        }

    if not data.get("image"):
        raise ValueError("❌ 'image' mancante nel dizionario 'data'")

    tplp = ["set-attach.yaml"]
    util.couch_affinity_tolerations_data(data)
    if data.get("affinity") or data.get("tolerations"):
        tplp.append("affinity-tolerance-sts-core-attach.yaml")

    kus.processTemplate("couchdb", "couchdb-set-tpl.yaml", data, "couchdb-set_generated.yaml")
    gen_file_path = "deploy/couchdb/couchdb-set_generated.yaml"
    exists = os.path.exists(gen_file_path)
    logging.info("🧪 File generato: %s esiste? %s", gen_file_path, exists)

    kust = kus.secretLiteral("couchdb-auth", user, pasw)
    kust += kus.patchTemplates("couchdb", tplp, data)

    logging.info("📋 Config completa passata a NUVOLARIS_CONFIG:")
    logging.info(json.dumps(cfg.getall(), indent=2))

    spec = kus.restricted_kustom_list(
        "couchdb",
        kust,
        templates=[
            "couchdb-init.yaml",
            "couchdb-svc.yaml"
        ],
        templates_filter=[
            "couchdb-set_generated.yaml",
            "couchdb-init.yaml",
            "couchdb-svc.yaml"
        ],
        data=data
    )

    job_found = any(i.get("kind") == "Job" for i in spec.get("items", []))
    logging.info("🔍 Il Job è stato generato dal kustom_list? %s", job_found)

    logging.info("🧪 DEBUG owner:\n%s", pprint.pformat(owner))
    logging.info("🧪 DEBUG: quante risorse contiene il kustom list? %d", len(spec.get("items", [])))

    for i, item in enumerate(spec.get("items", [])):
        logging.info("🔹 [%d] Kind: %s - Name: %s - Namespace: %s", i, item.get("kind"), item.get("metadata", {}).get("name"), item.get("metadata", {}).get("namespace"))
        if item.get("kind") == "Job":
            logging.info("🧪 DEBUG FULL JOB YAML:\n%s", json.dumps(item, indent=2))
            spec_job = item.get("spec", {}).get("template", {}).get("spec", {})
            if "initContainers" in spec_job:
                logging.info("✅ Job ha initContainers.")
            else:
                logging.warning("⚠️ Job NON ha initContainers!")

    res = True
    pod_namespace = None

    for item in spec.get("items", []):
        metadata = item.setdefault("metadata", {})
        item_namespace = metadata.setdefault("namespace", owner_namespace)

        if owner and item_namespace == owner_namespace:
            owner_ref = {
                "apiVersion": owner.get("apiVersion"),
                "kind": owner.get("kind"),
                "name": owner.get("name"),
                "uid": owner.get("uid"),
                "controller": True,
                "blockOwnerDeletion": True
            }
            references = metadata.setdefault("ownerReferences", [])
            if not any(ref.get("uid") == owner_ref["uid"] for ref in references):
                references.append(owner_ref)

        logging.info("🧪 Applying resource: %s/%s in namespace: %s", item["kind"], metadata["name"], item_namespace)
        logging.info("🧪 Full resource:\n%s", json.dumps(item, indent=2))

        result = kube.apply(item, namespace=item_namespace)
        logging.info("✅ kube.apply result = %s", str(result))
        if not result:
            logging.warning("❌ kube.apply fallito per %s/%s", item["kind"], metadata["name"])
            res = False

        if item.get("kind") == "StatefulSet":
            pod_namespace = item_namespace

    if pod_namespace:
        logging.info("⏳ Attendo 5 secondi per permettere la creazione del pod da parte dello StatefulSet...")
        time.sleep(5)
        logging.info("🕒 Attendo pod 'nuvolaris-couchdb' nel namespace: %s", pod_namespace)
        util.wait_for_pod_ready(
            "{.items[?(@.metadata.labels.app == 'nuvolaris-couchdb')].metadata.name}",
            namespace=pod_namespace
        )
    else:
        logging.warning("⚠️ Nessun StatefulSet trovato: skip wait_for_pod_ready")

    return res









def delete():
    spec = cfg.get("state.couchdb.spec")
    res = False
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete couchdb: {res}")
    return res

def check(f, what, res):
    if f:
        logging.info(f"OK: {what}")
        return res and True
    else:
        logging.warn(f"ERR: {what}")
        return False

def init_system(db):
    res = check(db.wait_db_ready(60), "wait_db_ready", True)
    res = check(db.configure_single_node(), "configure_single_node", res)
    res = check(db.configure_no_reduce_limit(), "configure_no_reduce_limit", res)
    cuser = cfg.get('couchdb.controller.user', "COUCHDB_CONTROLLER_USER", "controller_admin")
    cpasw = cfg.get('couchdb.controller.password', "COUCHDB_CONTROLLER_PASSWORD", "s0meP@ass1")
    iuser = cfg.get('couchdb.invoker.user', "COUCHDB_INVOKER_USER", "invoker_admin")
    ipasw = cfg.get('couchdb.invoker.password', "COUCHDB_INVOKER_PASSWORD", "s0meP@ass2")
    res = check(db.add_user(cuser, cpasw), "add_user: controller", res)
    return check(db.add_user(iuser, ipasw), "add_user: invoker", res)

def init_subjects(db):
    subjects_design_docs = [
        "auth_design_document_for_subjects_db_v2.0.0.json",
        "filter_design_document.json",
        "namespace_throttlings_design_document_for_subjects_db.json"]
    dbn = "subjects"
    res = check(db.wait_db_ready(60), "wait_db_ready", True)
    res = check(db.create_db(dbn), "create_db: subjects", res)
    members = [cfg.get('couchdb.controller.user'), cfg.get('couchdb.invoker.user')]
    res = check(db.add_role(dbn, members), "add_role: subjects", res)
    for i in subjects_design_docs:
        res = check(update_templated_doc(db, dbn, i, {}), f"add {i}", res)
    return res

def init_activations(db):
    activations_design_docs = [
        "whisks_design_document_for_activations_db_v2.1.0.json",
        "whisks_design_document_for_activations_db_filters_v2.1.1.json",
        "filter_design_document.json",
        "activations_design_document_for_activations_db.json",
        "logCleanup_design_document_for_activations_db.json"
    ]
    dbn = "activations"
    res = check(db.wait_db_ready(60), "wait_db_ready", True)
    res = check(db.create_db(dbn), "create_db: activations", res)
    members = [cfg.get('couchdb.controller.user'), cfg.get('couchdb.invoker.user')]
    res = check(db.add_role(dbn, members), "add_role: activations", res)
    for i in activations_design_docs:
        res = check(update_templated_doc(db, dbn, i, {}), f"add {i}", res)
    return res

def init_actions(db):
    whisks_design_docs = [
        "whisks_design_document_for_entities_db_v2.1.0.json",
        "filter_design_document.json"
    ]
    dbn = "whisks"
    res = check(db.wait_db_ready(60), "wait_db_ready", True)
    res = check(db.create_db(dbn), "create_db: whisks", res)
    members = [cfg.get('couchdb.controller.user'), cfg.get('couchdb.invoker.user')]
    res = check(db.add_role(dbn, members), "add_role: actions", res)
    for i in whisks_design_docs:
        res = check(update_templated_doc(db, dbn, i, {}), f"add {i}", res)
    return res

def add_initial_subjects(db):
    res = check(db.wait_db_ready(60), "wait_db_ready", True)
    dbn = "subjects"
    for _, (name, value) in enumerate(cfg.getall("openwhisk.namespaces").items()):
        [uuid, key] = value.split(":")
        basename = name.split(".")[-1]
        data = { "name": basename, "key": key, "uuid": uuid}
        res = check(update_templated_doc(db, dbn, "subject.json", data), f"add {name}", res)
    return res

def init():
    # load nuvolaris config from the named crd
    config = os.environ.get("NUVOLARIS_CONFIG")
    if config:
        import logging
        logging.basicConfig(level=logging.INFO)
        spec = json.loads(config)
        cfg.configure(spec)
        for k in cfg.getall(): logging.info(f"{k} = {cfg.get(k)}")

    # dynamically detect couchdb pod and wait for readiness
    util.wait_for_pod_ready("{.items[?(@.metadata.labels.name == 'couchdb')].metadata.name}")

    db = nuvolaris.couchdb_util.CouchDB()
    res = check(init_system(db), "init_system", True)
    res = check(init_subjects(db), "init_subjects", res) 
    res = check(init_activations(db), "init_activations", res)
    res = check(init_actions(db), "init_actions", res)
    res = check(add_initial_subjects(db), "add_subjects", res)
    res = check(init_users_metadata(db), "init_users_metadata", res)
    res = check(init_compactions_config(db), "init_compactions_config", res)

    # job process status code should be negated if the job is successfull
    return not res

def add_subject(db, namespace, auth):
    """
    Add a new Openwhisk Couchdb subject that will be authorized to interact with the specified Openwhisk namespace.
    the auth parameters represents the subject authentication in the form of a uuid.uuid4():randomstr(64)
    """
    res = check(db.wait_db_ready(60), "wait_db_ready", True)
    dbn = "subjects"
    [uuid, key] = auth.split(":")
    data = { "name": namespace, "key": key, "uuid": uuid}
    return check(update_templated_doc(db, dbn, "subject.json", data), f"add {namespace}", res)

def init_users_metadata(db):
    """
    Add a new Openwhisk Couchdb database to host nuvolaris user relevant informations
    """
    dbn = "users_metadata"
    res = check(db.wait_db_ready(60), "wait_db_ready", True)
    res = check(db.create_db(dbn), "create_db: user_metadata", res)
    return res 

def init_compactions_config(db):
    """
    Activate the compactions config for the nuvolaris related databases
    """
    res = check(db.wait_db_ready(60), "wait_db_ready", True)
    res = check(db.enable_db_compaction("users_metadata"), "enable_db_compaction: user_metadata", res)
    res = check(db.enable_db_compaction("users_subjects"), "enable_db_compaction: subjects", res)
    res = check(db.enable_db_compaction("whisks"), "enable_db_compaction: whisks", res)
    return res        

def create_ow_user(ucfg: UserConfig, user_metadata: UserMetadata):
    subject = ucfg.get("namespace")
    auth = ucfg.get("auth")

    logging.info(f"authorizing OpenWhisk namespace {subject}")

    try:
        db = nuvolaris.couchdb_util.CouchDB()

        if(util.validate_ow_auth(auth)):
            logging.info(f"{subject} authorization is valid, adding subject")
            res = add_subject(db, subject, auth)

            if(res):
                user_metadata.add_metadata("AUTH",auth)

            return res    
        else:
            return None
    except Exception as e:
        logging.error(f"failed to authorize Openwhisk namespace {subject} authorization id and key: {e}")
        return None

def delete_ow_user(subject):
    logging.info(f"removing auhorization for OpenWhisk namespace {subject}")

    try:
        db = nuvolaris.couchdb_util.CouchDB()
        selector = {"selector":{"subject": {"$eq": subject }}}
        response = db.find_doc("subjects", json.dumps(selector))

        if(response['docs']):
                docs = list(response['docs'])
                if(len(docs) > 0):
                    doc = docs[0]
                    logging.info(f"removing subjects documents {doc['_id']}")
                    return db.delete_doc("subjects",doc['_id'])
        
        logging.warn(f"auhorization for OpenWhisk namespace {subject} not found!")
        return None
    except Exception as e:
        logging.error(f"failed to remove Openwhisk namespace {subject} authorization id and key: {e}")
        return None

    
    

