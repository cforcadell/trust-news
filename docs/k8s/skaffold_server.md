# Despliegue Trust News en Hetzner

Este documento es el runbook operativo para el servidor Hetzner. Mantiene en un unico sitio:

- instalacion inicial de un entorno vacio;
- actualizacion normal desde GitLab CI usando la rama `postTFM`;
- verificaciones y operaciones de recuperacion.

El despliegue local paso a paso sigue documentado en [`skaffold-v2.md`](skaffold-v2.md). En Hetzner se usan los perfiles `*-prod` de `skaffold.yaml` y los secretos se crean fuera del repo.

## 0. Fuentes de verdad y estrategia

- La rama publicada en GitHub `main` se toma como ultima base estable de Hetzner.
- Los cambios nuevos se suben a GitLab en la rama `postTFM`.
- GitLab CI despliega contra el cluster de Hetzner con `.gitlab-ci.yml`.
- Los perfiles productivos son:
  - `setup`: namespaces.
  - `infra-prod`: MongoDB, Kafka, IPFS, Keycloak, mongo-express, logs.
  - `blockchain-prod`: red privada geth.
  - `apis-frontend-prod`: APIs y frontend.

Antes de desplegar una actualizacion importante, sincronizar `postTFM` con la base estable:

```bash
git fetch origin main
git checkout postTFM
git merge origin/main
# resolver conflictos si aparecen
git push gitlab postTFM
```

Si el remoto `origin` o `gitlab` no coinciden con tu checkout local, verificar primero:

```bash
git remote -v
git branch -vv
```

## 1. Variables y accesos requeridos

### 1.1 Servidor y cluster

En el servidor Hetzner debe existir:

- Kubernetes/k3s funcional.
- `kubectl` configurado para administrar el cluster.
- Acceso SSH por el puerto `2222` para el usuario de despliegue.
- GitLab Runner con tag `hetzner-runner`.
- Docker disponible para el job `build` de GitLab, normalmente con acceso al socket Docker del host.
- Pull secret de GitLab Registry en los namespaces que descargan imagenes privadas.

### 1.2 Variables CI/CD en GitLab

Definir como variables protegidas/enmascaradas del proyecto GitLab:

```dotenv
HETZNER_IP=<ip-publica-hetzner>
HETZNER_USER=<usuario-ssh>
HETZNER_SSH_KEY=<private-key-ssh>
KUBECONFIG_DATA=<base64-del-kubeconfig>
PROFILE=apis-frontend-prod
```

`CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER` y `CI_REGISTRY_PASSWORD` los aporta GitLab.

Para generar `KUBECONFIG_DATA` desde una maquina que ya tenga kubeconfig valido:

```bash
base64 -w0 ~/.kube/config
```

El job `deploy` abre un tunel SSH local `127.0.0.1:6443 -> Hetzner:127.0.0.1:6443` y fuerza el cluster de kubeconfig a `https://127.0.0.1:6443`. Si el API server no escucha ahi en Hetzner, ajustar `.gitlab-ci.yml` o el kubeconfig.

Nota sobre rollback: el job `rollback` actual no abre el tunel SSH. Si `KUBECONFIG_DATA` depende del tunel a `127.0.0.1:6443`, hacer rollback manual desde el servidor o replicar en ese job el mismo bloque SSH del job `deploy`.

## 2. Preparar secretos Kubernetes

Ejecutar en el servidor, desde un directorio privado fuera del repo. No versionar estos `.env`.

### 2.1 Helper idempotente

```bash
apply_secret() {
  local namespace="$1"
  local name="$2"
  local file="$3"
  kubectl create secret generic "$name" \
    --from-env-file="$file" \
    -n "$namespace" \
    --dry-run=client -o yaml | kubectl apply -f -
}
```

### 2.2 Namespaces

```bash
kubectl apply -f k8s/namespaces.yaml
kubectl get ns blockchain infra apis frontend
```

### 2.3 Secretos de infraestructura

`mongodb.env` debe contener:

```dotenv
MONGO_INITDB_ROOT_USERNAME=<root-user>
MONGO_INITDB_ROOT_PASSWORD=<root-password>
MONGO_APP_USERNAME=<application-user>
MONGO_APP_PASSWORD=<application-password>
MONGO_APP_DATABASE=newsdb
```

`mongodb-app.env` debe contener las claves que leen las APIs:

