# Assermetry Kubernetes - Local deployment

Runbook of the local environment with Kind and non-productive profiles of Skaffold. This document contains the current photograph, repeatable procedures and next steps. Historical evidence is not preserved here.

The shared procedures are in [`k8s-common.md`](k8s-common.md), the status of the current version in [`version.md`](../version.md) and the roadmap in [`next_releases.md`](../next_releases.md).

---

## 1. Current local photo

| Scope | State in force |
| --- | --- |
| Cluster | Kind, name `trust-news` |
| Entrada web | `https://localhost:7443/gui/`, preserving hostname by redirecting or tunneling from host |
| Ingress | Overlay `k8s/ingress/overlays/local` with `host: localhost` |
| TLS | Secret local `trustnews-origin-tls` generado desde `web_classic/certs/*` |
| Identity | Keycloak with `https://localhost:7443/auth/realms/TrustNews` issuer |
| APIs | Documentation available by local Skaffold port-forward |
| Cloudflare | No local intervention |
| mTLS | Cloudflare rules are not played in Kind |
| Production | No `prod` or `prod-domain` overlays are deployed |

Perfiles locales:

| Perfil | Scope |
| --- | --- |
| `traefik` | Traefik local, chart `41.0.2` |
| `blockchain` | Red privada Geth local |
| `infra-basic` | Basic infrastructure without monitoring |
| `infra` | Complete infrastructure with Kafdrop, Fluent Bit, Loki and Grafana |
| `apis-frontend` | APIs, Gateway, frontend e Ingress local |

`infra-basic` and `infra` are alternatives. They must not be run simultaneously:

- use `infra-basic` for light local flow without monitoring;
- use `infra` when logs are needed, persistence of observability,
Grafana or Kafdrop.

`infra-basic` does not exist in production.

### 1.1 Access from VM host

The local environment runs within a VM and the port-forwards that must be opened from the host listen deliberately in `0.0.0.0`. This exception is only local: the VM adapter must be `host-only` or an equivalent private network, and the guest firewall must accept those ports only from the host address. Do not use a bridge interface or a unreliable shared network with those active listeners.

The full tour of Traefik must retain `localhost`: the Ingress and the IODC issuer depend on that hostname. From the host the hypervisor port is redirected to the VM or a tunnel opens, for example:

```bash
ssh -L 7443:127.0.0.1:7443 <usuario-vm>@<ip-privada-vm>
```

Then `https://localhost:7443/gui/` opens in the host. Do not replace hostname with VM IP to validate login or OIDC. The panels and APIs accessed by direct port-forward, without a canonical host rule, can be opened as `http://<ip-privada-vm>:<puerto>`. If no access is needed from the host, link port-forward to `127.0.0.1`.

---

## 2. Deployment flow

Orden:

1. Create or check the Kind cluster.
2. Crear namespaces.
3. Desplegar `blockchain`.
4. Deploy or verify the contract.
5. Choose `infra-basic` or `infra`.
6. Run MongoDB bootstrap.
7. Desplegar `traefik`.
8. Desplegar `apis-frontend`.
9. Configure Keycloak, quotas and functional data.
10. Run the local validation matrix.

---

## 3. Cluster and namespaces

Create the cluster:

```bash
kind create cluster --name trust-news --config kind-config.yaml
```

Crear namespaces:

```bash
cd ./scripts/k8s
./create-namespaces.sh
kubectl get ns blockchain infra apis frontend
```

Recreating the cluster is destructive.

```bash
kubectl get pvc -A
docker volume ls
df -h /
```

When the reconstruction is decided:

```bash
kind delete cluster --name trust-news
kind create cluster --name trust-news --config kind-config.yaml
```

Additional cleaning of Docker images or volumes is executed separately and only after reviewing your targets.

---

## 4. Blockchain and contract

Unlock the local network:

```bash
./skaffold dev -p blockchain --namespace blockchain
```

Check nodes and logs:

```bash
kubectl get pods -n blockchain
kubectl logs -n blockchain -f geth-bootnode-0
kubectl logs -n blockchain -f geth-rpc-endpoint-0
kubectl logs -n blockchain -f geth-miner-0
```

Open the PRC only when necessary:

```bash
kubectl port-forward svc/geth-rpc-endpoint 8555:8555 -n blockchain
```

Deploy a local contract:

```bash
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth
```

