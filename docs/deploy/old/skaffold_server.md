# Trust News deployment in Hetzner

> [!WARNING]
> **ARCHIVADO — NOT USE.** Historical reference; see
> [`README.md`](README.md) and runbooks are in place before operation.

This document is the operating runbook for the Hetzner server. It maintains in one site:

- initial installation of an empty environment;
- normal update from GitLab CI using the `postTFM` branch;
- verifications and recovery operations.

The local step-by-step deployment is still documented in [`skaffold-v2.md`](skaffold-v2.md). In Hetzner, `*-prod` profiles of `skaffold.yaml` are used and secrets are created outside the repo.

## 0. Sources of truth and strategy

- The branch published in GitHub `main` is taken as the last stable base of Hetzner.
- New changes are uploaded to GitLab in the `postTFM` branch.
- GitLab CI deploys against the Hetzner cluster with `.gitlab-ci.yml`.
- The production profiles are:
  - `setup`: namespaces.
  - `infra-prod`: MongoDB, Kafka, IPFS, Keycloak, mongo-express, logs.
  - `blockchain-prod`: red privada geth.
  - `apis-frontend-prod`: APIs and frontend.

Before deploying an important update, sync `postTFM` to the stable base:

```bash
git fetch origin main
git checkout postTFM
git merge origin/main
# resolver conflictos si aparecen
git push gitlab postTFM
```

If the remote `origin` or `gitlab` do not match your local checkout, check first:

```bash
git remote -v
git branch -vv
```

## 1. Variables and accesses required

### 1.1 Server and cluster

On the Hetzner server there must be:

- Kubernetes/k3s functional.
- `kubectl` configured to manage the cluster.
- SSH access via `2222` port for deployment user.
- GitLab Runner with tag `hetzner-runner`.
- Docker available for GitLab's `build` job, usually with access to the host's Docker socket.
- Pull secret de GitLab Registry en los namespaces que descargan imagenes privadas.

### 1.2 CI/CD Variables in GitLab

Define protegidas/enmascaradas variables for the GitLab project:

```dotenv
HETZNER_IP=<ip-publica-hetzner>
HETZNER_USER=<usuario-ssh>
HETZNER_SSH_KEY=<private-key-ssh>
KUBECONFIG_DATA=<base64-del-kubeconfig>
PROFILE=apis-frontend-prod
```

`CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER` and `CI_REGISTRY_PASSWORD` are provided by GitLab.

To generate `KUBECONFIG_DATA` from a machine that already has valid kubeconfig:

```bash
base64 -w0 ~/.kube/config
```

The `deploy` job opens a local SSH `127.0.0.1:6443 -> Hetzner:127.0.0.1:6443` tunnel and forces the kubeconfig cluster to `https://127.0.0.1:6443`. If the server API does not listen there in Hetzner, adjust `.gitlab-ci.yml` or the kubeconfig.

Note on rollback: the current `rollback` job does not open the SSH tunnel. If `KUBECONFIG_DATA` depends on the tunnel to `127.0.0.1:6443`, make manual rollback from the server or replicate the same SSH block of the job `deploy` into that job.

## 2. Preparar secretos Kubernetes

Run on the server, from a private directory outside the repo. Do not re-version these `.env`.

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

### 2.3 Infrastructure secrets

`mongodb.env` must contain:

```dotenv
MONGO_INITDB_ROOT_USERNAME=<root-user>
MONGO_INITDB_ROOT_PASSWORD=<root-password>
MONGO_APP_USERNAME=<application-user>
MONGO_APP_PASSWORD=<application-password>
MONGO_APP_DATABASE=newsdb
```

`mongodb-app.env` must contain the keys that read APIs:

```dotenv
MONGO_APP_USER=<application-user>
MONGO_APP_PWD=<application-password>
MONGO_APP_HOST=mongodb.infra.svc.cluster.local
MONGO_APP_PORT=27017
MONGO_APP_DATABASE=newsdb
MONGO_DBNAME=newsdb
MONGO_APP_AUTHSOURCE=newsdb
```

`MONGO_APP_USER`/`MONGO_APP_PWD` are the credentials that will use APIs. They must match exactly the real user created within MongoDB by `MONGO_APP_USERNAME`/`MONGO_APP_PASSWORD` in `mongodb.env`. If the Kubernetes secret exists but the user does not exist in MongoDB, the pods will boot with `pymongo.errors.OperationFailure: Authentication failed`.

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