```dotenv
MONGO_APP_USER=<application-user>
MONGO_APP_PWD=<application-password>
MONGO_APP_HOST=mongodb.infra.svc.cluster.local
MONGO_APP_PORT=27017
MONGO_APP_DATABASE=newsdb
MONGO_DBNAME=newsdb
MONGO_APP_AUTHSOURCE=newsdb
```

`MONGO_APP_USER`/`MONGO_APP_PWD` son las credenciales que usaran las APIs. Deben
coincidir exactamente con el usuario real creado dentro de MongoDB mediante
`MONGO_APP_USERNAME`/`MONGO_APP_PASSWORD` en `mongodb.env`. Si el secreto de
Kubernetes existe pero el usuario no existe en MongoDB, los pods arrancaran con
`pymongo.errors.OperationFailure: Authentication failed`.

`keycloak-admin.env`:

```dotenv

ADMIN_USER=<admin-user>
ADMIN_PASSWORD=<admin-password>
DB_USER=<user_app_db> 
DB_PASSWORD=<pwd_app_db>


```

`keycloak-db.env`:

```dotenv
ADMIN_USER=<user_admin>
ADMIN_PASSWORD=<user_pwd> 
DB_USER=<user_app_db>  
DB_PASSWORD=<pwd_app_db>

```

`mongo-express.env`:

```dotenv
ME_CONFIG_BASICAUTH_USERNAME=<user>
ME_CONFIG_BASICAUTH_PASSWORD=<password>
```

Crear/aplicar:

```bash
apply_secret infra mongodb-secret mongodb.env
apply_secret apis mongodb-app-secret mongodb-app.env
apply_secret infra keycloak-admin-secret keycloak-admin.env
apply_secret infra keycloak-db-secret keycloak-db.env
apply_secret infra mongo-express-secret mongo-express.env
```

TLS de Keycloak, si se usa el secreto referenciado por el overlay:

```bash
kubectl create secret tls keycloak-tls-secret \
  --cert=./tls-keycloak.crt \
  --key=./tls-keycloak.key \
  -n infra \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 2.4 Secretos blockchain y APIs

`ethereum.env` debe contener las claves usadas por geth en `ethereum-secrets` segun el overlay de blockchain.

`generate-asertions.env` debe contener al menos la clave del proveedor activo. Con la configuracion actual el proveedor por defecto es OpenRouter:

```dotenv
OPENROUTER_API_KEY=<token>
# opcional si cambias proveedor/modelo por env:
# GEMINI_API_KEY=<token>
# MISTRAL_API_KEY=<token>
```

`search.env` para `evidence-search`:

```dotenv
API_KEY_PROVIDER=<exa-o-tavily-api-key>
```

Con la configuracion actual `SEARCH_PROVIDER=exa` y `SEARCH_API_URL=https://api.exa.ai/search` estan en el ConfigMap.

`news-chain.env`:

```dotenv
PRIVATE_KEY=<private-key-de-account-address>
```

`worker-1.env`, `worker-2.env`, `worker-3.env`:

```dotenv
PRIVATE_KEY=<validator-private-key>
ACCOUNT_ADDRESS=<validator-address>
API_KEY=<llm-provider-api-key>
```

Crear/aplicar:

```bash
apply_secret blockchain ethereum-secrets ethereum.env
apply_secret apis api-keys generate-asertions.env
apply_secret apis search-secret search.env
apply_secret apis news-chain-secrets news-chain.env
apply_secret apis validator-secret-1 worker-1.env
apply_secret apis validator-secret-2 worker-2.env
apply_secret apis validator-secret-3 worker-3.env
```

### 2.5 Frontend TLS

El overlay `k8s/frontend` genera `frontend-tls` desde:

```text
web_classic/certs/fullchain.pem
web_classic/certs/privkey.pem
```

En Hetzner deben existir esos ficheros antes de ejecutar `apis-frontend-prod`, o se debe crear el secreto `frontend-tls` manualmente y ajustar el overlay para no regenerarlo.

### 2.6 Pull secret del GitLab Registry

Crear un Deploy Token o usar credenciales con permiso `read_registry`. Repetir en los namespaces que descargan imagenes privadas:

