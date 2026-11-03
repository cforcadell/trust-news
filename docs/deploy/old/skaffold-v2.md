# TrustNews Kubernetes Deployment Guide v2

> [!WARNING]
> **ARCHIVADO — NOT USE.** Historical reference; see
> [`README.md`](README.md) and runbooks are in place before operation.

This version reorganizes `skaffold.md` without replacing it. It maintains the original operating order:

1. Recrear cluster.
2. Crear namespaces.
3. Levantar blockchain.
4. Disclosure contract.
5. Levantar infraestructura.
6. Lift APIs and frontend.
7. Configure Keycloak, quotas and users.
8. Load functional configurations.
9. Consult data, endpoints and collections.
10. Maintenance operations.

---

## 1. Recrear Cluster Local

Use this section when you want to start from scratch. It is destructive: delete the `kind`, imagenes/volumenes Docker cluster unused and clean local space.

### 1.1 Inspeccion Previa

```bash
kubectl get pvc -A
docker volume ls
df -h /
```

### 1.2 Deleted from Cluster

```bash
kind delete cluster --name trust-news
```

### 1.3 Limpieza Local

```bash
docker system prune -a -f
sudo journalctl --vacuum-size=300M
sudo apt clean
sudo apt autoremove -y
docker volume prune -f

df -h /
docker volume ls
```

### 1.4 Cluster Creation

```bash
kind create cluster --name trust-news --config kind-config.yaml
```

---

## 2. Crear Namespaces

Run before any Skaffold profile.

```bash
cd ./scripts/k8s
./create-namespaces.sh
```

---

## 3. Desplegar Blockchain

Perfil Skaffold:

```bash
./skaffold dev -p blockchain --namespace blockchain
# ./skaffold dev -p blockchain --namespace blockchain --cleanup=false
```

### 3.1 See State

```bash
kubectl get pods -n blockchain
kubectl get pv -n blockchain
```

### 3.2 Logs

```bash
kubectl logs -n blockchain -f geth-bootnode-0
kubectl logs -n blockchain -f geth-rpc-endpoint-0
kubectl logs -n blockchain -f geth-miner-0
```

### 3.3 Procesos Geth

```bash
kubectl exec geth-bootnode-0 -n blockchain -- ps aux | grep geth
kubectl exec geth-rpc-endpoint-0 -n blockchain -- ps aux | grep geth
kubectl exec geth-miner-0 -n blockchain -- ps aux | grep geth
```

### 3.4 Pods Diagnostic

```bash
kubectl describe pod geth-bootnode-0 -n blockchain
kubectl describe pod geth-rpc-endpoint-0 -n blockchain
kubectl describe pod geth-miner-0 -n blockchain
```

### 3.5 Connect to the RPC Node

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555
```

Inside the console:

```javascript
admin.peers
net.peerCount
eth.blockNumber
```

Alternativa directa:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "admin.peers"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "eth.blockNumber"
```

### 3.6 Connect to Bootnode

```bash
kubectl exec -it geth-bootnode-0 -n blockchain -- ps aux
kubectl exec -it geth-bootnode-0 -n blockchain -- geth --exec "admin.nodeInfo.enode" attach ipc:/root/.ethereum/geth.ipc
```

### 3.7 Connect Al Miner

```bash
kubectl exec -it geth-miner-0 -n blockchain -- geth attach
```

Inside the console:

```javascript
admin.peers
net.peerCount
eth.blockNumber
```

Alternativa directa:

```bash
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "admin.peers"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "eth.blockNumber"
```

Check that `net.peerCount == 1` in RPC and miner, and that `eth.blockNumber` matches.

### 3.8 Anadir Peer Manualmente

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("enode://af28ee328bbab1085d8f3e6eef110001a4075da8513871091bb25c7111f57e4261270b26791b5d71d6fd9707c1efd4ca17db2010b73fcd7ff1c7cd3a6877531c@10.244.2.13:30304")'
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
```

### 3.9 Reiniciar Blockchain Conservando Volumenes

```bash
kubectl scale statefulset geth-bootnode --replicas=0 -n blockchain
kubectl scale statefulset geth-miner --replicas=0 -n blockchain
kubectl scale statefulset geth-rpc-endpoint --replicas=0 -n blockchain

kubectl scale statefulset --all --replicas=0 -n blockchain
kubectl scale statefulset --all --replicas=1 -n blockchain

