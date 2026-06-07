# TrustNews Kubernetes Deployment Guide v2

Esta version reorganiza `skaffold.md` sin sustituirlo. Mantiene el orden operativo original:

1. Recrear cluster.
2. Crear namespaces.
3. Levantar blockchain.
4. Desplegar contrato.
5. Levantar infraestructura.
6. Levantar APIs y frontend.
7. Configurar Keycloak, cuotas y usuarios.
8. Cargar configuraciones funcionales.
9. Consultar datos, endpoints y colecciones.
10. Operaciones de mantenimiento.

---

## 1. Recrear Cluster Local

Usar esta seccion cuando se quiera empezar desde cero. Es destructiva: borra el cluster `kind`, imagenes/volumenes Docker no usados y limpia espacio local.

### 1.1 Inspeccion Previa

```bash
kubectl get pvc -A
docker volume ls
df -h /
```

### 1.2 Borrado Del Cluster

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

### 1.4 Creacion Del Cluster

```bash
kind create cluster --name trust-news --config kind-config.yaml
```

---

## 2. Crear Namespaces

Ejecutar antes de cualquier perfil Skaffold.

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

### 3.1 Ver Estado

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

### 3.4 Diagnostico De Pods

```bash
kubectl describe pod geth-bootnode-0 -n blockchain
kubectl describe pod geth-rpc-endpoint-0 -n blockchain
kubectl describe pod geth-miner-0 -n blockchain
```

### 3.5 Conectar Al Nodo RPC

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555
```

Dentro de la consola:

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

### 3.6 Conectar Al Bootnode

```bash
kubectl exec -it geth-bootnode-0 -n blockchain -- ps aux
kubectl exec -it geth-bootnode-0 -n blockchain -- geth --exec "admin.nodeInfo.enode" attach ipc:/root/.ethereum/geth.ipc
```

### 3.7 Conectar Al Miner

```bash
kubectl exec -it geth-miner-0 -n blockchain -- geth attach
```

Dentro de la consola:

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

Comprobar que `net.peerCount == 1` en RPC y miner, y que `eth.blockNumber` coincide.

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

Atencion: si se despliega un contrato nuevo, `postId` vuelve a `0`. Si hay datos previos, borrar o ajustar Mongo para evitar inconsistencias.

```javascript
db.events.deleteMany({})
db.news.deleteMany({})
db.validations.deleteMany({})
```

### 4.1 Abrir RPC Local

```bash
kubectl port-forward svc/geth-rpc-endpoint 8555:8555 -n blockchain
```

### 4.2 Desplegar Contrato

```bash
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth
```

### 4.3 Fondear Cuentas

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555
```

Dentro de la consola:

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

### 4.4 Verificaciones Del Contrato

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

Servicios expuestos por Skaffold:

```text
Kafdrop: http://localhost:9000
Grafana: http://localhost:3000
Mongo Express: http://localhost:18081
```

### 5.1 Ver Estado

```bash
kubectl get pods -n infra
kubectl get svc -n infra
kubectl logs -n infra -f kafka-0
```

### 5.2 Reiniciar StatefulSets De Infra

```bash
kubectl scale statefulset --all --replicas=0 -n infra
kubectl scale statefulset --all --replicas=1 -n infra
```

### 5.3 Borrar PVCs De Infra

Usar si al parar pods o eliminar StatefulSets quedan PVCs antiguos.

```bash
kubectl get pvc -n infra
kubectl delete pvc ipfs-storage-ipfs-0 -n infra
kubectl delete pvc kafka-data-kafka-0 -n infra
kubectl delete pvc mongodb-storage-mongodb-0 -n infra
```

### 5.4 Grafana Y Loki

Datasource en Grafana:

```text
http://loki.infra.svc.cluster.local:3100
```

Luego usar `Explore` y `Run query`.

---

## 6. Desplegar APIs Y Frontend

Perfil Skaffold:

```bash
./skaffold dev -p apis-frontend
# ./skaffold dev -p apis-frontend --cache-artifacts=true --cleanup=false
```

### 6.1 Ver Estado

```bash
kubectl get pods -n apis
kubectl get pods -n frontend
kubectl logs -n apis -f
```

### 6.2 Frontend

Si no se levanta el port-forward:

```bash
kubectl port-forward svc/frontend-service -n frontend 7443:443
```

URLs principales:

```text
https://localhost:7443/
https://localhost:7443/backend/docs
https://localhost:7443/auth/admin/master/console/
```

Si se accede desde VM con mapeo de host:

```text
https://192.168.56.108:7443/
```

### 6.3 Ver Nginx Del Frontend

```bash
kubectl exec -it -n frontend frontend-web-5769696f49-dljlk -- cat /etc/nginx/conf.d/default.conf
```

---

## 7. Secretos Y Configuracion Base

### 7.1 Secretos De Infra Y APIs

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

Comprobacion:

```bash
curl -v -k https://localhost:7443/auth/admin/master/console
```

Consola:

```text
https://localhost:7443/auth/admin/master/console/
```

### 7.3 Crear Realm

En Keycloak:

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

En `Realm settings` para `TrustNews`:

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

## 8. Usuarios, Roles Y Cuotas

### 8.1 Usuarios Frontend

1. Crear usuario en Keycloak.
2. Usar Admin/Clients para definir cuota.
3. Crear documento en Mongo con `client_id=user_<keycloak_user_id>`.

Ejemplo:

```json
{
  "name": "cforcadellm",
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

Para usuarios administradores, crear realm role:

```text
trust-admin
```

y asignarlo al usuario.

### 8.2 Clientes API

1. Crear cliente en Keycloak.
2. Obtener token.
3. Decodificar token y obtener `sub`.
4. Crear cuota con `client_id=<client-name>_<keycloak_client_hash_id>`.

Ejemplo:

```text
TrustNewsWeb_617597c5-fcc6-4ed5-9cf3-ae124ad3570c
```

Documento ejemplo:

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

## 9. Configuraciones Funcionales

### 9.1 Dominios Preferentes Para Evidence Search

La configuracion contextual vive en MongoDB, coleccion `evidence_domain_profiles`.

Seed versionado:

```text
api/evidence-search/config/evidence-domain-profiles.yaml
```

Dry-run:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --dry-run
```

Carga real del perfil `default` sin borrar otros perfiles de la coleccion:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --confirm
```

Carga de otro `profile_id`:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --profile-id custom --confirm
```

Carga de otro fichero:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py \
  --source /path/to/profiles.yaml \
  --confirm
```

El loader reemplaza solo los documentos del `profile_id` indicado y crea documentos separados:

```text
profile_index/<profile_id>
profile_subset/<profile_id>/source_types
profile_subset/<profile_id>/categories
profile_subset/<profile_id>/subcategories
profile_subset/<profile_id>/countries
profile_subset/<profile_id>/regions
profile_subset/<profile_id>/cities
profile_subset/<profile_id>/entities
```

Por defecto tambien borra `evidence_search_cache`. Para conservar cache:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --confirm --keep-cache
```

Despues de recargar:

```bash
kubectl rollout restart deployment/evidence-search -n apis
kubectl logs deployment/evidence-search -n apis
```

Verificacion esperada: una busqueda con `city=Barcelona` y `entity=Ayuntamiento de Barcelona` debe priorizar `barcelona.cat`, `seu.barcelona.cat` y `bop.diba.cat` cuando `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=true`.

---

## 10. MongoDB: Consultas Y Limpieza De Datos

### 10.1 Entrar A Mongo

```bash
kubectl exec -it mongodb-0 -n infra -- mongo -u root -p cforcadellm --authenticationDatabase admin
```

Dentro de Mongo:

```javascript
use newsdb
show collections
```

### 10.2 Consultar Y Borrar Datos Runtime

```javascript
db.news.countDocuments({})
db.news.deleteMany({})
db.news.countDocuments({})

db.events.deleteMany({})
db.validations.deleteMany({})
```

### 10.3 Reset De Desarrollo Recomendado

El schema `assertions-document-v2` no mantiene compatibilidad con documentos antiguos. Para limpiar solo datos runtime sin borrar cuotas/clientes:

```javascript
use newsdb
db.news.deleteMany({})
db.validations.deleteMany({})
db.events.deleteMany({})
db.clients_quotas.countDocuments()
```

---

## 11. Resumen De Endpoints

