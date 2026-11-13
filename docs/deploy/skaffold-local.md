# Assermetry Kubernetes - Local deployment

Runbook of the local environment with Kind and non-productive profiles of Skaffold. This document contains the current photograph, repeatable procedures and next steps. Historical evidence is not preserved here.

The shared procedures are in [`k8s-common.md`](k8s-common.md), the status of the current version in [`v0.0.13.md`](../releases/v0.0.13.md) and the roadmap in [`next_releases.md`](../next_releases.md).

## Guía rápida de la VM local

1. En la VM, comprobar `kubectl config current-context` (`kind-trust-news`). Solo si falta el clúster, crearlo con `kind create cluster --name trust-news --config kind-config.yaml`. Aplicar `./skaffold deploy -p setup`.
2. Conservar la CA y los archivos privados existentes. En la primera instalación, preparar S03/S07a como en [infraestructura](#5-infraestructura-local). Ejecutar `./skaffold dev -p infra-basic` **o** `./skaffold dev -p infra`; esperar a Keycloak y MongoDB. Completar MongoDB y los clientes base y de servicio de Keycloak antes de las APIs.
3. Ejecutar `./skaffold deploy -p traefik` y `./skaffold dev -p apis-frontend`. Mantener `BLOCKCHAIN_ENABLED=OFF` para LIGHT. Skaffold aplica los manifiestos S03/S07a con los insumos preparados.
4. Abrir Traefik en loopback de la VM, tunelizar `7443` por SSH desde el host y alinear el cliente web OIDC antes del primer login. Comprobar `https://localhost:7443/gui/` y las rutas autenticadas. La aceptación local del camino declarativo S03 quedó cerrada el 13-11-2026 según confirmación del operador; esta evidencia no acredita Hetzner/K3s.

En un **clúster existente**, revisar contexto, PVC, CA y archivos locales; no recrear kind ni regenerar material criptográfico en un redespliegue normal. Las campañas [E2E](#92-matriz-funcional) son opcionales y no acreditan K3s.

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
| `blockchain` | Manifiestos de la red privada Geth; inicia a cero réplicas |
| `news-chain` | Integración blockchain; se aplica al activar el modo ON |
| `infra-basic` | Basic infrastructure without monitoring |
| `infra` | Complete infrastructure with Kafdrop, Fluent Bit, Loki and Grafana |
| `apis-frontend` | APIs, Gateway, frontend e Ingress local |

`infra-basic` and `infra` are alternatives. They must not be run simultaneously:

- use `infra-basic` for light local flow without monitoring;
- use `infra` when logs are needed, persistence of observability,
Grafana or Kafdrop.

`infra-basic` does not exist in production.

### 1.1 Access from VM host

The local environment runs within a VM. Skaffold's direct API port-forwards can listen on `0.0.0.0`; the VM adapter must be `host-only` or an equivalent private network, and the guest firewall must accept those ports only from the host address. The Traefik port-forward below listens on `127.0.0.1` and is reached through SSH. Do not use a bridge interface or an untrusted shared network with those listeners.

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
3. Preparar la PKI local S03 y el material TLS Kafka S07a antes de Skaffold.
4. Choose `infra-basic` or `infra`.
5. Run MongoDB bootstrap; con Keycloak listo, comprobar el realm y los clientes
   base y reconciliar clientes de servicio S03 si aún no existen los
   `s03-client.env` locales.
6. Desplegar `traefik` y `apis-frontend` en LIGHT.
7. Alinear el cliente web/issuer local y configurar cuotas y datos funcionales.
8. Activar blockchain solo si se va a probar un flujo auditable; desplegar o
   verificar el contrato entonces.
9. Run the local validation matrix.

En redespliegues con CA y credenciales conservadas, los perfiles aplican S03/S07a sin activador posterior.

---

## 3. Cluster and namespaces

Solo si falta el clúster, crearlo:

```bash
kind create cluster --name trust-news --config kind-config.yaml
```

Crear o comprobar namespaces con el perfil idempotente:

```bash
./skaffold deploy -p setup
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

## 4. Blockchain and contract (optional)

LIGHT starts without this profile. A direct Skaffold deployment of the
blockchain profile leaves its StatefulSets at zero replicas.

Tras tener `infra`/`infra-basic` y `apis-frontend` activos, habilita el modo:

```bash
BLOCKCHAIN_ENABLED=ON bash scripts/k8s/set-blockchain-mode.sh
```

El script aplica `blockchain`, escala los tres StatefulSets de Geth, despliega
`news-chain` y reinicia las APIs afectadas cuando la red está lista. Kafka,
los workers LIGHT y `news-handler` siguen activos en ambos modos. Para volver
a LIGHT, bloquea nuevas órdenes auditables, verifica que no queden órdenes
BLOCKCHAIN en curso y escala los pods accesorios a cero:

```bash
BLOCKCHAIN_ENABLED=OFF bash scripts/k8s/set-blockchain-mode.sh
```

No uses `skaffold dev -p blockchain` ni escalados manuales como cambio de
modo: el perfil por diseño conserva Geth en cero réplicas hasta que el script
lo active.

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

Antes de ejecutar `infra-basic` o `infra` en un kind nuevo, preparar la PKI
S03 fuera del repositorio. El script crea los enlaces ignorados que necesitan
los `secretGenerator` locales de Skaffold:

```bash
python3 scripts/security/s03_local_pki.py --output-dir /tmp/s03-kind-pki
python3 scripts/security/s07a_local_kafka_tls.py --pki-dir /tmp/s03-kind-pki
python3 scripts/security/render_s03_runtime.py --check
```

Conservar `/tmp/s03-kind-pki` y los archivos ignorados entre redespliegues. Si faltan, seguir [S03](../security/s03-skaffold.md) y [S07a](../security/s07a-kafka-tls.md) antes de continuar; no regenerar una CA o un PKCS12 por separado.

### 5.1 Basic profile

`infra-basic` includes Kafka, IPFS, MongoDB, Mongo Express and Keycloak; Kafdrop, Fluent Bit, Loki and Grafana belong to `infra`.

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

The listener is accessible from the host according to the private network model described in [1.1](#11-access-from-vm-host).

With either of the two profiles, then run the common bootstrap:

- [`k8s-common.md - MongoDB bootstrap`](k8s-common.md#7-mongodb-bootstrap).

En la primera instalación, esperar a los servicios y completar el bootstrap:

```bash
kubectl rollout status deployment/keycloak -n infra
kubectl rollout status statefulset/mongodb -n infra
scripts/k8s/init-mongodb-server.sh
scripts/k8s/realign-source-routing-mongodb.sh --check
```

Skaffold no crea el realm `TrustNews` ni los clientes base `TrustNewsWeb` y `TrustNewsApi`. Restaurarlos o seguir la [configuración de Keycloak](k8s-common.md#8-keycloak-and-assessed-contributions) antes de reconciliar los clientes S03. Para el reconciliador local, abrir temporalmente en otra terminal de la VM:

```bash
kubectl port-forward --address 127.0.0.1 -n infra svc/keycloak 18080:8080
```

Cerrar ese puerto al terminar la reconciliación.

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

If its local client files do not exist yet, first bring up
Keycloak with `infra-basic` or `infra` and reconcile its service clients. This
writes one ignored `s03-client.env` into each API overlay; Kustomize uses those
files to generate the `s03-client-*` Secrets during the API deployment. Run the
reconciliation from the repository root:

```bash
python3 scripts/security/reconcile_s03_keycloak.py --kind-local --local-overlays
```

Then deploy APIs and frontends:

```bash
./skaffold dev -p apis-frontend
```

Para el arranque LIGHT, después de aplicar las APIs:

```bash
BLOCKCHAIN_ENABLED=OFF bash scripts/k8s/set-blockchain-mode.sh
```

Los perfiles Skaffold ya incluyen sidecars, TLS, Secrets y rutas S03 en sus
manifiestos. Las credenciales locales `s03-client.env` siguen ignoradas por
Git y son reutilizadas en los siguientes despliegues. No se ejecuta un
activador después de Skaffold. Keycloak debe estar listo antes de reconciliar
los clients; la CA y los certificados se conservan en `/tmp/s03-kind-pki`.
El orden completo y el contrato de Secrets están en
[S03 con Skaffold](../security/s03-skaffold.md).

Open the full entry:

```bash
kubectl port-forward --address 127.0.0.1 \
  -n kube-system svc/traefik 7443:443
```

Desde el host, usar el túnel SSH de [1.1](#11-access-from-vm-host). Para otros puertos de diagnóstico, añadir `-L <puerto>:127.0.0.1:<puerto>` solo durante la operación.

Rutas principales:

```text
https://localhost:7443/gui/
https://localhost:7443/backend/docs
https://localhost:7443/auth/admin/master/console/
```

Antes de ejecutar un E2E que publique órdenes, comprobar la ruta OIDC:

```bash
curl -k -sS -o /dev/null -w 'OIDC HTTP %{http_code}\n' \
  https://localhost:7443/auth/realms/TrustNews/.well-known/openid-configuration
```

`Connection refused` en 7443 indica que falta el túnel. Un error local
`[Errno 1] Operation not permitted` indica que el proceso no puede abrir
conexiones desde su sandbox; no demuestra que el secreto del cliente sea
incorrecto. OIDC 200 confirma la ruta, pero no valida las credenciales.

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

- [`k8s-common.md - Keycloak y cuotas`](k8s-common.md#8-keycloak-and-assessed-contributions).

The functional configuration and operations of MongoDB are in:

- [`k8s-common.md - Evidence Search`](k8s-common.md#9-source-router-and-evidence-search);
- [`k8s-common.md - MongoDB`](k8s-common.md#10-mongodb-consultations-and-cleaning).

The frontend does not finish TLS or proxify `/backend` or `/auth`. Traefik publishes these routes through the Ingress manifests.

---

## 8. Endpoints locales

The table uses `localhost` as a canonical reference. For frontend and Keycloak it is preserved by redirection or tunnel. A direct HTTP port-forward displayed by Skaffold can use the private IP of the VM. Services that Skaffold links only to loopback require an explicit tunnel or port-forward with the same network criterion of [1.1](#11-access-from-vm-host).

| Service | URL | Perfil |
| --- | --- | --- |
| Frontend | `https://localhost:7443/gui/` | `apis-frontend` |
| Admin API Swagger | `http://localhost:8400/docs` | `apis-frontend` |
| Gateway Swagger | `http://localhost:8500/docs` | `apis-frontend` |
| Evidence Search Swagger | `http://localhost:8074/docs` | `apis-frontend` |
| News Handler Swagger | `http://localhost:8072/docs` | `apis-frontend` |
| News Chain Swagger | `http://localhost:8073/docs` | `news-chain`, solo con blockchain ON |
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

El Ingress local usa el certificado de `web_classic/certs`. Si se regenera, el
nombre DNS debe coincidir con `localhost`; el generador reutiliza la clave
existente y emite un certificado con SAN. Aplicar después el overlay local para
actualizar `trustnews-origin-tls` en kind:

```bash
bash web_classic/certs/create_certs.sh localhost
openssl verify -CAfile web_classic/certs/fullchain.pem \
  -verify_hostname localhost web_classic/certs/fullchain.pem
kubectl kustomize --load-restrictor=LoadRestrictionsNone \
  k8s/ingress/overlays/local | kubectl apply -f -
```

En el navegador del host, confiar explícitamente en este certificado local
autofirmado antes de usar la GUI; en comandos `curl`, pasar `--cacert` como en
las comprobaciones siguientes. No usar este certificado ni su clave en K3s.

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
- LIGHT flows and, when `BLOCKCHAIN_ENABLED=ON`, blockchain flows;
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

### 9.3 E2E y viewer opcionales

Estas campañas pueden consumir cuotas y proveedores; fijar identidad de prueba y presupuesto antes de ejecutarlas. Con el túnel `7443` activo, el smoke LIGHT usa `ASSERMETRY_USERNAME` y `ASSERMETRY_PASSWORD` cargados solo en la sesión:

```bash
ASSERMETRY_CASE_FILE=tests/data/frontend-e2e/resources/cases/light.json \
  node tests/frontend/e2e/ui-smoke-test.js
```

Para una campaña de evaluación publicada, cargar `ASSERMETRY_KEYCLOAK_CLIENT_ID` y `ASSERMETRY_KEYCLOAK_CLIENT_SECRET` solo en la sesión; el proceso puede llamar proveedores externos. Ejecutar con el túnel `7443` activo:

```bash
PYTHONPATH=tests:api .venv/bin/python -m evaluation.pipeline \
  --dataset tests/data/benchmark/resources/cases/official-gold-v0 \
  --mode full --publish --repetitions 1 \
  --output "tests/data/evaluation/artifacts/e2e-$(date +%Y%m%d-%H%M%S)"
unset ASSERMETRY_KEYCLOAK_CLIENT_SECRET
```

Solo `phase=campaign.complete` acredita el fin de la campaña; revisar `execution_failures` si aparece `COMPLETED_WITH_ERRORS`. La regresión completa se documenta en [E2E frontend](../../tests/frontend/e2e/README.md). No forma parte del arranque rutinario. Para leer los artefactos ya generados, iniciar en la VM:

```bash
PYTHONPATH=tests:api .venv/bin/python -m evaluation.viewer.server \
  --artifacts-root tests/data/evaluation/artifacts --host 127.0.0.1 --port 8765
```

Desde el host se accede con `ssh -L 8765:127.0.0.1:8765 <usuario-vm>@<ip-privada-vm>` y `http://127.0.0.1:8765/`. Al terminar, detener viewer, túneles y procesos `skaffold dev` con `Ctrl+C`; el clúster y sus volúmenes permanecen.

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