```bash
for ns in apis infra frontend blockchain; do
  kubectl create secret docker-registry gitlab-pull-secret \
    --docker-server=registry.gitlab.com \
    --docker-username=<gitlab-deploy-token-user> \
    --docker-password=<gitlab-deploy-token-password> \
    --docker-email=<email> \
    --namespace="$ns" \
    --dry-run=client -o yaml | kubectl apply -f -

  kubectl patch serviceaccount default \
    -n "$ns" \
    -p '{"imagePullSecrets":[{"name":"gitlab-pull-secret"}]}'
done
```

## 3. Instalacion inicial de un entorno vacio

Usar este flujo solo para una instalacion nueva o una reconstruccion controlada. No borra PVCs por defecto.

### 3.1 Desplegar infra

Desde GitLab, lanzar pipeline manual sobre `postTFM` con:

```dotenv
PROFILE=infra-prod
```

O desde el servidor, si se despliega manualmente:

```bash
skaffold deploy -p infra-prod --default-repo registry.gitlab.com/cforcadell/tfm
kubectl rollout status statefulset/mongodb -n infra --timeout=180s
kubectl get pods -n infra
```

Despues de MongoDB, ejecutar siempre el bootstrap idempotente. En GitLab CI,
el job `bootstrap_mongodb` se ejecuta automaticamente tras `deploy` cuando
`PROFILE=infra-prod`; tambien queda disponible como job manual de recuperacion.
Antes de desplegar `PROFILE=apis-frontend-prod`, el job `check_mongodb_bootstrap`
falla el pipeline si falta el perfil `default` o las taxonomias de normalizacion.

Si se hace a mano desde el servidor:

```bash
scripts/k8s/init-mongodb-server.sh --dry-run
scripts/k8s/init-mongodb-server.sh
```

Este paso es obligatorio tambien cuando el `mongodb-app-secret` ya existe:
crea o actualiza dentro de MongoDB el usuario de aplicacion usado por
`MONGO_APP_USER`, con permisos `readWrite` sobre `MONGO_APP_DATABASE`.

El script:

- crea/actualiza el usuario de aplicacion;
- crea indices de `news`, `clients_quotas`, `events`, `validations` y `evidence_search_cache`;
- reemplaza solo el perfil `default` de `evidence_domain_profiles`;
- inserta/actualiza `evidence_normalization_configs`;
- limpia por defecto la cache `evidence_search_cache`.

Verificacion esperada del perfil actual:

```bash
kubectl exec -it mongodb-0 -n infra -- sh -c \
  'mongo -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "$MONGO_APP_DATABASE" --quiet --eval "const p=db.evidence_domain_profiles.findOne({profile_id: \"default\"}); printjson({profiles: db.evidence_domain_profiles.countDocuments({profile_id: \"default\"}), normalization: db.evidence_normalization_configs.countDocuments({}), domains: p ? p.domains.length : 0})"'
```

Resultado esperado en esta version:

```text
profiles: 1
normalization: 3
domains: 500
```

### 3.2 Desplegar blockchain

Lanzar pipeline manual con:

```dotenv
PROFILE=blockchain-prod
```

Verificar peers y bloques:

```bash
kubectl get pods -n blockchain
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "eth.blockNumber"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "eth.blockNumber"
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec "eth.blockNumber"
```

Verificar transacciones pendientes y recibos:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getTransactionReceipt("0x5ea06048912ba0cebe91ff428c7058def03cf4e5024c7a5e6b4fd7326f294675")'
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
```

### 3.2.1 Diagnostico: transacciones pendientes en RPC que no se minan

En produccion/Hetzner puede ocurrir que los validadores `validate-worker-*` se queden bloqueados durante el arranque en:

```text
INFO: Waiting for application startup.
Inicio update_validator_config_blockchain -> ipfs_config_hash: ...
Transaccion enviada: 0x...
```

Y que nunca aparezca:

```text
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8070
```

La causa observada fue que la transaccion enviada por el validador al nodo RPC quedo en el `txpool` del RPC, pero no llego al minero.

Comprobar el `txpool` del RPC:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
```

Salida problematica:

```text
{
  pending: 10,
  queued: 0
}
```

Comprobar el `txpool` del minero:

```bash
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'txpool.status'
```

Salida problematica:

```text
{
  pending: 0,
  queued: 0
}
```