kubectl get pods -n blockchain
```

---

## 4. Desplegar Smart Contract

Attention: If a new contract is deployed, `postId` returns to `0`. If there are previous data, delete or adjust Mongo to avoid inconsistencies.

```javascript
db.events.deleteMany({})
db.news.deleteMany({})
db.validations.deleteMany({})
```

### 4.1 Abrir RPC Local

```bash
kubectl port-forward svc/geth-rpc-endpoint 8555:8555 -n blockchain
```

### 4.2 Deploy Contract

```bash
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth
```

### 4.3 Fondear Cuentas

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555
```

Inside the console:

```javascript
eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "0xa28885a13a7b4d3561a7af64ea1ba0f82ed9f06b",
  value: web3.toWei(10, "ether")
})

eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "4504a1d4047583164919ae40c37c4f4c5b854bbb",
  value: web3.toWei(10, "ether")
})

eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "edbef53fc17dde65bf303b3d4983afb7028eb6eb",
  value: web3.toWei(10, "ether")
})

eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "be794abf86d173ddcfe937c6d8d739bdc4e94165",
  value: web3.toWei(10, "ether")
})

eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "42d488d0393fd1d6b72bb424db28dd7eb5e06737",
  value: web3.toWei(10, "ether")
})
```

### 4.4 Verifications of the Contract

```javascript
eth.pendingTransactions
eth.getBalance("0xa28885a13a7b4d3561a7af64ea1ba0f82ed9f06b")
```

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getCode("0x9eA62eb7944349C407B307025644E47bF22F8bCc")'
```

---

## 5. Desplegar Infraestructura

Perfiles Skaffold:

```bash
./skaffold dev -p infra
./skaffold dev -p infra-basic
```

Services displayed by Skaffold:

```text
Kafdrop: http://localhost:9000
Grafana: http://localhost:3000
Mongo Express: http://localhost:18081 
kubectl port-forward \
  --address 0.0.0.0 \
  -n infra svc/mongo-express \
  8081:8081 si se reompe el tunel)
```

### 5.1 See State

```bash
kubectl get pods -n infra
kubectl get svc -n infra
kubectl logs -n infra -f kafka-0
```

### 5.2 Restart StatefulSets From Infra

```bash
kubectl scale statefulset --all --replicas=0 -n infra
kubectl scale statefulset --all --replicas=1 -n infra
```

### 5.3 Delete PVCs From Infra

Use if you stop pods or remove StatefulSets old PVCs.

```bash
kubectl get pvc -n infra
kubectl delete pvc ipfs-storage-ipfs-0 -n infra
kubectl delete pvc kafka-data-kafka-0 -n infra
kubectl delete pvc mongodb-storage-mongodb-0 -n infra
```

### 5.4 Grafana and Loki

Datasource in Grafana:

```text
http://loki.infra.svc.cluster.local:3100
```

Then use `Explore` and `Run query`.

---

## 6. Deploy APIs & Frontend

Perfil Skaffold:

```bash
./skaffold dev -p apis-frontend
# ./skaffold dev -p apis-frontend --cache-artifacts=true --cleanup=false
```

### 6.1 See State

```bash
kubectl get pods -n apis
kubectl get pods -n frontend
kubectl logs -n apis -f
```

### 6.2 Frontend

If the port-forward doesn't get up:

```bash
kubectl port-forward svc/frontend-service -n frontend 7443:443
```

URLs principales:

```text
https://localhost:7443/
https://localhost:7443/backend/docs
https://localhost:7443/auth/admin/master/console/
```

If accessed from VM with host mapping:

```text
https://192.168.56.108:7443/
```

### 6.3 See Nginx Del Frontend

```bash
kubectl exec -it -n frontend frontend-web-5769696f49-dljlk -- cat /etc/nginx/conf.d/default.conf
```

---

## 7. Secrets and Base Configuration

### 7.1 Undercover Secrets & APIs

```bash
kubectl get secrets -n infra
kubectl get mongodb-secret -n infra -o jsonpath='{.data}'

kubectl get secrets -n apis
kubectl get secret mongodb-app-secret -n apis -o jsonpath='{.data}'
echo "x" | base64 --decode
```

### 7.2 Keycloak Sin Nginx

Si no lo abre Skaffold:

```bash
kubectl port-forward svc/keycloak --address 0.0.0.0 -n infra 7443:8443
```

Check:

```bash
curl -v -k https://localhost:7443/auth/admin/master/console
```

Consola:

```text
https://localhost:7443/auth/admin/master/console/
```

### 7.3 Crear Realm

In Keycloak:

```text
Master -> Create Realm
Nombre: TrustNews
```

### 7.4 Crear Cliente Web

```text
Clients -> Create client
ClientID: TrustNewsWeb
Root URL: https://localhost:7443
Valid redirect: https://localhost:7443/*
Web Origins: *
```

### 7.5 Crear Cliente API

```text
Clients -> Create client
ClientID: TrustNewsApi
Client Authentication: ON
Authorization: OFF
Authentication Flow: solo Service accounts roles
```

Despues, en `Credentials`, copiar el `Client Secret`.

In `Realm settings` for `TrustNews`:

```text
Frontend URL: https://localhost:7443/auth/
```

### 7.6 Obtener Token De Cliente

```bash
curl -k -X POST https://localhost:7443/auth/realms/TrustNews/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=TrustNewsApi" \
  -d "client_secret=xxxxx"