Initialize categories:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network privateGeth
npx hardhat run scripts/initCategories.js --network privateGeth
unset DEPLOYER_PRIVATE_KEY
```

The second execution verifies the power and should not create duplicate categories.

---

## 5. Infraestructura local

### 5.1 Basic profile

`infra-basic` includes Kafka, IPFS, MongoDB, Mongo Express and Keycloak. It includes Kafdrop, Fluent Bit, Loki and Grafana.

```bash
./skaffold dev -p infra-basic
```

Mongo Express is available at:

```text
http://localhost:8081
```

### 5.2 Perfil completo

`infra` adds Kafdrop, Fluent Bit, Loki and Grafana:

```bash
./skaffold dev -p infra
```

Services:

```text
Kafdrop:       http://localhost:9000
Grafana:       http://localhost:3000
Mongo Express: http://localhost:8081
```

If Mongo Express port-forward is interrupted:

```bash
kubectl port-forward --address 0.0.0.0 \
  -n infra svc/mongo-express 8081:8081
```

The listener is accessible from the host according to the private network model described in [1.1](#11-acceso-desde-el-host-de-la-vm).

With either of the two profiles, then run the common bootstrap:

- [`k8s-common.md - MongoDB bootstrap`](k8s-common.md#6-mongodb-bootstrap).

---

## 6. Traefik, APIs and frontend

Install or update Traefik exclusively via Skaffold:

```bash
./skaffold deploy -p traefik
```

The profile fixes `41.0.2` chart, uses `k8s/traefik/values.yaml` and applies atomic upgrades. Do not run `helm upgrade` or patch the Deployment manually.

Check the driver:

```bash
kubectl rollout status deployment/traefik -n kube-system
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
kubectl get ingress -A
```

Unfold APIs and frontends:

```bash
./skaffold dev -p apis-frontend
```

Open the full entry:

```bash
kubectl port-forward --address 0.0.0.0 \
  -n kube-system svc/traefik 7443:443
```

The listener is accessible from the host according to the private network model described in [1.1](#11-acceso-desde-el-host-de-la-vm).

Rutas principales:

```text
https://localhost:7443/gui/
https://localhost:7443/backend/docs
https://localhost:7443/auth/admin/master/console/
```

Kind does not play Cloudflare Single Redirects: `/` must be routed and GUI tested directly in `/gui/`. Traefik's middleware removes that prefix before sending the request to the nginx frontend.

Align the local web client idempotently before trying login and logout:

```bash
KEYCLOAK_URL=https://localhost:7443/auth \
FRONTEND_URL=https://localhost:7443/gui \
WEB_ORIGIN=https://localhost:7443 \
./scripts/k8s/infra/reconcile-keycloak-web-prod.sh
```

Este mismo paso crea o verifica el client scope `trustnews-gateway-audience`
y lo asigna por defecto a `TrustNewsWeb` y `TrustNewsApi`, de modo que los
nuevos access tokens incluyan `aud=TrustNewsGateway`. Si ya había una sesión
abierta, cerrar sesión y volver a iniciar para obtener un token nuevo.

The browser can display a notice by the local certificate.

Do not use the frontend's direct port-forward to validate the full application: it only serves the statics and leaves out `/backend` and `/auth`.

---

## 7. Secrets and configuration

Check Secrets without copying its contents to the repository:

```bash
kubectl get secrets -n infra
kubectl get secrets -n apis
```

The shared configuration of Keycloak and quotas is in:

- [`k8s-common.md - Keycloak y cuotas`](k8s-common.md#7-keycloak-y-cuotas).

The functional configuration and operations of MongoDB are in:

- [`k8s-common.md - Evidence Search`](k8s-common.md#8-evidence-search);
- [`k8s-common.md - MongoDB`](k8s-common.md#9-mongodb-consultas-y-limpieza).

The frontend does not finish TLS or proxify `/backend` or `/auth`. Traefik publishes these routes through the Ingress manifests.

---

## 8. Endpoints locales

The table uses `localhost` as a canonical reference. For frontend and Keycloak it is preserved by redirection or tunnel. A direct HTTP port-forward displayed by Skaffold can use the private IP of the VM. Services that Skaffold links only to loopback requires an explicit tunnel or port-forward with the same network criterion of [1.1](#11-acceso-desde-el-host-de-la-vm).

| Service | URL | Perfil |
| --- | --- | --- |
| Frontend | `https://localhost:7443/gui/` | `apis-frontend` |
| Admin API Swagger | `http://localhost:8400/docs` | `apis-frontend` |
| Gateway Swagger | `http://localhost:8500/docs` | `apis-frontend` |
| Evidence Search Swagger | `http://localhost:8074/docs` | `apis-frontend` |
| News Handler Swagger | `http://localhost:8072/docs` | `apis-frontend` |
| News Chain Swagger | `http://localhost:8073/docs` | `apis-frontend` |
| IPFS FastAPI Swagger | `http://localhost:8060/docs` | `apis-frontend` |
| Assertion Generator Swagger | `http://localhost:8071/docs` | `apis-frontend` |
| Validator Worker 1 Swagger | `http://localhost:8070/docs` | `apis-frontend` |
| Validator Worker 2 Swagger | `http://localhost:8069/docs` | `apis-frontend` |
| Validator Worker 3 Swagger | `http://localhost:8068/docs` | `apis-frontend` |
| Mongo Express | `http://localhost:8081` | `infra-basic` or `infra` |
| Grafana | `http://localhost:3000` | `infra` |
| Kafdrop | `http://localhost:9000` | `infra` |
| Keycloak Admin | `https://localhost:7443/auth/admin/master/console/` | `apis-frontend` |

