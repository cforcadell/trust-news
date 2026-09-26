
**create/recreate cluster**
> [!WARNING]
> **ARCHIVADO — NOT USE.** Historical reference; see
> [`README.md`](README.md) and runbooks are in place before operation.

```bash delete

kubectl get pvc -A
docker volume ls

kind delete cluster --name trust-news

docker system prune -a -f

df -h /
docker volume ls

docker system prune -a -f
sudo journalctl --vacuum-size=300M
sudo apt clean
sudo apt autoremove -y
df -h /

docker volume prune -f
df -h /


```
```bash create

kind create cluster --name trust-news --config kind-config.yaml
```



**Skaffold**

```bash create namespaces
cd ./scripts/k8s
./create-namespaces.sh
```

```bash blockchain

./skaffold dev -p blockchain --namespace blockchain
# ./skaffold dev -p blockchain --namespace blockchain --cleanup=false


kubectl get pods -n blockchain

#see logs
kubectl logs -n blockchain -f geth-bootnode-0
kubectl logs -n blockchain -f geth-rpc-endpoint-0
kubectl logs -n blockchain -f geth-miner-0

#see geth processes

kubectl exec geth-bootnode-0 -n blockchain -- ps aux | grep geth
kubectl exec geth-rpc-endpoint-0 -n blockchain -- ps aux | grep geth
kubectl exec geth-miner-0 -n blockchain -- ps aux | grep geth

#analyze if node have been initialized or not

 kubectl describe pod geth-bootnode-0 -n blockchain
 kubectl describe pod geth-rpc-endpoint-0 -n blockchain
 kubectl describe pod geth-miner-0 -n blockchain

#connect rpc node
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555

> admin.peers
> net.peerCount
> eth.blockNumber

#alernativa
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "admin.peers"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "eth.blockNumber"

#connect boot node
kubectl exec -it geth-bootnode-0 -n blockchain -- ps aux
#get enode
kubectl exec -it geth-bootnode-0 -n blockchain -- geth --exec "admin.nodeInfo.enode" attach ipc:/root/.ethereum/geth.ipc

#connect miner node
kubectl exec -it geth-miner-0 -n blockchain -- geth attach
> admin.peers
> net.peerCount
> eth.blockNumber

kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "admin.peers"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "eth.blockNumber"

# check that net.peerCount ==1 in rpc & miner node and check that eth.blockNumber in both nodes are equal
#connect manually two nodes

>kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("enode://af28ee328bbab1085d8f3e6eef110001a4075da8513871091bb25c7111f57e4261270b26791b5d71d6fd9707c1efd4ca17db2010b73fcd7ff1c7cd3a6877531c@10.244.2.13:30304")'4")'

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"


#restart blockchain keepong stateful and volumes
kubectl scale statefulset geth-bootnode --replicas=0 -n blockchain
kubectl scale statefulset geth-miner --replicas=0 -n blockchain
kubectl scale statefulset geth-rpc-endpoint --replicas=0 -n blockchain

kubectl scale statefulset --all --replicas=0 -n blockchain
kubectl scale statefulset --all --replicas=1 -n blockchain

kubectl get pods -n blockchain

kubectl get pv  -n blockchain

```



```bash deploy contract
#!!! if we deploy new contract POstId resets to 0. Remember to delete db content o change postId
# db.events.deleteMany({})
# db.news.deleteMany({})
# db.validations.deleteMany({})
#to allow access through localhost
kubectl port-forward svc/geth-rpc-endpoint 8555:8555 -n blockchain

cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth

#fund

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555

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



eth.pendingTransactions

eth.getBalance("0xa28885a13a7b4d3561a7af64ea1ba0f82ed9f06b")

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getCode("0x9eA62eb7944349C407B307025644E47bF22F8bCc")'

```


```bash infra

./skaffold dev -p infra 
./skaffold dev -p infra-basic

# Kafdrop queda expuesto por Skaffold en:
# http://localhost:9000

kubectl scale statefulset --all --replicas=0 -n infra
kubectl scale statefulset --all --replicas=1 -n infra

kubectl get pods -n infra


kubectl logs -n infra -f kafka-0


#si al parar los pods a replicas=0 o eliminar los statefuls quedan pvcs
kubectl get pvc -n infra
kubectl delete pvc ipfs-storage-ipfs-0 -n infra
kubectl delete pvc kafka-data-kafka-0 -n infra
kubectl delete pvc mongodb-storage-mongodb-0 -n infra
```



