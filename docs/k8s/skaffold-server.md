# TrustNews Kubernetes - Despliegue server/Hetzner

Runbook operativo para el servidor Hetzner. Los procedimientos compartidos con
local estan en [`k8s-common.md`](k8s-common.md). Este documento mantiene solo lo
especifico de servidor: GitLab CI, perfiles `*-prod`, secretos productivos,
tuneles y verificaciones de despliegue.

---

## 0. Fuentes de verdad y estrategia

- La rama publicada en GitHub `main` se toma como ultima base estable de Hetzner.
- Los cambios nuevos se suben a GitLab en la rama `postTFM`.
- GitLab CI despliega contra el cluster de Hetzner con `.gitlab-ci.yml`.
- Los perfiles productivos son:
  - `setup`: namespaces.
  - `infra-prod`: MongoDB, Kafka, IPFS, Keycloak, mongo-express, logs.
  - `blockchain-prod`: red privada geth.
  - `apis-frontend-prod`: APIs y frontend.

Antes de desplegar una actualizacion importante:

```bash
git fetch origin main
git checkout postTFM
git merge origin/main
git push gitlab postTFM
```

Si el remoto `origin` o `gitlab` no coinciden con el checkout local:

```bash
git remote -v
git branch -vv
```

---

## 1. Variables y accesos requeridos

En el servidor Hetzner debe existir:

- Kubernetes/k3s funcional.
- `kubectl` configurado para administrar el cluster.
- Acceso SSH por el puerto `2222` para el usuario de despliegue.
- GitLab Runner con tag `hetzner-runner`.
- Docker disponible para el job `build` de GitLab.
- Pull secret de GitLab Registry en los namespaces que descargan imagenes privadas.

Variables CI/CD protegidas/enmascaradas del proyecto GitLab:

```dotenv
HETZNER_IP=<ip-publica-hetzner>
HETZNER_USER=<usuario-ssh>
HETZNER_SSH_KEY_B64=<private-key-ssh-en-base64-sin-saltos-de-linea>
KUBECONFIG_DATA=<base64-del-kubeconfig>
PROFILE=apis-frontend-prod
```

`CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER` y
`CI_REGISTRY_PASSWORD` los aporta GitLab.

Si una variable marcada como `Protected` aparece vacia en el pipeline, comprobar
que la rama o tag que ejecuta el pipeline tambien esta protegida. Para el flujo
actual, `postTFM` debe estar en `Settings > Repository > Protected branches` si
las variables de despliegue son `Protected`. Revisar tambien el `Environment
scope`: usar `*` salvo que el job declare explicitamente un environment.

Generar `HETZNER_SSH_KEY_B64` desde la clave privada SSH de despliegue:

```bash
base64 -w0 id_rsa_hetzner_deploy
```

Generar `KUBECONFIG_DATA` desde una maquina con kubeconfig valido:

```bash
base64 -w0 ~/.kube/config
```

El job `deploy` abre un tunel SSH local `127.0.0.1:6443 ->
Hetzner:127.0.0.1:6443` y fuerza el cluster de kubeconfig a
`https://127.0.0.1:6443`. Si el API server no escucha ahi en Hetzner, ajustar
`.gitlab-ci.yml` o el kubeconfig.

---

## 2. Preparar secretos Kubernetes

Ejecutar en el servidor, desde un directorio privado fuera del repo. No
versionar estos `.env`.

### 2.1 Helper idempotente

Usar `apply_secret` en lugar de borrar y recrear secrets manualmente:

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

### 2.3 Inventario obligatorio de secrets

Antes de desplegar `infra-prod`, `blockchain-prod` o `apis-frontend-prod` deben
existir estos secrets. Esta tabla sigue el script operativo de creacion de
secrets.