Keycloak TLS, if the secret referenced by the overlay is used:

```bash
kubectl create secret tls keycloak-tls-secret \
  --cert=./tls-keycloak.crt \
  --key=./tls-keycloak.key \
  -n infra \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 2.4 Blockchain Secrets and APIs

`ethereum.env` must contain the keys used by geth in `ethereum-secrets` according to the blockchain overlay.

`generate-asertions.env` must contain at least the key of the active provider. With the current configuration the default provider is OpenRouter:

```dotenv
OPENROUTER_API_KEY=<token>
# opcional si cambias proveedor/modelo por env:
# GEMINI_API_KEY=<token>
# MISTRAL_API_KEY=<token>
```

`search.env` for `evidence-search`:

```dotenv
API_KEY_PROVIDER=<exa-o-tavily-api-key>
```

With the current `SEARCH_PROVIDER=exa` and `SEARCH_API_URL=https://api.exa.ai/search` configuration they are in the ConfigMap.

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

The overlay `k8s/frontend` generates `frontend-tls` from:

```text
web_classic/certs/fullchain.pem
web_classic/certs/privkey.pem
```

In Hetzner, those files must exist before running `apis-frontend-prod`, or the secret `frontend-tls` must be created manually and the overlay must be adjusted to avoid regeneration.

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

## 3. Initial installation of an empty environment

Use this flow only for a new installation or a controlled reconstruction. It does not delete PVCs by default.

### 3.1 Desplegar infra

From GitLab, launch manual pipeline on `postTFM` with:

```dotenv
PROFILE=infra-prod
```

Or from the server, if it is manually displayed:

```bash
skaffold deploy -p infra-prod --default-repo registry.gitlab.com/cforcadell/tfm
kubectl rollout status statefulset/mongodb -n infra --timeout=180s
kubectl get pods -n infra
```

After MongoDB, always run the idempotent bootstrap. In GitLab CI, the `bootstrap_mongodb` job is automatically run after `deploy` when `PROFILE=infra-prod`; it is also available as a manual recovery job. Before deploying `PROFILE=apis-frontend-prod`, the `check_mongodb_bootstrap` job fails the pipeline if the `default` profile or the normalization taxonomies is missing.

If done by hand from the server:

```bash
scripts/k8s/init-mongodb-server.sh --dry-run
scripts/k8s/init-mongodb-server.sh
```

Este paso es obligatorio tambien cuando el `mongodb-app-secret` ya existe:
crea o actualiza dentro de MongoDB el usuario de aplicacion usado por
`MONGO_APP_USER`, con permisos `readWrite` sobre `MONGO_APP_DATABASE`.

The script:

- crea/actualiza application user;
- creates `news`, `clients_quotas`, `events`, `validations` and `evidence_search_cache` indexes;
- replaces only the `default` profile of `evidence_domain_profiles`;
- inserta/actualiza `evidence_normalization_configs`;
- cleans the `evidence_search_cache` cache by default.

Expected verification of the current profile:

```bash
kubectl exec -it mongodb-0 -n infra -- sh -c \
  'mongo -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "$MONGO_APP_DATABASE" --quiet --eval "const p=db.evidence_domain_profiles.findOne({profile_id: \"default\"}); printjson({profiles: db.evidence_domain_profiles.countDocuments({profile_id: \"default\"}), normalization: db.evidence_normalization_configs.countDocuments({}), domains: p ? p.domains.length : 0})"'
```

Expected result in this version:

```text
profiles: 1
normalization: 3
domains: 500
```

### 3.2 Desplegar blockchain

Launch manual pipeline with:

```dotenv
PROFILE=blockchain-prod
```

Check peer and block:

```bash
kubectl get pods -n blockchain
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "eth.blockNumber"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "eth.blockNumber"
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec "eth.blockNumber"
```

Verify pending transactions and receipts:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getTransactionReceipt("0x5ea06048912ba0cebe91ff428c7058def03cf4e5024c7a5e6b4fd7326f294675")'
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
```

### 3.2.1 Diagnostics: outstanding transactions in CPRs that are not mined

In produccion/Hetzner, `validate-worker-*` validators may be locked during booting at:

```text
INFO: Waiting for application startup.
Inicio update_validator_config_blockchain -> ipfs_config_hash: ...
Transaccion enviada: 0x...
```

And never to show up:

```text
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8070
```

The cause observed was that the transaction sent by the validator to the RPC node was left in the RPC `txpool`, but did not reach the miner.

Check the `txpool` of the PRC:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
```

