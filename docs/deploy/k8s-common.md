# Assermetry Kubernetes - Procedimientos comunes

Este documento concentra las partes compartidas por el despliegue local y el
despliegue en servidor. Los runbooks especificos solo deben mantener lo que
cambia por entorno:

- Local: [`skaffold-local.md`](skaffold-local.md)
- Server/Hetzner: [`skaffold-server.md`](skaffold-server.md)

---

## 1. Namespaces

Los namespaces usados por Assermetry son:

```text
blockchain
infra
apis
frontend
```

Verificacion:

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
| APIs y frontend | `apis-frontend` | `apis-frontend-prod` |

`infra` e `infra-basic` son alternativas locales. `infra-basic` omite la
monitorización para un despliegue ligero y no tiene equivalente productivo.

---

## 3. Verificaciones Kubernetes

Estado general:

```bash
kubectl get pods -n blockchain
kubectl get pods -n infra
kubectl get pods -n apis
kubectl get pods -n frontend
```

Servicios:

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

### 4.1 Estado de nodos

```bash
kubectl get pods -n blockchain -o wide
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "eth.blockNumber"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "eth.blockNumber"
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec "eth.blockNumber"
```

RPC y miner deben avanzar al mismo bloque. Si una transaccion queda pendiente,
revisar `txpool.status` en RPC y miner:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'txpool.status'
```

### 4.2 Peers y conexion manual

Consultar peers reales sin arrow functions, porque algunas consolas de geth no
las soportan:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.peers.map(function(p){ return p.name + " " + p.network.remoteAddress })'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.peers.map(function(p){ return p.name + " " + p.network.remoteAddress })'
```

Obtener enodes:

```bash
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.nodeInfo.enode'
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.nodeInfo.enode'
```

Conectar RPC y miner si solo estan conectados al bootnode:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("ENODE_DEL_MINER")'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.addPeer("ENODE_DEL_RPC")'
```

`admin.addPeer()` es temporal. Si se reinician los pods de blockchain, puede
perderse.

### 4.3 Reinicio conservando volumenes

```bash
kubectl scale statefulset --all --replicas=0 -n blockchain
kubectl scale statefulset --all --replicas=1 -n blockchain
kubectl get pods -n blockchain
```

---

## 5. Smart contract

Si se despliega un contrato nuevo, `postId` vuelve a `0`. Si hay datos previos,
borrar o ajustar MongoDB para evitar inconsistencias:

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

Inicializar o verificar categorias on-chain. Es idempotente si se usa el
propietario del contrato:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network <network>
npx hardhat run scripts/initCategories.js --network <network>
unset DEPLOYER_PRIVATE_KEY
```

La segunda ejecucion debe mostrar las categorias como `unchanged`. Si hay
`mismatch`, no continuar: el contrato no corresponde a la version esperada o las
categorias no coinciden con `smart-contracts/config/categories.json`.

---

## 6. MongoDB bootstrap

Despues de levantar MongoDB, ejecutar siempre el bootstrap idempotente:

```bash
scripts/k8s/init-mongodb-server.sh --dry-run
scripts/k8s/init-mongodb-server.sh
```

Este paso:

- crea o actualiza el usuario de aplicacion;
- crea indices de `news`, `clients_quotas`, `events`, `validations` y `evidence_search_cache`;
- reemplaza el perfil `default` de `evidence_domain_profiles`;
- inserta o actualiza `evidence_normalization_configs`;
- limpia por defecto `evidence_search_cache`.

Verificacion:

```bash
kubectl exec -it mongodb-0 -n infra -- sh -c \
  'mongo -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "$MONGO_APP_DATABASE" --quiet --eval "const p=db.evidence_domain_profiles.findOne({profile_id: \"default\"}); printjson({profiles: db.evidence_domain_profiles.countDocuments({profile_id: \"default\"}), normalization: db.evidence_normalization_configs.countDocuments({}), domains: p ? p.domains.length : 0})"'
```

---

## 7. Keycloak y cuotas

Configuracion minima:

- Realm: `TrustNews`.
- Cliente frontend: `TrustNewsWeb`.
  - Root URL: URL publica o local del frontend.
  - Home URL: URL publica o local del frontend, con `/` final.
  - Valid redirect URIs: `<frontend-url>/*`.
  - Valid post logout redirect URIs: `<frontend-url>/*`.
  - Web Origins: URL publica o local del frontend, o `*` solo para pruebas.
  - En produccion no conservar entradas localhost ni usar un comodin global.