| Namespace | Secret | Env file |
|---|---|---|
| `apis` | `validator-secret-1` | `worker-1.env` |
| `apis` | `validator-secret-2` | `worker-2.env` |
| `apis` | `validator-secret-3` | `worker-3.env` |
| `apis` | `api-keys` | `generate-asertions.env` |
| `apis` | `news-chain-secrets` | `news-chain.env` |
| `apis` | `news-handler-secrets` | `news-handler.env` |
| `apis` | `gate-config` | `gateway.env` |
| `apis` | `mongodb-secret` | `mongodb.env` |
| `apis` | `search-secret` | `search.env` |
| `apis` | `mongodb-app-secret` | `mongodb-app.env` |
| `infra` | `mongodb-secret` | `mongodb.env` |
| `infra` | `keycloak-admin-secret` | `keycloak.env` |
| `infra` | `keycloak-db-secret` | `keycloak-db.env` |
| `infra` | `mongo-express-secret` | `mongo-express.env` |
| `blockchain` | `ethereum-secrets` | `ethereum.env` |

Crear o actualizar todos los secrets:

```bash
apply_secret apis validator-secret-1 worker-1.env
apply_secret apis validator-secret-2 worker-2.env
apply_secret apis validator-secret-3 worker-3.env
apply_secret apis api-keys generate-asertions.env
apply_secret apis news-chain-secrets news-chain.env
apply_secret apis news-handler-secrets news-handler.env
apply_secret apis gate-config gateway.env
apply_secret apis mongodb-secret mongodb.env
apply_secret apis search-secret search.env
apply_secret apis mongodb-app-secret mongodb-app.env

apply_secret infra mongodb-secret mongodb.env
apply_secret infra keycloak-admin-secret keycloak.env
apply_secret infra keycloak-db-secret keycloak-db.env
apply_secret infra mongo-express-secret mongo-express.env

apply_secret blockchain ethereum-secrets ethereum.env
```

### 2.4 Parametros requeridos por env file

`ethereum.env`:

```dotenv
ACCOUNT_PASSWORD=<informar>
```

`gateway.env`:

```dotenv
# Sin parametros definidos
```

`generate-asertions.env`:

```dotenv
GEMINI_API_KEY=<informar>
OPENROUTER_API_KEY=<informar>
```

`keycloak-db.env`:

```dotenv
ADMIN_PASSWORD=<informar>
ADMIN_USER=<informar>
DB_PASSWORD=<informar>
DB_USER=<informar>
```

`keycloak.env`:

```dotenv
ADMIN_PASSWORD=<informar>
ADMIN_USER=<informar>
DB_PASSWORD=<informar>
DB_USER=<informar>
```

`mongodb-app.env`:

```dotenv
MONGO_APP_AUTHSOURCE=<informar>
MONGO_APP_DATABASE=<informar>
MONGO_APP_HOST=<informar>
MONGO_APP_PORT=<informar>
MONGO_APP_PWD=<informar>
MONGO_APP_USER=<informar>
MONGO_DBNAME=<informar>
```

`mongodb.env`:

```dotenv
MONGO_APP_DATABASE=<informar>
MONGO_APP_PASSWORD=<informar>
MONGO_APP_USERNAME=<informar>
MONGO_INITDB_ROOT_PASSWORD=<informar>
MONGO_INITDB_ROOT_USERNAME=<informar>
```

`mongo-express.env`:

```dotenv
ME_CONFIG_BASICAUTH_PASSWORD=<informar>
ME_CONFIG_BASICAUTH_USERNAME=<informar>
```

`news-chain.env`:

```dotenv
PRIVATE_KEY=<informar>
```

`news-handler.env`:

```dotenv
MONGO_URI=<informar>
```

`search.env`:

```dotenv
API_KEY_PROVIDER=<informar>
```

`worker-1.env`, `worker-2.env`, `worker-3.env`:

```dotenv
ACCOUNT_ADDRESS=<informar>
API_KEY=<informar>
PRIVATE_KEY=<informar>
```

### 2.5 Notas de coherencia de MongoDB

`MONGO_APP_USER`/`MONGO_APP_PWD` de `mongodb-app.env` son las credenciales que
usan las APIs. Deben coincidir con el usuario real creado dentro de MongoDB a
partir de `MONGO_APP_USERNAME`/`MONGO_APP_PASSWORD` en `mongodb.env`.

