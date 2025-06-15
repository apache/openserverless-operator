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
import time

import kopf, logging
import nuvolaris.kube as kube
import nuvolaris.kustomize as kus
import nuvolaris.config as cfg
import nuvolaris.util as util
import nuvolaris.operator_util as operator_util
import nuvolaris.minio_util as mutil
import nuvolaris.openwhisk as openwhisk

from nuvolaris.milvus_admin_client import MilvusAdminClient
from nuvolaris.user_config import UserConfig
from nuvolaris.user_metadata import UserMetadata


def patchEntries(data: dict):
    src_folder = "milvus"
    if data['slim']:
        src_folder += "-slim"
        tplp = ["milvus-cfg-slim-base.yaml"]
    else:
        tplp = ["milvus-cfg-base.yaml"]
    
    tplp.append("milvus.yaml")

    if (data['affinity'] or data['tolerations']):
        tplp.append("affinity-tolerance-dep-core-attach.yaml")

    kust = kus.patchTemplates(src_folder, tplp, data)
    kust += kus.patchGenericEntry("Secret", "nuvolaris-milvus-etcd-secret", "/data/username",
                                  util.b64_encode(data['milvus_etcd_username']))
    kust += kus.patchGenericEntry("Secret", "nuvolaris-milvus-etcd-secret", "/data/password",
                                  util.b64_encode(data['milvus_etcd_password']))
    
    kust += kus.patchGenericEntry("Secret", "nuvolaris-milvus-s3-secret", "/stringData/accesskey",
                                  data['milvus_s3_username'])
    kust += kus.patchGenericEntry("Secret", "nuvolaris-milvus-s3-secret", "/stringData/secretkey",
                                  data['milvus_s3_password'])

    
    kust += kus.patchGenericEntry("PersistentVolumeClaim", "nuvolaris-milvus", "/spec/storageClassName",
                                  data['storageClass'])
    kust += kus.patchGenericEntry("PersistentVolumeClaim", "nuvolaris-milvus", "/spec/resources/requests/storage",
                                  f"{data['size']}Gi")

    if not data["slim"]:
        kust += kus.patchGenericEntry("PersistentVolumeClaim", "nuvolaris-milvus-zookeeper", "/spec/storageClassName",
                                    data['storageClass'])
        kust += kus.patchGenericEntry("PersistentVolumeClaim", "nuvolaris-milvus-zookeeper",
                                    "/spec/resources/requests/storage", f"{data['zookeeper_size']}Gi")

        kust += kus.patchGenericEntry("PersistentVolumeClaim", "nuvolaris-milvus-bookie-journal", "/spec/storageClassName",
                                    data['storageClass'])
        kust += kus.patchGenericEntry("PersistentVolumeClaim", "nuvolaris-milvus-bookie-journal",
                                    "/spec/resources/requests/storage", f"{data['bookie_journal_size']}Gi")

        kust += kus.patchGenericEntry("PersistentVolumeClaim", "nuvolaris-milvus-bookie-ledgers", "/spec/storageClassName",
                                    data['storageClass'])
        kust += kus.patchGenericEntry("PersistentVolumeClaim", "nuvolaris-milvus-bookie-ledgers",
                                    "/spec/resources/requests/storage", f"{data['bookie_ledgers_size']}Gi")
    return kust


def create(owner=None):
    """
    Deploys the milvus vector db in standalone mode.
    """
    data = util.get_milvus_config_data()
    res = create_milvus_accounts(data)
    dir = "milvus"
    if res:
        if data['slim']:
            dir += "-slim"
        
        logging.info(f"*** creating a {dir} standalone instance")

        kust = patchEntries(data)
        mspec = kus.kustom_list(dir, kust, templates=[], data=data)

        if owner:
            kopf.append_owner_reference(mspec['items'], owner)
        else:
            cfg.put("state.milvus.spec", mspec)

        kube.apply(mspec)
        util.wait_for_pod_ready(
            r"{.items[?(@.metadata.labels.app\.kubernetes\.io\/instance == 'nuvolaris-milvus')].metadata.name}")

        milvus_api_host = cfg.get("milvus.host", "MILVUS_API_HOST", "nuvolaris-milvus")
        milvus_api_port = cfg.get("milvus.host", "MILVUS_API_PORT", "19530")

        logging.info("*** waiting for milvus api to be available")
        util.wait_for_http(f"http://{milvus_api_host}:{milvus_api_port}", up_statuses=[200,401], timeout=30)

        res = create_default_milvus_database(data)
        logging.info("*** created a milvus standalone instance")


    return res


def create_milvus_accounts(data: dict):
    """"
    Creates technical accounts for ETCD and MINIO
    """
    try:
        # currently we use the ETCD root password, so we skip the ETCD user creation.
        # res = util.check(etcd.create_etcd_user(data['milvus_etcd_username'],data['milvus_etcd_password'],data['milvus_etcd_prefix']),"create_etcd_milvus_user",True)

        minioClient = mutil.MinioClient()
        bucket_policy_names = []
        bucket_policy_names.append(f"{data['milvus_bucket_name']}/*")

        res = util.check(minioClient.add_user(data["milvus_s3_username"], data["milvus_s3_password"]),
                         "create_milvus_s3_user", True)
        res = util.check(minioClient.make_bucket(data["milvus_bucket_name"]), "create_milvus_s3_bucket", res)
        return util.check(minioClient.assign_rw_bucket_policy_to_user(data["milvus_s3_username"], bucket_policy_names),
                          "assign_milvus_s3_bucket_policy", res)
    except Exception as ex:
        logging.error("Could not create milvus ETCD and MINIO accounts", ex)
        return False