| Servicio | URL | Perfil Skaffold | Descripcion |
|---|---|---|---|
| Frontend | https://localhost:7443 | `apis-frontend` | Aplicacion web principal |
| Admin API Swagger | http://localhost:8400/docs | `apis-frontend` | API de administracion |
| Gateway Swagger | http://localhost:8500/docs | `apis-frontend` | API Gateway |
| Evidence Search Swagger | http://localhost:8074/docs | `apis-frontend` | Servicio de busqueda de evidencias |
| News Handler Swagger | http://localhost:8072/docs | `apis-frontend` | Orquestador principal de noticias |
| News Chain Swagger | http://localhost:8073/docs | `apis-frontend` | API de interaccion con blockchain/IPFS |
| IPFS FastAPI Swagger | http://localhost:8060/docs | `apis-frontend` | API propia para IPFS |
| Assertion Generator Swagger | http://localhost:8071/docs | `apis-frontend` | Generador de aserciones |
| Validator Worker 1 Swagger | http://localhost:8070/docs | `apis-frontend` | Validador IA worker 1 |
| Validator Worker 2 Swagger | http://localhost:8069/docs | `apis-frontend` | Validador IA worker 2 |
| Validator Worker 3 Swagger | http://localhost:8068/docs | `apis-frontend` | Validador IA worker 3 |
| Grafana | http://localhost:3000 | `infra` | Dashboards y logs |
| Mongo Express | http://localhost:8081 | `infra` | UI para MongoDB, requiere Basic Auth |
| Kafdrop | http://localhost:9000 | `infra` | UI para Kafka, topics y mensajes |
| Keycloak Admin | https://localhost:7443/auth/admin/master/console/ | `apis-frontend` | Consola de administracion de Keycloak via frontend/proxy |
| Frontend Prod | https://localhost:10443 | `apis-frontend-prod` | Frontend en perfil prod |
| Admin API Prod Swagger | http://localhost:8400/docs | `apis-frontend-prod` | Admin API en perfil prod |

---

## 12. Resumen De Colecciones

| Base de datos | Coleccion | Servicio principal | Variable/config | Uso |
|---|---|---|---|---|
| `newsdb` | `news` | `news-handler` | `MONGO_COLLECTION=news` | Coleccion principal de ordenes/noticias. Guarda estado del flujo, documento, aserciones, validaciones, `postId`, hashes, CIDs, resultados y metadatos. |
| `newsdb` | `news` | `admin` | `ORDERS_COLLECTION=news` | Consulta ordenes para resolver `client_id` y asociar consumo de cuotas a una orden o `postId`. |
| `newsdb` | `events` | `news-handler` | Hardcoded: `db["events"]` | Guarda eventos del flujo por `order_id`: acciones Kafka enviadas/recibidas, topic, timestamp y payload. La UI los recupera para pintar la pestana de eventos de una orden. |
| `newsdb` | `validations` | `news-handler` | Hardcoded: `db["validations"]` | Guarda registros normalizados de validaciones por orden/asercion/validador, incluyendo resultado, `tx_hash`, evidencia usada, config del validador y tiempos de respuesta. |
| `newsdb` | `clients_quotas` | `admin` | `QUOTAS_COLLECTION_NAME=clients_quotas` | Guarda clientes y cuotas disponibles/consumidas por servicio, como generacion de noticias o validaciones. |
| `newsdb` | `evidence_domain_profiles` | `evidence-search` | `EVIDENCE_DOMAIN_CONFIG_COLLECTION=evidence_domain_profiles` | Configura el enrutado contextual v3 de dominios. Usa documentos separados por perfil: `profile_index` y `profile_subset` para `source_types`, `categories`, `subcategories`, `countries`, `regions`, `cities` y `entities`. |
| `newsdb` | `evidence_search_cache` | `evidence-search` | `EVIDENCE_SEARCH_CACHE_COLLECTION=evidence_search_cache` | Cache v2 de respuestas de `/search/evidence` por asercion normalizada, politica de busqueda y version de perfiles. Expira por TTL (`EVIDENCE_SEARCH_CACHE_TTL_SECONDS`). |

---

## 13. Mantenimiento Local

### 13.1 Limpiar Imagenes No Usadas Dentro De Nodos Kind

```bash
docker system df

for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo "==== Limpiando $node ===="
  docker exec "$node" crictl rmi --prune || true
done
```