Comprobar el receipt de una transaccion pendiente:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getTransactionReceipt("TX_HASH")'
```

Salida problematica:

```text
null
```

Este caso indica que:

- el RPC recibe transacciones;
- el minero no las recibe;
- por tanto, la transaccion no se mina;
- los validadores quedan bloqueados esperando el receipt;
- el puerto HTTP del validador puede no abrirse porque FastAPI sigue en `Waiting for application startup`.

Comprobar numero de peers:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'net.peerCount'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'net.peerCount'
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec 'net.peerCount'
```

Caso observado:

```text
rpc: 1
miner: 1
bootnode: 2
```

Aunque los tres nodos esten en el mismo bloque:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.blockNumber'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'eth.blockNumber'
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec 'eth.blockNumber'
```

El problema puede seguir existiendo si RPC y miner solo estan conectados al bootnode, no entre ellos.

Confirmar los peers reales sin usar arrow functions, porque la consola JS de `geth attach` puede no soportar `=>`:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.peers.map(function(p){ return p.name + " " + p.network.remoteAddress })'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.peers.map(function(p){ return p.name + " " + p.network.remoteAddress })'
```

Caso observado:

```text
["Geth/... 10.42.0.56:30303"]
```

Si `10.42.0.56` es `geth-bootnode-0`, queda confirmada esta topologia incorrecta:

```text
rpc   ---> bootnode
miner ---> bootnode
```

Y falta la conexion directa:

```text
rpc <--> miner
```

Solucion manual temporal con `admin.addPeer()`:

```bash
kubectl get pods -n blockchain -o wide
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.nodeInfo.enode'
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.nodeInfo.enode'
```

Conectar RPC hacia miner:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("ENODE_DEL_MINER")'
```

Opcionalmente, conectar miner hacia RPC:

```bash
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.addPeer("ENODE_DEL_RPC")'
```

Ejemplo real observado:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("enode://2902482757cd755c3e5fdb6632b23cfd3205140843211aa11fd20c5fe7809e717ff323d1c3e94e9e02eb7818dea8a8309d748937f7719c73d6c11f35d21946cb@10.42.0.54:30305")'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.addPeer("enode://e57a9ffb627bcb8808e77d15b84457cd2b9e61d9354cb13157888e5916fb005d44bc2d87b4eaedbaeed87fb08d28344aadd4a6f2a9a9131d8dae0e0792c769da@10.42.0.55:30304")'
```

Validar que ambos nodos tienen dos peers:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'net.peerCount'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'net.peerCount'
```

Resultado esperado:

```text
2
2
```

Comprobar que la transaccion pendiente ya se mina:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getTransactionReceipt("TX_HASH")'
```

Resultado esperado:

```text
{
  blockNumber: ...,
  status: "0x1",
  ...
}
```

Comprobar de nuevo el `txpool`:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'txpool.status'
```

Una vez minadas las transacciones pendientes, reiniciar los validadores:

```bash
kubectl rollout restart deployment validate-worker-1 -n apis
kubectl rollout restart deployment validate-worker-2 -n apis
kubectl rollout restart deployment validate-worker-3 -n apis
kubectl rollout status deployment validate-worker-1 -n apis
kubectl rollout status deployment validate-worker-2 -n apis
kubectl rollout status deployment validate-worker-3 -n apis
```

Logs esperados:

```text
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8070
```

Importante: `admin.addPeer()` es una solucion manual y no persistente. Si se reinician los pods de blockchain, puede perderse y habra que repetir el procedimiento.

### 3.3 Desplegar o verificar contrato

Si el contrato de la version estable ya existe, conservar la direccion actual y comprobar bytecode:

```bash
export CONTRACT_ADDRESS=0x<direccion-trust-news>
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- \
  geth attach --exec "eth.getCode('$CONTRACT_ADDRESS')"
```

Si se despliega contrato nuevo, abrir tunel al RPC desde tu maquina de trabajo:

```bash
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 8565:localhost:8555 \
  <usuario>@<hetzner-ip> \
  -t "kubectl port-forward pod/geth-rpc-endpoint-0 -n blockchain 8555:8555"
```

En otra terminal:

```bash
cd smart-contracts
read -rsp "Deployer private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/deployGeth.js --network cloudGeth
unset DEPLOYER_PRIVATE_KEY
```

Guardar la direccion mostrada como `CONTRACT_ADDRESS`.

Inicializar o verificar categorias on-chain. Es idempotente si se usa el propietario del contrato:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network cloudGeth
npx hardhat run scripts/initCategories.js --network cloudGeth
unset DEPLOYER_PRIVATE_KEY
```