```

---

## 8. Users, Roles and Contributions

### 8.1 Frontend users

1. Create user in Keycloak.
2. Use Admin/Clients to define quota.
3. Create document in Mongo with `client_id=user_<keycloak_user_id>`.

Example:

```json
{
  "name": "<client-name>",
  "limits": {
    "news_generation": 99999999,
    "blockchain_validation": 99999999
  },
  "consumed": {
    "news_generation": 0,
    "blockchain_validation": 0
  },
  "status": "Active",
  "active_date": "2026-05-01T09:59:08.903000",
  "deactivate_date": null,
  "client_id": "user_966b234d-adf3-430f-a98e-2f98dfe877a3"
}
```

Admin API:

```text
http://127.0.0.1:8400/docs
```

For administrators users, create realm role:

```text
trust-admin
```

and assign it to the user.

### 8.2 Clientes API

1. Create customer in Keycloak.
2. Obtener token.
3. Decodificar token y obtener `sub`.
4. Create quota with `client_id=<client-name>_<keycloak_client_hash_id>`.

Example:

```text
TrustNewsWeb_617597c5-fcc6-4ed5-9cf3-ae124ad3570c
```

Example document:

```json
{
  "name": "api_client_admin",
  "limits": {
    "news_generation": 99999999,
    "blockchain_validation": 99999999
  },
  "consumed": {
    "news_generation": 0,
    "blockchain_validation": 0
  },
  "status": "Active",
  "active_date": "2026-05-01T09:59:08.903000",
  "deactivate_date": null,
  "client_id": "TrustNewsApi_bca02884-1184-4e2f-94f5-6b6974a932ce"
}
```

---

## 9. Functional Configurations

### 9.1 Preferred Domains for Evidence Search

Contextual configuration lives in MongoDB, `evidence_domain_profiles` collection.

Seed versionado:

```text
api/evidence-search/config/evidence-domain-profile-default.json
api/evidence-search/config/evidence-normalization-configs.json
```

Dry-run:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --dry-run
```

Actual loading of the `default` profile without deleting other profiles from the collection:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --refresh --confirm
```

Load of another profile or other taxonomies:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py \
  --source /path/to/profile.json \
  --normalization-source /path/to/normalization-configs.json \
  --refresh --confirm
```

The loader makes `upsert` of a single document by `profile_id` and a document by `config_type`. Preserves the other profiles. After changing profiles or taxonomys, `evidence_search_cache` must be cleaned by `DELETE /admin/cache`, because its versions are part of the new keys but the previous documents remain until TTL.

After reloading:

```bash
kubectl rollout restart deployment/evidence-search -n apis
kubectl logs deployment/evidence-search -n apis
```

Expected verification: a Catalan SOCIAL/DEMOGRAPHICS assertion must order `idescat.cat`, `ine.es`, `eurostat.ec.europa.eu` and `reuters.com` when `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=LOCAL`.

---

## 10. MongoDB: Consultations and Data Cleaning

### 10.1 Entrar A Mongo

```bash
kubectl exec -it mongodb-0 -n infra -- mongo -u root -p <root-password> --authenticationDatabase admin
```

Inside Mongo:

```javascript
use newsdb
show collections
```

### 10.2 Consult and Delete Runtime Data

```javascript
db.news.countDocuments({})
db.news.deleteMany({})
db.news.countDocuments({})

db.events.deleteMany({})
db.validations.deleteMany({})
```

### 10.3 Recommended Development Reset

`assertions-document-v2` Schema does not maintain compatibility with old documents. To clean only runtime data without deleting cuotas/clientes:

```javascript
use newsdb
db.news.deleteMany({})
db.validations.deleteMany({})
db.events.deleteMany({})
db.clients_quotas.countDocuments()
```

---

## 11. Summary of Endpoints