def create_default_milvus_database(data):
    """
    Creates nuvolaris MILVUS custom resources
    """
    logging.info("*** configuring MILVUS database for nuvolaris")
    adminClient = MilvusAdminClient()
    res = adminClient.setup_user("nuvolaris", data["nuvolaris_password"], "nuvolaris")

    if (res):
        _annotate_nuv_milvus_metadata(data)
        logging.info("*** configured MILVUS database for nuvolaris")
        return True

    return False


def _annotate_nuv_milvus_metadata(data):
    """
    annotate nuvolaris configmap with entries for MILVUS connectivity MILVUS_HOST, MILVUS_PORT, MILVUS_TOKEN, MILVUS_DB_NAME
    this is becasue MINIO
    """
    try:
        milvus_service = util.get_service(
            r"{.items[?(@.metadata.labels.app\.kubernetes\.io\/instance == 'nuvolaris-milvus')]}")
        if (milvus_service):
            milvus_host = f"{milvus_service['metadata']['name']}.{milvus_service['metadata']['namespace']}.svc.cluster.local"
            password = data["nuvolaris_password"]

            openwhisk.annotate(f"milvus_host={milvus_host}")
            openwhisk.annotate(f"milvus_token=nuvolaris:{password}")
            openwhisk.annotate("milvus_db_name=nuvolaris")

            ports = list(milvus_service['spec']['ports'])
            for port in ports:
                if (port['name'] == 'milvus'):
                    openwhisk.annotate(f"milvus_port={port['port']}")
        return None
    except Exception as e:
        logging.error(f"failed to annotate MILVUS for nuvolaris: {e}")
        return None


def _add_milvus_user_metadata(ucfg: UserConfig, user_metadata: UserMetadata):
    """
    adds entries for MILVUS connectivity MILVUS_HOST, MILVUS_PORT, MILVUS_TOKEN, MILVUS_DB_NAME    
    """

    try:
        milvus_service = util.get_service(
            r"{.items[?(@.metadata.labels.app\.kubernetes\.io\/instance == 'nuvolaris-milvus')]}")

        if (milvus_service):
            milvus_host = f"{milvus_service['metadata']['name']}.{milvus_service['metadata']['namespace']}.svc.cluster.local"
            milvus_token = f"{ucfg.get('namespace')}:{ucfg.get('milvus.password')}"
            user_metadata.add_metadata("MILVUS_HOST", milvus_host)
            user_metadata.add_metadata("MILVUS_TOKEN", milvus_token)
            user_metadata.add_metadata("MILVUS_DB_NAME", ucfg.get('milvus.database'))

            ports = list(milvus_service['spec']['ports'])
            for port in ports:
                if (port['name'] == 'milvus'):
                    user_metadata.add_metadata("MILVUS_PORT", port['port'])

        return None
    except Exception as e:
        logging.error(f"failed to build MILVUS metadata for {ucfg.get('namespace')}: {e}")
        return None


def create_ow_milvus(ucfg: UserConfig, user_metadata: UserMetadata, owner=None):
    logging.info(f"*** configuring MILVUS database for {ucfg.get('namespace')}")

    adminClient = MilvusAdminClient()
    username = ucfg.get("namespace")
    password = ucfg.get("milvus.password")
    database = ucfg.get("milvus.database")
    res = adminClient.setup_user(username, password, database)

    if (res):
        _add_milvus_user_metadata(ucfg, user_metadata)
        logging.info(f"*** configured MILVUS database linked to namespace {ucfg.get('namespace')}")

    return res


def delete_ow_milvus(ucfg):
    logging.info(f"removing MILVUS database {ucfg.get('namespace')}")
    adminClient = MilvusAdminClient()
    res = adminClient.remove_user(ucfg.get('namespace'), ucfg.get('milvus.database'))

    if res:
        logging.info(f"removed MILVUS database linked to namespace {ucfg.get('namespace')}")

    return res


def delete_by_owner():
    spec = kus.build("milvus")
    res = kube.delete(spec)
    logging.info(f"delete milvus: {res}")
    return res


def delete_by_spec():
    spec = cfg.get("state.milvus.spec")
    if spec:
        res = kube.delete(spec)
        logging.info(f"delete milvus: {res}")
        return res


def delete(owner=None):
    if owner:
        return delete_by_owner()
    else:
        return delete_by_spec()


def patch(status, action, owner=None):
    """
    Called by the operator patcher to create/delete milvus component
    """
    try:
        logging.info(f"*** handling request to {action} milvus")
        if action == 'create':
            msg = create(owner)
            operator_util.patch_operator_status(status, 'milvus', 'on')
        else:
            msg = delete(owner)
            operator_util.patch_operator_status(status, 'milvus', 'off')

        logging.info(msg)
        logging.info(f"*** handled request to {action} milvus")
    except Exception as e:
        logging.error('*** failed to update milvus: %s' % e)
        operator_util.patch_operator_status(status, 'milvus', 'error')