La segunda ejecucion debe mostrar las diez categorias como `unchanged`. Si hay `mismatch`, no continuar: el contrato no corresponde a la version esperada o las categorias no coinciden con `smart-contracts/config/categories.json`.

### 3.4 Actualizar direccion de contrato antes de APIs

Los overlays prod contienen la direccion en estos ficheros:

```text
k8s/apis/news-chain/overlays/prod/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-1/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-2/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-3/kustomization.yaml
```

Antes de desplegar `apis-frontend-prod`, cambiar todos los `CONTRACT_ADDRESS` si se ha desplegado contrato nuevo. Confirmar tambien que `ACCOUNT_ADDRESS` de `news-chain` coincide con la cuenta de `news-chain.env`.

Si el contrato ABI cambia, regenerar el artefacto y confirmar que existe:

```bash
cd smart-contracts
npx hardhat compile
test -f artifacts/contracts/TrustNews.sol/TrustNews.json
```

### 3.5 Desplegar APIs y frontend

Lanzar pipeline manual con:

```dotenv
PROFILE=apis-frontend-prod
```

Verificar rollouts:

```bash
kubectl get pods -n apis
kubectl get pods -n frontend
kubectl rollout status deployment/gateway -n apis --timeout=180s
kubectl rollout status deployment/news-handler -n apis --timeout=180s
kubectl rollout status deployment/evidence-search -n apis --timeout=180s
kubectl rollout status deployment/frontend-web -n frontend --timeout=180s
```

## 4. Actualizacion normal desde GitLab CI

Usar este flujo para desplegar commits ya subidos a `postTFM`.

### 4.1 Preflight local

```bash
git checkout postTFM
git fetch origin main
git merge origin/main
git status --short
```

Comprobar si el cambio toca contrato o overlays de contrato:

```bash
git diff --name-only origin/main...HEAD | grep -E 'smart-contracts|k8s/apis/.*/overlays/prod/.*/kustomization.yaml|k8s/apis/news-chain/overlays/prod/kustomization.yaml' || true
```

Si toca contrato, repetir las secciones 3.3 y 3.4 antes de desplegar APIs.

Subir a GitLab:

```bash
git push gitlab postTFM
```

### 4.2 Ejecutar pipeline

En GitLab:

1. Abrir `Build > Pipelines > Run pipeline`.
2. Branch: `postTFM`.
3. Variable `PROFILE=apis-frontend-prod`.
4. Ejecutar `build` y luego `deploy`.

El job `build` genera `build.json` con las imagenes exactas. El job `deploy` ejecuta:

```bash
skaffold deploy --build-artifacts=build.json --profile=$PROFILE
```

El pipeline solo construye automaticamente si hay cambios en `api/**`, `web_classic/**`, `skaffold.yaml` o `k8s/apis/**`; para cambios de docs, infra, blockchain o certificados puede ser necesario ejecutar el job manualmente.

### 4.3 Verificacion despues de CI

```bash
kubectl get pods -n apis -o wide
kubectl get pods -n frontend -o wide
kubectl logs deployment/gateway -n apis --tail=80
kubectl logs deployment/news-handler -n apis --tail=80
kubectl logs deployment/evidence-search -n apis --tail=80
```

Ejemplo para probar un endpoint directamente dentro del pod, sin instalar nada adicional:

```bash
kubectl exec -it news-handler-59c79887fd-224k4 -n apis -- /bin/bash
python3 - <<'PY'
import requests
r = requests.get(
    "http://localhost:8072/validators/cache",
    params={"recover_ipfs": "false"},
    headers={"accept": "application/json"},
)
print(r.status_code)
print(r.text)
PY
```

```bash
kubectl exec -it validate-worker-1-5776658d65-9fsh8 -n apis -- /bin/bash
python3 - <<'PY'
import requests
r = requests.get(
    "http://localhost:8070/health",
    headers={"accept": "application/json"},
)
print(r.status_code)
print(r.text)
PY
```

Probar frontend mediante tunel:

```bash
#in hetzner (~/trust-news/scripts/port-forward.sh)
kubectl port-forward service/frontend-service -n frontend 10443:443

# in local vm machine ~/blockchain/hetzner/keys-github (dev)
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 9443:127.0.0.1:10443 \
  <usuario>@<hetzner-ip>
```



Abrir:

```text
https://localhost:9443/
https://localhost:9443/backend/docs
```