Si el secret de Kubernetes existe pero el usuario no existe en MongoDB, los pods
pueden arrancar con:

```text
pymongo.errors.OperationFailure: Authentication failed
```

Por eso, despues de levantar MongoDB, ejecutar siempre el bootstrap:

- [`k8s-common.md#6-mongodb-bootstrap`](k8s-common.md#6-mongodb-bootstrap)

### 2.6 TLS frontend, Keycloak y pull secret

TLS de Keycloak, si se usa el secret referenciado por el overlay:

```bash
kubectl create secret tls keycloak-tls-secret \
  --cert=./tls-keycloak.crt \
  --key=./tls-keycloak.key \
  -n infra \
  --dry-run=client -o yaml | kubectl apply -f -
```

El overlay `k8s/frontend` genera `frontend-tls` desde:

```text
web_classic/certs/fullchain.pem
web_classic/certs/privkey.pem
```

En Hetzner deben existir esos ficheros antes de ejecutar
`apis-frontend-prod`, o se debe crear el secret `frontend-tls` manualmente y
ajustar el overlay para no regenerarlo.

Crear un Deploy Token o usar credenciales con permiso `read_registry`. Repetir
en los namespaces que descargan imagenes privadas:

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

---

## 3. Instalacion inicial de un entorno vacio

Usar este flujo solo para una instalacion nueva o una reconstruccion controlada.
No borra PVCs por defecto.

### 3.1 Desplegar infra

Lanzar pipeline manual sobre `postTFM` con:

```dotenv
PROFILE=infra-prod
```

O desde el servidor:

```bash
skaffold deploy -p infra-prod --default-repo registry.gitlab.com/cforcadell/tfm
kubectl rollout status statefulset/mongodb -n infra --timeout=180s
kubectl get pods -n infra
```

Despues de MongoDB, ejecutar el bootstrap idempotente:

- [`k8s-common.md#6-mongodb-bootstrap`](k8s-common.md#6-mongodb-bootstrap)

En GitLab CI, el job `bootstrap_mongodb` se ejecuta automaticamente tras
`deploy` cuando `PROFILE=infra-prod`; tambien queda disponible como job manual
de recuperacion. Antes de desplegar `PROFILE=apis-frontend-prod`, el job
`check_mongodb_bootstrap` falla el pipeline si falta el perfil `default` o las
taxonomias de normalizacion.

### 3.2 Desplegar blockchain

Lanzar pipeline manual con:

```dotenv
PROFILE=blockchain-prod
```

Verificaciones:

- [`k8s-common.md#4-blockchain`](k8s-common.md#4-blockchain)

Diagnostico especifico de Hetzner: si los validadores quedan bloqueados durante
el arranque en `Waiting for application startup` tras enviar una transaccion,
comprobar si el RPC tiene transacciones pendientes y el miner no:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'txpool.status'
```

Si RPC y miner solo estan conectados al bootnode, conectar ambos nodos
temporalmente con `admin.addPeer()` usando el procedimiento comun.

Cuando las transacciones pendientes se minen, reiniciar validadores:

```bash
kubectl rollout restart deployment validate-worker-1 -n apis
kubectl rollout restart deployment validate-worker-2 -n apis
kubectl rollout restart deployment validate-worker-3 -n apis
kubectl rollout status deployment validate-worker-1 -n apis
kubectl rollout status deployment validate-worker-2 -n apis
kubectl rollout status deployment validate-worker-3 -n apis
```

### 3.3 Desplegar o verificar contrato

Si el contrato de la version estable ya existe, conservar la direccion actual y
comprobar bytecode:

```bash
export CONTRACT_ADDRESS=0x<direccion-trust-news>
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- \
  geth attach --exec "eth.getCode('$CONTRACT_ADDRESS')"
```

Si se despliega contrato nuevo, abrir tunel al RPC desde la maquina de trabajo:

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

Inicializar o verificar categorias:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network cloudGeth
npx hardhat run scripts/initCategories.js --network cloudGeth
unset DEPLOYER_PRIVATE_KEY
```

### 3.4 Actualizar direccion de contrato antes de APIs

Los overlays prod contienen la direccion en estos ficheros:

```text
k8s/apis/news-chain/overlays/prod/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-1/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-2/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-3/kustomization.yaml
```

Antes de desplegar `apis-frontend-prod`, cambiar todos los `CONTRACT_ADDRESS` si
se ha desplegado contrato nuevo. Confirmar tambien que `ACCOUNT_ADDRESS` de
`news-chain` coincide con la cuenta de `news-chain.env`.

Si el ABI cambia:

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

---

## 4. Actualizacion normal desde GitLab CI

Preflight local:

```bash
git checkout postTFM
git fetch origin main
git merge origin/main
git status --short
```

Comprobar si el cambio toca contrato u overlays:

```bash
git diff --name-only origin/main...HEAD | grep -E 'smart-contracts|k8s/apis/.*/overlays/prod/.*/kustomization.yaml|k8s/apis/news-chain/overlays/prod/kustomization.yaml' || true
```

Si toca contrato, repetir las secciones 3.3 y 3.4 antes de desplegar APIs.

Subir a GitLab:

```bash
git push gitlab postTFM
```

En GitLab:

1. Abrir `Build > Pipelines > Run pipeline`.
2. Branch: `postTFM`.
3. Variable `PROFILE=apis-frontend-prod`.
4. Ejecutar `build` y luego `deploy`.

El job `deploy` ejecuta:

```bash
skaffold deploy --build-artifacts=build.json --profile=$PROFILE
```

El pipeline solo construye automaticamente si hay cambios en `api/**`,
`web_classic/**`, `skaffold.yaml` o `k8s/apis/**`; para cambios de docs, infra,
blockchain o certificados puede ser necesario ejecutar el job manualmente.

---

## 5. Verificacion despues de CI

```bash
kubectl get pods -n apis -o wide
kubectl get pods -n frontend -o wide
kubectl logs deployment/gateway -n apis --tail=80
kubectl logs deployment/news-handler -n apis --tail=80
kubectl logs deployment/evidence-search -n apis --tail=80
```

Probar frontend mediante tunel:

```bash
# En Hetzner
kubectl port-forward service/frontend-service -n frontend 10443:443

# En local
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 9443:127.0.0.1:10443 \
  <usuario>@<hetzner-ip>
```

Abrir:

```text
https://localhost:9443/
https://localhost:9443/backend/docs
```

Keycloak:

```text
https://localhost:9443/auth/admin/master/console/
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

---

## 6. Operacion y recuperacion server

Rollback manual:

```bash
kubectl rollout undo deployment/gateway -n apis
kubectl rollout undo deployment/news-handler -n apis
kubectl rollout undo deployment/evidence-search -n apis
kubectl rollout undo deployment/frontend-web -n frontend
kubectl rollout status deployment/gateway -n apis --timeout=180s
```

Limpieza destructiva de PVCs. Solo para reconstruccion completa y con backup:

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

Si Docker falla descargando imagenes base conocidas:

```bash
docker pull mirror.gcr.io/library/python:3.11-slim
docker tag mirror.gcr.io/library/python:3.11-slim python:3.11-slim
```

---

## 7. Checklist rapido server

Antes de `apis-frontend-prod`:

- `postTFM` contiene la base de `origin/main`.
- Los secrets del inventario obligatorio existen en `apis`, `infra` y `blockchain`.
- `gitlab-pull-secret` esta asociado al service account de `apis`, `infra`, `frontend` y `blockchain`.
- `frontend-tls` existe o los certificados estan disponibles para el generator de `k8s/frontend`.
- `CONTRACT_ADDRESS` en overlays prod coincide con el contrato desplegado.
- `initCategories.js` se ha ejecutado y la segunda ejecucion no cambia nada.
- `scripts/k8s/init-mongodb-server.sh` se ha ejecutado despues de levantar MongoDB.
- El pipeline GitLab usa `PROFILE=apis-frontend-prod` para actualizaciones normales.