Problematic exit:

```text
{
  pending: 10,
  queued: 0
}
```

Check the miner's `txpool`:

```bash
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'txpool.status'
```

Problematic exit:

```text
{
  pending: 0,
  queued: 0
}
```

Check the receipt of an outstanding transaction:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getTransactionReceipt("TX_HASH")'
```

Problematic exit:

```text
null
```

This case indicates that:

- the PRC receives transactions;
- the miner does not receive them;
- Therefore, the transaction is not mined;
- validators are locked pending receipt;
- the HTTP port of the validator may not be opened because FastAPI is still in `Waiting for application startup`.

Check number of peers:

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

Although the three nodes are in the same block:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.blockNumber'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'eth.blockNumber'
kubectl exec -it geth-bootnode-0 -n blockchain -- geth attach --exec 'eth.blockNumber'
```

The problem may still exist if RPC and miner are only connected to the bootnode, not to each other.

Confirm real peer without using arrow functions, because the `geth attach` JS console may not support `=>`:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.peers.map(function(p){ return p.name + " " + p.network.remoteAddress })'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.peers.map(function(p){ return p.name + " " + p.network.remoteAddress })'
```

Caso observado:

```text
["Geth/... 10.42.0.56:30303"]
```

If `10.42.0.56` is `geth-bootnode-0`, this incorrect topology is confirmed:

```text
rpc   ---> bootnode
miner ---> bootnode
```

And the direct connection is missing:

```text
rpc <--> miner
```

Temporary manual solution with `admin.addPeer()`:

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

Actual example observed:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("enode://2902482757cd755c3e5fdb6632b23cfd3205140843211aa11fd20c5fe7809e717ff323d1c3e94e9e02eb7818dea8a8309d748937f7719c73d6c11f35d21946cb@10.42.0.54:30305")'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'admin.addPeer("enode://e57a9ffb627bcb8808e77d15b84457cd2b9e61d9354cb13157888e5916fb005d44bc2d87b4eaedbaeed87fb08d28344aadd4a6f2a9a9131d8dae0e0792c769da@10.42.0.55:30304")'
```

Validate that both nodes have two peers:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'net.peerCount'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'net.peerCount'
```

Expected result:

```text
2
2
```

Check that the pending transaction is already mined:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getTransactionReceipt("TX_HASH")'
```

Expected result:

```text
{
  blockNumber: ...,
  status: "0x1",
  ...
}
```

Check the `txpool` again:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'txpool.status'
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec 'txpool.status'
```

Once pending transactions have been mined, restart the validators:

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

Important: `admin.addPeer()` is a manual and non-persistent solution. If blockchain pods are restarted, they may be lost and the procedure will have to be repeated.

### 3.3 Deploy or verify contract

If the stable version contract already exists, keep the current address and check bytecode:

```bash
export CONTRACT_ADDRESS=0x<direccion-trust-news>
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- \
  geth attach --exec "eth.getCode('$CONTRACT_ADDRESS')"
```

If new contract is deployed, open tunnel to the PRC from your work machine:

```bash
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 8565:localhost:8555 \
  <usuario>@<hetzner-ip> \
  -t "kubectl port-forward pod/geth-rpc-endpoint-0 -n blockchain 8555:8555"
```

At another terminal:

```bash
cd smart-contracts
read -rsp "Deployer private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/deployGeth.js --network cloudGeth
unset DEPLOYER_PRIVATE_KEY
```

Save the displayed address as `CONTRACT_ADDRESS`.

Initialize or verify on-chain categories. It is idempotent if the contract owner is used:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network cloudGeth
npx hardhat run scripts/initCategories.js --network cloudGeth
unset DEPLOYER_PRIVATE_KEY
```

The second execution must show the ten categories as `unchanged`. If there is `mismatch`, do not continue: the contract does not correspond to the expected version or the categories do not match `smart-contracts/config/categories.json`.

### 3.4 Update contract address before APIs

The overlays prod contain the address in these files:

```text
k8s/apis/news-chain/overlays/prod/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-1/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-2/kustomization.yaml
k8s/apis/validate-asertions/overlays/prod/worker-3/kustomization.yaml
```

Before deploying `apis-frontend-prod`, change all `CONTRACT_ADDRESS` if new contract has been deployed. Also confirm that `ACCOUNT_ADDRESS` from `news-chain` matches the `news-chain.env` account.

If the ABI contract changes, regenerate the artifact and confirm that it exists:

```bash
cd smart-contracts
npx hardhat compile
test -f artifacts/contracts/TrustNews.sol/TrustNews.json
```

### 3.5 Unfold APIs and frontend

Launch manual pipeline with:

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

## 4. Normal update from GitLab CI

Use this stream to deploy already uploaded commit to `postTFM`.

### 4.1 Preflight local

```bash
git checkout postTFM
git fetch origin main
git merge origin/main
git status --short
```

Check if the change touches contract or contract overlays:

```bash
git diff --name-only origin/main...HEAD | grep -E 'smart-contracts|k8s/apis/.*/overlays/prod/.*/kustomization.yaml|k8s/apis/news-chain/overlays/prod/kustomization.yaml' || true
```

If you touch contract, repeat sections 3.3 and 3.4 before deploying APIs.

Subir a GitLab:

```bash
git push gitlab postTFM
```

### 4.2 Run Pipeline

In GitLab:

1. Abrir `Build > Pipelines > Run pipeline`.
2. Branch: `postTFM`.
3. Variable `PROFILE=apis-frontend-prod`.
4. Run `build` and then `deploy`.

The `build` job generates `build.json` with the exact images. The `deploy` job runs:

```bash
skaffold deploy --build-artifacts=build.json --profile=$PROFILE
```

The pipeline only automatically builds if there are changes to `api/**`, `web_classic/**`, `skaffold.yaml` or `k8s/apis/**`; for changes to docs, infra, blockchain or certificates it may be necessary to run the job manually.

### 4.3 Verification after IQ

```bash
kubectl get pods -n apis -o wide
kubectl get pods -n frontend -o wide
kubectl logs deployment/gateway -n apis --tail=80
kubectl logs deployment/news-handler -n apis --tail=80
kubectl logs deployment/evidence-search -n apis --tail=80
```

Example to test an endpoint directly inside the pod, without installing any additional items:

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

Test frontend by tunnel:

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

## 5. Keycloak and assessed contributions

Acceder a Keycloak:

```text
https://localhost:9443/auth/admin/master/console/
```

Minima configuration:

- Realm: `TrustNews`.
- Cliente frontend: `TrustNewsWeb`.
  - Root URL: Public frontend URL.
  - Valid redirect URIs: `<frontend-url>/*`.
  - Web Origins: frontend URL, or `*` for testing only.
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

Admin/quotas via tunnel:

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

Business cuotas/clientes is created by admin API; they should not be part of the fixed bootstrap.

## 6. Operation and recovery

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

### 6.3 Destructive cleaning of PVCs

Just for full reconstruction.

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

### 6.6 Images base with pull rate limit

Si Docker falla descargando imagenes base conocidas:

```bash
docker pull mirror.gcr.io/library/python:3.11-slim
docker tag mirror.gcr.io/library/python:3.11-slim python:3.11-slim
```

## 7. Checklist rapido

Before `apis-frontend-prod`:

- `postTFM` contains the `origin/main` base.
- `mongodb-app-secret`, `api-keys`, `search-secret`, `news-chain-secrets` y `validator-secret-{1,2,3}` existen en `apis`.
- `mongodb-secret`, `keycloak-admin-secret`, `keycloak-db-secret` y `mongo-express-secret` existen en `infra`.
- `ethereum-secrets` exists in `blockchain`.
- `gitlab-pull-secret` esta asociado al service account de `apis`, `infra`, `frontend` y `blockchain`.
- `frontend-tls` exists or certificates are available for the `k8s/frontend` generator.
- `CONTRACT_ADDRESS` in overlays prod matches the contract deployed.
- `initCategories.js` has been executed and the second execution does not change anything.
- `scripts/k8s/init-mongodb-server.sh` has been executed after lifting MongoDB.
- The GitLab Pipeline uses `PROFILE=apis-frontend-prod` for normal updates.