- Cliente backend: `TrustNewsApi`.
  - Client authentication: ON.
  - Service accounts roles: ON.
  - Guardar el client secret para clientes externos.
  - No modificar ni rotar este cliente al cambiar las URLs de `TrustNewsWeb`.

En producción, el pipeline `infra-prod` aplica y valida estas URLs mediante el
script idempotente documentado en
[`skaffold-server.md`](skaffold-server.md#65-alineación-idempotente-de-keycloak).
Usar ese mismo script, en lugar de la consola web, para una recuperación manual.

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

En produccion se usa el endpoint canonico con la cadena TLS verificada por
`curl` y, mientras siga activa la regla temporal, `--cert <cert.pem>` y
`--key <key.pem>`. No usar `-k` ni publicar el puerto interno de Keycloak.

Las cuotas/clientes de negocio se crean por API de admin; no deben formar parte
del bootstrap fijo.

- Display name: nombre visible de la aplicacion, por ejemplo `Assermetry`.
  Keycloak usa este valor en la pantalla de autenticacion (por ejemplo,
  `Sign in to Assermetry`). Mantener `TrustNews` como nombre tecnico del realm
  evita cambiar las URLs OIDC, el issuer y la configuracion de los clientes.

---

## 8. Evidence Search

La configuracion contextual vive en MongoDB, coleccion
`evidence_domain_profiles`.

Seeds versionados:

```text
api/evidence-search/config/evidence-domain-profile-default.json
api/evidence-search/config/evidence-normalization-configs.json
```

Dry-run:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --dry-run
```

Carga real del perfil `default` sin borrar otros perfiles:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --refresh --confirm
```

Tras cambiar perfiles o taxonomias se debe limpiar `evidence_search_cache`
mediante `DELETE /admin/cache`, porque los documentos anteriores permanecen
hasta el TTL.

Reiniciar el servicio:

```bash
kubectl rollout restart deployment/evidence-search -n apis
kubectl logs deployment/evidence-search -n apis
```

---

## 9. MongoDB: consultas y limpieza

Entrar a MongoDB:

```bash
kubectl exec -it mongodb-0 -n infra -- mongo -u <root-user> -p <root-password> --authenticationDatabase admin
```

Dentro de MongoDB:

```javascript
use newsdb
show collections
```

Limpiar datos runtime sin borrar cuotas/clientes:

```javascript
db.news.deleteMany({})
db.validations.deleteMany({})
db.events.deleteMany({})
db.clients_quotas.countDocuments()
```

Colecciones principales:

| Coleccion | Servicio principal | Uso |
|---|---|---|
| `news` | `news-handler`, `admin` | Ordenes/noticias, estado del flujo, `postId`, hashes, CIDs y consulta de cuotas. |
| `events` | `news-handler` | Eventos del flujo por `order_id`. |
| `validations` | `news-handler` | Validaciones por orden/asercion/validador. |
| `clients_quotas` | `admin` | Clientes y cuotas disponibles/consumidas. |
| `evidence_domain_profiles` | `evidence-search` | Perfil `default` y dominios preferentes. |
| `evidence_normalization_configs` | `evidence-search` | Taxonomias off-chain. |
| `evidence_search_cache` | `evidence-search` | Cache v2 de busquedas de evidencias. |

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

Los servicios Python desplegados escriben JSON de una sola línea en `stdout`.
Los saltos de línea incluidos en mensajes y tracebacks se escapan dentro del
JSON, de modo que CRI, Fluent Bit y Loki conservan un evento por registro. Las
utilidades CLI de estadísticas mantienen su salida tabular para uso interactivo
y no forman parte de la ingestión normal de Kubernetes.

Datasource Loki:

```text
http://loki.infra.svc.cluster.local:3100
```

Mongo Express:

```bash
kubectl port-forward --address 127.0.0.1 -n infra svc/mongo-express 8081:8081
```

Este procedimiento compartido liga el listener a loopback. La excepción para
acceder desde el host de la VM local está delimitada en
[`skaffold-local.md`](skaffold-local.md#11-acceso-desde-el-host-de-la-vm); no
aplica a producción.