| Service | URL | Perfil Skaffold | Description |
|---|---|---|---|
| Frontend | https://localhost:7443 | `apis-frontend` | Main Web Application |
| Admin API Swagger | http://localhost:8400/docs | `apis-frontend` | Admin API |
| Gateway Swagger | http://localhost:8500/docs | `apis-frontend` | API Gateway |
| Evidence Search Swagger | http://localhost:8074/docs | `apis-frontend` | Evidence search service |
| News Handler Swagger | http://localhost:8072/docs | `apis-frontend` | Main news orchestrator |
| News Chain Swagger | http://localhost:8073/docs | `apis-frontend` | blockchain/IPFS interaction API |
| IPFS FastAPI Swagger | http://localhost:8060/docs | `apis-frontend` | Own API for IPFS |
| Assertion Generator Swagger | http://localhost:8071/docs | `apis-frontend` | Assertion Generator |
| Validator Worker 1 Swagger | http://localhost:8070/docs | `apis-frontend` | Validator IA worker 1 |
| Validator Worker 2 Swagger | http://localhost:8069/docs | `apis-frontend` | Validator IA worker 2 |
| Validator Worker 3 Swagger | http://localhost:8068/docs | `apis-frontend` | Validator IA worker 3 |
| Grafana | http://localhost:3000 | `infra` | Dashboards and logs |
| Mongo Express | http://localhost:8081 | `infra` | UI for MongoDB, requires Basic Auth |
| Kafdrop | http://localhost:9000 | `infra` | UI for Kafka, topics and messages |
| Keycloak Admin | https://localhost:7443/auth/admin/master/console/ | `apis-frontend` | Keycloak administration console via frontend/proxy |
| Frontend Prod | https://localhost:10443 | `apis-frontend-prod` | Frontend in prod profile |
| Admin API Prod Swagger | http://localhost:8400/docs | `apis-frontend-prod` | Admin API in prod profile |

---

## 12. Summary of Collections

| Database | Coleccion | Main Service | Variable/config | Uso |
|---|---|---|---|---|
| `newsdb` | `news` | `news-handler` | `MONGO_COLLECTION=news` | ordenes/noticias. Main Collection Saves flow status, document, assertions, validations, `postId`, hashes, CIDs, results and metadata. |
| `newsdb` | `news` | `admin` | `ORDERS_COLLECTION=news` | Check orders to resolve `client_id` and associate quota consumption to an order or `postId`. |
| `newsdb` | `events` | `news-handler` | Hardcoded: `db["events"]` | Saves flow events by `order_id`: Kafka enviadas/recibidas actions, topic, timestamp and payload. The UI retrieves them to paint the event pestana of an order. |
| `newsdb` | `validations` | `news-handler` | Hardcoded: `db["validations"]` | It keeps standardized validation records by orden/asercion/validador, including result, `tx_hash`, used evidence, validator config and response times. |
| `newsdb` | `clients_quotas` | `admin` | `QUOTAS_COLLECTION_NAME=clients_quotas` | Save disponibles/consumidas customers and fees per service, such as news generation or validations. |
| `newsdb` | `evidence_domain_profiles` | `evidence-search` | `EVIDENCE_DOMAIN_CONFIG_COLLECTION=evidence_domain_profiles` | A complete document by `profile_id` with weights, policy and array `domains`; LOCAL is the only way you consult it. |
| `newsdb` | `evidence_normalization_configs` | `evidence-search` | `EVIDENCE_NORMALIZATION_CONFIG_COLLECTION=evidence_normalization_configs` | A document by taxonomy off-chain: subcategories, location scopes and source types. |
| `newsdb` | `evidence_search_cache` | `evidence-search` | `EVIDENCE_SEARCH_CACHE_COLLECTION=evidence_search_cache` | `/search/evidence` response cache v2 for standardized assertion, search policy and profile version. Expires by TTL (`EVIDENCE_SEARCH_CACHE_TTL_SECONDS`). |

---

## 13. Mantenimiento Local

### 13.1 Clear Unusual Images Inside Kind Nodes

```bash
docker system df

for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo "==== Limpiando $node ===="
  docker exec "$node" crictl rmi --prune || true
done


for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo
  echo "=================================================="
  echo "BORRANDO import-* EN $node"
  echo "=================================================="

  docker exec "$node" sh -c '
    crictl images | grep "docker.io/library/import-" | awk "{print \$3}" | sort -u > /tmp/import-images.txt

    echo "Total a borrar:"
    wc -l /tmp/import-images.txt

    while read img; do
      echo "Borrando $img"
      crictl rmi "$img"
    done < /tmp/import-images.txt
  '
done
```