---

## 9. Local Validation Current

Local validates application and manifests without playing out the external controls of Cloudflare.

### 9.1 Render

```bash
kubectl kustomize --load-restrictor=LoadRestrictionsNone \
  k8s/ingress/overlays/local > /tmp/assermetry-ingress-local.yaml

rg -n 'host: localhost|path: /gui|frontend-strip-gui|gateway-strip-backend-prefix' \
  /tmp/assermetry-ingress-local.yaml
```

The render must not contain `prod-domain`, the public issuer or Cloudflare exclusive locks.

Further check the local border after deployment:

```bash
curl --fail --show-error --cacert web_classic/certs/fullchain.pem \
  -o /dev/null https://localhost:7443/gui/
curl --fail --show-error --cacert web_classic/certs/fullchain.pem \
  -o /dev/null https://localhost:7443/gui/css/style.css

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cacert web_classic/certs/fullchain.pem https://localhost:7443/)" = "404"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cacert web_classic/certs/fullchain.pem https://localhost:7443/gui-malicious)" = "404"
```

### 9.2 Functional matrix

Validation should cover:

- login, refresh, logout and expiration;
- exclusive entry by `/gui/` and logout return to `/gui/`;
- navigation and role authorization;
- Polling and quotas;
- Light and Blockchain flows;
- valid and invalid methods;
- authentication absent, expired or manipulated;
- body within 5 MiB and above the limit;
- Gateway and Keycloak console documentation accessible locally;
- absence of relevant errors in Gateway, workers, Traefik and frontend.

Expected results of technical checks:

| Caso | Outcome |
| --- | --- |
| API protegida sin token | `401` or `403` according to layer |
| Method not permitted | `405` |
| Cuerpo superior a 5 MiB | `413` |
| Local documentation | Accesible |
| Rate limiting Cloudflare | No aplica |
| mTLS Cloudflare | No aplica |

When they change Gateway, Traefik or his manifests repeat this matrix before deploying in Hetzner.

---

## 10. Mantenimiento local

Status and consumption:

```bash
kubectl get pods -A
kubectl get pvc -A
docker system df
```

Stop `skaffold dev` processes first to prevent images from being imported again while cleaning is running.

Clear unused images within Kind nodes:

```bash
for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  docker exec "$node" crictl rmi --prune || true
done
```

`crictl rmi --prune` can keep temporary images uploaded by Skaffold because containerd maintains references with `import-<fecha>@sha256:<digest>` names. Always preview those references before deleting them:

```bash
for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo "=== $node ==="
  docker exec "$node" sh -c \
    'ctr --namespace k8s.io images list -q | grep "^import-" || true'
done
```

When there are no active Skaffold deployments, delete the temporary references by their exact name and then request a new CRI pruning:

```bash
for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo "=== Limpiando $node ==="

  docker exec "$node" sh -c '
    ctr --namespace k8s.io images list -q |
      grep "^import-" |
      while read -r ref; do
        ctr --namespace k8s.io images rm "$ref"
      done

    crictl rmi --prune
  '
done
```

Verify that there are no time references left and measure the recovered space:

```bash
for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo "=== $node ==="
  docker exec "$node" sh -c \
    'ctr --namespace k8s.io images list -q | grep -c "^import-" || true'
  docker exec "$node" du -sh /var/lib/containerd
done

df -h /
```

Each counter must be left in `0`. The necessary images are reconstructed or reloaded in the next Skaffold display. This procedure does not remove the cluster or its PVC. Do not manually delete `/var/lib/containerd` or Docker volumes associated with Kind nodes.

The removal of PVC belongs only to a deliberate local reconstruction. Always inspect before:

```bash
kubectl get pvc -n infra
kubectl get pvc -n blockchain
```

---

## 11. Next steps

### v0.0.13

- Create the reproducible set of synthetic data.
- Run the complete regression of GUI and API.
- Add negative tests for `aud`, `azp` or `client_id`, issuer, expiration and
  firma.
- Demonstrate isolation between organizations.
- Repeat three consecutive internal demos with the same initialization and
  limpieza.

### Subsequent versions

- Keep local without Cloudflare, customer certificates or `prod-domain`.
- Use local as an isolated destination for restoration tests when
`v0.0.16` defines the procedure.
- Do not incorporate Cloudflare Tunnel into the local profile.

The detail and output criteria are maintained in [`next_releases.md`](../next_releases.md).
