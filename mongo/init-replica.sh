#!/bin/sh
# Inicializa o replica set "rs0" com os 3 nós (mongo1, mongo2, mongo3).
# Roda dentro de um container descartável (serviço "mongo-init"): faz o trabalho e termina.
# É idempotente: se o replica set já existir, não faz nada.
set -eu

echo "[init] aguardando os 3 nós do MongoDB responderem..."
for h in mongo1 mongo2 mongo3; do
  until mongosh --host "$h" --port 27017 --quiet --eval 'db.adminCommand({ ping: 1 }).ok' >/dev/null 2>&1; do
    echo "[init] $h ainda não respondeu, tentando de novo em 2s..."
    sleep 2
  done
  echo "[init] $h respondeu"
done

cat > /tmp/init.js <<'EOF'
try {
  const st = rs.status();
  print("[init] replica set '" + st.set + "' já estava inicializado.");
} catch (e) {
  print("[init] inicializando o replica set rs0...");
  printjson(rs.initiate({
    _id: "rs0",
    members: [
      { _id: 0, host: "mongo1:27017", priority: 2 },
      { _id: 1, host: "mongo2:27017", priority: 1 },
      { _id: 2, host: "mongo3:27017", priority: 1 }
    ]
  }));
}
EOF

mongosh --host mongo1 --port 27017 --quiet --file /tmp/init.js

echo "[init] aguardando a eleição do nó PRIMARY..."
until mongosh "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0" --quiet \
      --eval 'quit(db.hello().isWritablePrimary ? 0 : 1)' >/dev/null 2>&1; do
  sleep 2
done
echo "[init] replica set pronto: há um PRIMARY eleito."
