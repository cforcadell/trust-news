# Assermetry Kubernetes - Procedimientos comunes

This document concentrates shared parts for local deployment and server deployment. Specific runbooks should only keep what changes by environment:

- Local: [`skaffold-local.md`](skaffold-local.md)
- Server/Hetzner: [`skaffold-server.md`](skaffold-server.md)

---

## 1. Namespaces

The names used by Assermetry are:

```text
blockchain
infra
apis
frontend
```

Verification:

```bash
kubectl get ns blockchain infra apis frontend
```

---

## 2. Perfiles Skaffold

| Capa | Local | Server/produccion |
|---|---|---|
| Namespaces/setup | script local | `setup` |
| Infraestructura | `infra`, `infra-basic` | `infra-prod` |
| Blockchain | `blockchain` | `blockchain-prod` |
| APIs and frontend | `apis-frontend` | `apis-frontend-prod` |

`infra` and `infra-basic` are local alternatives. `infra-basic` omits monitoring for a lightweight deployment and has no productive equivalent.

---

## 3. Verificaciones Kubernetes

General status:

```bash
kubectl get pods -n blockchain
kubectl get pods -n infra
kubectl get pods -n apis
kubectl get pods -n frontend
```

Services:

```bash
kubectl get svc -n infra
kubectl get svc -n apis
kubectl get svc -n frontend
```

Rollouts principales:

```bash
kubectl rollout status deployment/gateway -n apis --timeout=180s
kubectl rollout status deployment/news-handler -n apis --timeout=180s
kubectl rollout status deployment/evidence-search -n apis --timeout=180s
kubectl rollout status deployment/frontend-web -n frontend --timeout=180s
```

Logs habituales:

```bash
kubectl logs deployment/gateway -n apis --tail=80
kubectl logs deployment/news-handler -n apis --tail=80
kubectl logs deployment/evidence-search -n apis --tail=80
kubectl logs -n infra -f kafka-0
```

---

## 4. Blockchain

### 4.1 Node State

```bash
kubectl get pods -n blockchain -o wide
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "eth.blockNumber"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "eth.blockNumber"
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec "eth.blockNumber"
```

RPC and miner must move to the same block. If a transaction is pending, check `txpool.status` in RPC and miner:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'txpool.status'
```

### 4.2 Peers and manual connection

Check real peer without arrow functions, because some geth consoles don't support them:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.peers.map(function(p){ return p.name + " " + p.network.remoteAddress })'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.peers.map(function(p){ return p.name + " " + p.network.remoteAddress })'
```

Obtener enodes:

```bash
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.nodeInfo.enode'
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.nodeInfo.enode'
```

Connect RPC and miner if they are only connected to the bootnode:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("ENODE_DEL_MINER")'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.addPeer("ENODE_DEL_RPC")'
```

`admin.addPeer()` is temporary. If blockchain pods are restarted, you may miss it.

### 4.3 Reinicio conservando volumenes

```bash
kubectl scale statefulset --all --replicas=0 -n blockchain
kubectl scale statefulset --all --replicas=1 -n blockchain
kubectl get pods -n blockchain
```

---

## 5. Smart contract

If a new contract is deployed, `postId` returns to `0`. If there are previous data, delete or adjust MongoDB to avoid inconsistencies:

```javascript
db.events.deleteMany({})
db.news.deleteMany({})
db.validations.deleteMany({})
```

Comprobar bytecode:

```bash
export CONTRACT_ADDRESS=0x<direccion-trust-news>
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- \
  geth attach --exec "eth.getCode('$CONTRACT_ADDRESS')"
```

Initialize or verify on-chain categories. It is idempotent if the contract owner is used:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network <network>
npx hardhat run scripts/initCategories.js --network <network>
unset DEPLOYER_PRIVATE_KEY
```

The second execution must show categories such as `unchanged`. If there is `mismatch`, do not continue: the contract does not correspond to the expected version or the categories do not match `smart-contracts/config/categories.json`.

---

## 6. MongoDB bootstrap

After lifting MongoDB, run the bootstrap and check the schema:

```bash
scripts/k8s/init-mongodb-server.sh
scripts/k8s/realign-source-routing-mongodb.sh --check
```

This step:

