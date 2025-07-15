import os
import kopf
import nuvolaris.config as cfg
import nuvolaris.couchdb as couchdb

@kopf.on.create('nuvolaris.org', 'v1', 'couchdbinstances')
def create_couchdb(spec, meta, status, body, **kwargs):
    print("🚀 Invocato handler create_couchdb")

    # ✅ imposta il namespace nella config necessario per `kube.apply`
    #cfg.put("nuvolaris.kube.namespace", meta["namespace"])  
    cfg.put("nuvolaris.kube.namespace", os.environ.get("NUVOLARIS_KUBE_NAMESPACE", meta["namespace"]))

    # prepara ownerReference completo (senza questo fallisce il kubectl apply -f -)
    owner_ref = {
        "apiVersion": "nuvolaris.org/v1",
        "kind": "CouchdbInstance",
        "name": meta["name"],
        "uid": meta["uid"],
        "controller": True,
        "blockOwnerDeletion": True
    }

    # passa l’owner correttamente formato alla funzione
    return couchdb.create(owner=owner_ref)

@kopf.on.resume('nuvolaris.org', 'v1', 'couchdbinstances')
def resume_couchdb(spec, meta, status, body, **kwargs):
    print("📦 Ripristino da resume_couchdb")
    cfg.put("nuvolaris.kube.namespace", meta["namespace"])
    owner_ref = {
        "apiVersion": "nuvolaris.org/v1",
        "kind": "CouchdbInstance",
        "name": meta["name"],
        "uid": meta["uid"],
        "controller": True,
        "blockOwnerDeletion": True
    }
    return couchdb.create(owner=owner_ref)