```bash apis + frontend

./skaffold dev -p apis-frontend  # --cache-artifacts=true --cleanup=false


kubectl get pods -n apis
kubectl get pods -n frontend

kubectl logs -n apis -f

Frontend:
#si no se levanta el port forward
kubectl port-forward svc/frontend-service -n frontend 7443:443
#verify nginx config
kubectl exec -it -n frontend frontend-web-5769696f49-dljlk -- cat /etc/nginx/conf.d/default.conf
#realm console
https://localhost:7443/auth/admin/master/console/


#https://192.168.56.108:7443/
#con mapeo de host a vm
https://localhost:7443/

grafana:
http://localhost:3000/

https://localhost:7443/backend/docs


keycloak realm master
https://localhost:7443/auth/admin/master/console/

#get token
curl -k -X POST https://localhost:7443/auth/realms/TrustNews/protocol/openid-connect/token -H "Content-Type: application/x-www-form-urlencoded" -d "grant_type=client_credentials" -d "client_id=TrustNewsApi" -d "client_secret=xxxxx"



---



get svc -n infra

#Add datasource in grafana: http://loki.infra.svc.cluster.local:3100

Explore + Run query

```
```bash  get secret details

kubectl get secrets -n infra
kubectl get mongodb-secret -n infra -o jsonpath='{.data}'


kubectl get secrets -n apis
kubectl get secret mongodb-app-secret -n apis -o jsonpath='{.data}'
echo "x" | base64 --decode

```
```bash config keycloak
keycloak (sin ir por nginx):

#si no lo abre skaffold
kubectl port-forward svc/keycloak --address 0.0.0.0 -n infra 7443:8443

curl -v -k https://localhost:7443/auth/admin/master/console

https://localhost:7443/auth/admin/master/console/


```

Create the Realm: * Click the top left drop-down (Master) and hit Create Realm.

Name: TrustNews.

Creates the Client for the Web (Frontend):

Clients -> Create client.

ClientID: TrustNewsWeb.

Root URL: https://localhost:7443 (or your frontend URL). Valid redirect: https://localhost:7443/*

Web Origins: * (to avoid developing CORS problems).

Create Customer for Public Backends (What you asked for at the beginning):

Clients -> Create client.

ClientID: TrustNewsApi.

Client Authentication: Put it on ON.

Authorization: Put it in OFF.

Authentication Flow: Brand only Service accounts roles (unmarks the rest).

Una vez guardado, ve a la pestaña Credentials y ahí verás el Client Secret que necesitarán los backends externos para llamarte.

#In realm settings (TrustNews) #Frontend URL: https://localhost:7443/auth/

Create Application User

```bash quota & users admin

FE Users
Create new keycloak user
Use admin/Clients to define user quota and create inside mondogb: user_<keycloak_user_id>
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

http://127.0.0.1:8400/docs

for admin users create realm role (trust-admin) ans assig


API Users
Create new keycloak client

curl -k -X POST https://localhost:7443/auth/realms/TrustNews/protocol/openid-connect/token -H "Content-Type: application/x-www-form-urlencoded" -d "grant_type=client_credentials" -d "client_id=TrustNewsApi" -d "client_secret=xxxxxx"

Decode token ang get keycloak_client_hash_id ("sub")

Use admin/Clients to define user quota and create inside mondogb: <client-name>_<keycloak_client_hash_id>
Ej: TrustNewsWeb_617597c5-fcc6-4ed5-9cf3-ae124ad3570c

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

http://127.0.0.1:8400/docs


```
```bash  Ini search preferences
./scripts/k8s/apis/init-evidence-search-domains.py

```
```bash  get mongodb data

kubectl exec -it mongodb-0 -n infra -- mongo -u root -p <root-password> --authenticationDatabase admin
> use newsdb
> show collections
events
news
validations
> db.news.countDocuments({})
8
> db.news.deleteMany({})
{ "acknowledged" : true, "deletedCount" : 8 }
> db.news.countDocuments({})
0
> db.events.deleteMany({})
{ "acknowledged" : true, "deletedCount" : 99 }
> db.validations.deleteMany({})
{ "acknowledged" : true, "deletedCount" : 22 }
```