- creates or updates the application user;
- creates `news`, `clients_quotas`, `events` and `validations` indexes;
- realinea `source_routes_v2`, `domain_profiles_v1` and `evidence_search_cache_v2` when changing the schema marker;
- eliminates previous incompatible collections and retains new caches in repeated executions.

In CI, `apis-frontend-prod` runs `--apply` and `--check` immediately before the API rollout. For `infra-prod`, the bootstrap executes them after the MongoDB StatefulSet is ready.

Verification:

```bash
scripts/k8s/realign-source-routing-mongodb.sh --check
```

---

## 7. Keycloak and assessed contributions

Minima configuration:

- Realm: `TrustNews`.
- Cliente frontend: `TrustNewsWeb`.
  - Root URL: base frontend URL with `/gui`, without `/` final.
  - Home URL: Frontend base URL with `/gui/` final.
  - Valid redirect URIs: `<origen>/gui/*`.
  - Valid post logout redirect URIs: `<origen>/gui/*`.
  - Web Origins: only source (`scheme://host[:port]`), no path; use `*`
only in disposable tests.
  - In production they did not keep localhost entries or use a global comodin.
- Cliente backend: `TrustNewsApi`.
  - Client authentication: ON.
  - Service accounts roles: ON.
  - Guardar el client secret para clientes externos.
  - Do not modify or rotate this client when changing `TrustNewsWeb` URLs.

El Gateway protege su API con la audiencia `TrustNewsGateway`. Configurar en
Keycloak un client scope OIDC, por ejemplo `trustnews-gateway-audience`, con un
mapper de tipo **Audience** que emita `TrustNewsGateway` en el access token.
Asignar ese scope como **Default** a `TrustNewsWeb` y `TrustNewsApi`. La
audiencia identifica al recurso protegido; los clientes presentadores siguen
siendo `TrustNewsWeb` y `TrustNewsApi`.

The mapper must have:

- Including Client Audience or Custom Audience: `TrustNewsGateway`.
- Add to access token: activado.
- Add to ID token: desactivado.

The Gateway accepts tokens only with `aud` containing `TrustNewsGateway` and with `azp` or `client_id` equal to one of the permitted customers. After changing Keycloak you must request new tokens; existing tokens are not updated.