## 5. Keycloak y cuotas

Acceder a Keycloak:

```text
https://localhost:9443/auth/admin/master/console/
```

Configuracion minima:

- Realm: `TrustNews`.
- Cliente frontend: `TrustNewsWeb`.
  - Root URL: URL publica del frontend.
  - Valid redirect URIs: `<frontend-url>/*`.
  - Web Origins: URL publica del frontend, o `*` solo para pruebas.
- Cliente backend: `TrustNewsApi`.
  - Client authentication: ON.
  - Service accounts roles: ON.
  - Guardar el client secret para clientes externos.

Obtener token de prueba:

```bash
curl -k -X POST https://localhost:9443/auth/realms/TrustNews/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=TrustNewsApi" \
  -d "client_secret=<secret>"
```

Admin/quotas mediante tunel:

```bash
# En Hetzner
kubectl port-forward service/admin-service -n apis 7400:8400

# En local
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 7400:127.0.0.1:7400 \
  <usuario>@<hetzner-ip>
```

Abrir:

```text
http://127.0.0.1:7400/docs
```

Las cuotas/clientes de negocio se crean por API de admin; no deben formar parte del bootstrap fijo.

## 6. Operacion y recuperacion

### 6.1 Reinicios conservando PVCs

```bash
kubectl scale deployment --all --replicas=0 -n apis
kubectl scale deployment --all --replicas=1 -n apis

kubectl scale statefulset --all --replicas=0 -n infra
kubectl scale statefulset --all --replicas=1 -n infra

kubectl scale statefulset --all --replicas=0 -n blockchain
kubectl scale statefulset --all --replicas=1 -n blockchain
```

### 6.2 Rollback manual

```bash
kubectl rollout undo deployment/gateway -n apis
kubectl rollout undo deployment/news-handler -n apis
kubectl rollout undo deployment/evidence-search -n apis
kubectl rollout undo deployment/frontend-web -n frontend
kubectl rollout status deployment/gateway -n apis --timeout=180s
```

### 6.3 Limpieza destructiva de PVCs

Solo para reconstruccion completa. Hacer backup antes.

```bash
kubectl get pvc -n infra
kubectl get pvc -n blockchain

kubectl delete pvc ipfs-storage-ipfs-0 -n infra
kubectl delete pvc kafka-data-kafka-0 -n infra
kubectl delete pvc mongodb-storage-mongodb-0 -n infra
kubectl delete pvc bootnode-data-geth-bootnode-0 -n blockchain
kubectl delete pvc miner-data-geth-miner-0 -n blockchain
kubectl delete pvc rpc-data-geth-rpc-endpoint-0 -n blockchain
```

### 6.4 Mongo Express

```bash
kubectl port-forward --address 0.0.0.0 -n infra svc/mongo-express 8081:8081
```

Abrir:

```text
http://localhost:8081
```

### 6.5 Grafana/Loki

```bash
kubectl port-forward service/grafana -n infra 3300:3000
```

Datasource Loki:

```text
http://loki.infra.svc.cluster.local:3100
```

### 6.6 Imagenes base con pull rate limit

Si Docker falla descargando imagenes base conocidas:

```bash
docker pull mirror.gcr.io/library/python:3.11-slim
docker tag mirror.gcr.io/library/python:3.11-slim python:3.11-slim
```

## 7. Checklist rapido

Antes de `apis-frontend-prod`:

- `postTFM` contiene la base de `origin/main`.
- `mongodb-app-secret`, `api-keys`, `search-secret`, `news-chain-secrets` y `validator-secret-{1,2,3}` existen en `apis`.
- `mongodb-secret`, `keycloak-admin-secret`, `keycloak-db-secret` y `mongo-express-secret` existen en `infra`.
- `ethereum-secrets` existe en `blockchain`.
- `gitlab-pull-secret` esta asociado al service account de `apis`, `infra`, `frontend` y `blockchain`.
- `frontend-tls` existe o los certificados estan disponibles para el generator de `k8s/frontend`.
- `CONTRACT_ADDRESS` en overlays prod coincide con el contrato desplegado.
- `initCategories.js` se ha ejecutado y la segunda ejecucion no cambia nada.
- `scripts/k8s/init-mongodb-server.sh` se ha ejecutado despues de levantar MongoDB.
- El pipeline GitLab usa `PROFILE=apis-frontend-prod` para actualizaciones normales.
