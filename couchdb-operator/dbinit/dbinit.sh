#!/bin/sh

echo "🔧 Inizializzazione CouchDB..."

curl -X PUT http://couchdb.nuvolaris.svc.cluster.local:5984/mydb

echo "✅ Inizializzazione completata."