In production, the `infra-prod` pipeline applies and validates these URLs using the idepotent script documented in [`skaffold-server.md`](skaffold-server.md#65-alineación-idempotente-de-keycloak). Use the same script, instead of the web console, for manual recovery.

Para obtener un token local sin recurrir a TLS inseguro, abrir temporalmente el
puerto HTTP interno de Keycloak solo en loopback dentro de la VM y ejecutar la
peticion desde ella. Este salto no sale de la VM:

```bash
kubectl port-forward --address 127.0.0.1 -n infra svc/keycloak 18080:8080

read -rsp "TrustNewsApi client secret: " TRUSTNEWS_API_SECRET
printf '\n'
curl --fail --show-error -X POST \
  http://127.0.0.1:18080/auth/realms/TrustNews/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=TrustNewsApi" \
  --data-urlencode "client_secret=$TRUSTNEWS_API_SECRET"
unset TRUSTNEWS_API_SECRET
```

In production, the canonical endpoint is used with the TLS chain verified by `curl` and, while the time rule is still active, `--cert <cert.pem>` and `--key <key.pem>`. Do not use `-k` or publish the internal port of Keycloak.

### Quotas for frontend users

Business cuotas/clientes is created using the `admin` API; they must not be part of the fixed bootstrap or inserted directly into MongoDB. In local, the API and its Swagger interface are available at:

```text
http://localhost:8400/docs
```

For a frontend user, copy your `ID` (user UUID, not user name) from the realm `TrustNews` of Keycloak. The `client_id` that uses the Gateway is built in the format:

```text
user_<keycloak_user_id>
```

Create the client with `POST /clients`. The following example gives high 100 generation and 100 validation uses; adjust both limits as appropriate:

```bash
curl --fail --show-error -X POST \
  http://127.0.0.1:8400/clients \
  -H "Content-Type: application/json" \
  -d '{
    "name": "user-7d6c0b75-52af-4204-8288-9055d9218d02",
    "client_id": "user_7d6c0b75-52af-4204-8288-9055d9218d02",
    "limits": {
      "news_generation": 100,
      "blockchain_validation": 100
    }
  }'
```

`consumed` is initialized to zero, `status` to `Active` and `active_date` to the current UTC date when those fields are not sent. API persists document in `newsdb.clients_quotas`.

Check the discharge:

```bash
curl --fail --show-error \
  http://127.0.0.1:8400/clients/user_7d6c0b75-52af-4204-8288-9055d9218d02
```

If `POST /clients` responds `400` with `El cliente ya existe`, first consult the previous record and update its limits using `PATCH /clients/{client_id}` in Swagger, instead of creating a duplicate.

- Display name: visible application name, for example `Assermetry`.
Keycloak uses this value on the authentication screen (e.g. `Sign in to Assermetry`). Keeping `TrustNews` as the technical name of the realm prevents changing OIDC URLs, the issuer and client settings.

---

## 8. Source Router and Evidence Search

`source-router` mantiene rutas dinámicas en `source_routes_v2` y propiedades
estables en `domain_profiles_v1`. En MISS/STALE usa el proveedor de búsqueda y
el LLM configurados; en FRESH solo consulta Mongo.
Crear fuera del repositorio `search-secret`, `source-router-llm-secret` y
`mongodb-app-secret`. Evidence Search recibe `preferred_sources` para `LOCAL` y
solo recupera/rankea evidencia. No existen seeds ni allowlists.

```bash
kubectl create secret generic source-router-llm-secret -n apis \
  --from-env-file=source-router.env
```

The Evidence Search cache is cleaned using `DELETE /admin/cache`; routes do not use destructive TTL and are refreshed according to `refresh_after`.

Restart service:

```bash
kubectl rollout restart deployment/evidence-search -n apis
kubectl logs deployment/evidence-search -n apis
kubectl rollout restart deployment/source-router -n apis
kubectl logs deployment/source-router -n apis
```

---

## 9. MongoDB: consultations and cleaning

Entrar a MongoDB:

```bash
kubectl exec -it mongodb-0 -n infra -- mongo -u <root-user> -p <root-password> --authenticationDatabase admin
```

Inside MongoDB:

```javascript
use newsdb
show collections
```

Clear Runtime Data Without Erasing cuotas/clientes:

```javascript
db.news.deleteMany({})
db.validations.deleteMany({})
db.events.deleteMany({})
db.clients_quotas.countDocuments()
```

Colecciones principales:

| Coleccion | Main Service | Uso |
|---|---|---|
| `news` | `news-handler`, `admin` | Ordenes/noticias, flow status, `postId`, hashes, CIDs and quota query. |
| `events` | `news-handler` | Flow events by `order_id`. |
| `validations` | `news-handler` | Validations by orden/asercion/validador. |
| `clients_quotas` | `admin` | disponibles/consumidas. Customers and Quotas |
| `source_routes_v2` | `source-router` | Dynamic references FRESH/STALE of standard routes. |
| `domain_profiles_v1` | `source-router` | Stable and standardised profile of each classified domain. |
| `evidence_search_cache_v2` | `evidence-search` | Answers cached by assertion, origin, politics and backend. |

---

## 10. Operacion comun

Reiniciar APIs:

```bash
kubectl scale deployment --all --replicas=0 -n apis
kubectl scale deployment --all --replicas=1 -n apis
```

Reiniciar infra conservando PVCs:

```bash
kubectl scale statefulset --all --replicas=0 -n infra
kubectl scale statefulset --all --replicas=1 -n infra
```

Grafana/Loki:

```bash
kubectl port-forward service/grafana -n infra 3300:3000
```

The Python services deployed write JSON on a single line at `stdout`. Line breaks included in messages and tracebacks escape within the JSON, so that CRI, Fluent Bit and Loki retain an event per record. CLI utilities for statistics keep their tabular output for interactive use and are not part of the normal ingestion of Kubernetes.

Datasource Loki:

```text
http://loki.infra.svc.cluster.local:3100
```

Mongo Express:

```bash
kubectl port-forward --address 127.0.0.1 -n infra svc/mongo-express 8081:8081
```

This shared procedure links the listener to loopback. The exception for accessing from the host of the local VM is defined in [`skaffold-local.md`](skaffold-local.md#11-acceso-desde-el-host-de-la-vm); it does not apply to production.