**ENDPOINTS SUMMARY**
| Service | URL | Perfil Skaffold | Description |
|---|---|---|---|
| Frontend | https://localhost:7443 | `apis-frontend` | Main Web application |
| Admin API Swagger | http://localhost:8400/docs | `apis-frontend` | Administration API |
| Gateway Swagger | http://localhost:8500/docs | `apis-frontend` | API Gateway |
| Evidence Search Swagger | http://localhost:8074/docs | `apis-frontend` | Evidence-seeking service |
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


** COLLECTIONS OVERVIEW**
| Database | Collection | Main Service | Variable/config | Uso |
|---|---|---|---|---|
| `newsdb` | `news` | `news-handler` | `MONGO_COLLECTION=news` | Main command/news collection. Save flow status, document, assertions, validations, `postId`, hashes, CIDs, results and metadata. |
| `newsdb` | `news` | `admin` | `ORDERS_COLLECTION=news` | Check commands to resolve `client_id` and associate quota consumption to an order or `postId`. |
| `newsdb` | `events` | `news-handler` | Hardcoded: `db["events"]` | Saves flow events by `order_id`: Kafka enviadas/recibidas actions, topic, timestamp and payload. The UI retrieves them to paint the event tab of an order. |
| `newsdb` | `validations` | `news-handler` | Hardcoded: `db["validations"]` | It keeps standardized validation records by orden/asercion/validator, including result, `tx_hash`, used evidence, validator config and response times. |
| `newsdb` | `clients_quotas` | `admin` | `QUOTAS_COLLECTION_NAME=clients_quotas` | Save disponibles/consumidas customers and quotas per service, as news generation or validations. |
| `newsdb` | `evidence_domain_profiles` | `evidence-search` | `EVIDENCE_DOMAIN_CONFIG_COLLECTION=evidence_domain_profiles` | A complete document by `profile_id` for LOCAL scorring; there is no hardcoded fallback or legacy model by category. |
| `newsdb` | `evidence_normalization_configs` | `evidence-search` | `EVIDENCE_NORMALIZATION_CONFIG_COLLECTION=evidence_normalization_configs` | A document by taxonomy off-chain: subcategories, location scopes and source types. |
| `newsdb` | `evidence_search_cache` | `evidence-search` | `EVIDENCE_SEARCH_CACHE_COLLECTION=evidence_search_cache` | `/search/evidence` response cache v2 for standardized assertion, search policy and profile version. Expires by TTL (`EVIDENCE_SEARCH_CACHE_TTL_SECONDS`). |

**Reset of development data and top-up of preferred domains**

`assertions-document-v2` Schema does not maintain compatibility with old documents. If in a local environment you want to clean only runtime data, do it manually and without deleting cuotas/clientes:

```javascript
use newsdb
db.news.deleteMany({})
db.validations.deleteMany({})
db.events.deleteMany({})
db.clients_quotas.countDocuments()
```

The context configuration of preferred domains lives in MongoDB, `evidence_domain_profiles` collection. The versioned seed is in `api/evidence-search/config/evidence-domain-profile-default.json` and `api/evidence-search/config/evidence-normalization-configs.json`. Dry-run of the controlled destructive charger:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --dry-run
```

Real charge on demand. The charger makes upsert of the profile indicated and taxonomy, preserving other profiles:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --refresh --confirm
```

You can also load explicit files:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py \
  --source /path/to/profile.json \
  --normalization-source /path/to/normalization-configs.json \
  --refresh --confirm
```

Recommended verification:

```bash
kubectl rollout restart deployment/evidence-search -n apis
kubectl logs deployment/evidence-search -n apis
```

After reloading, a search with `city=Barcelona` and `entity=Ayuntamiento de Barcelona` should prioritize `barcelona.cat`, `seu.barcelona.cat` and `bop.diba.cat`.

```bash limpiar imagenes no usadas dento de los nodos de kind
for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo "==== Limpiando $node ===="
  docker exec "$node" crictl rmi --prune || true
done
```
