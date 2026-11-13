# Assermetry Kubernetes - server/Hetzner Deployment

Runbook operating the Hetzner environment. This document contains only:

- the current technical photograph;
- repeatable deployment, verification and recovery procedures;
- the next steps that have not yet been implemented.

The status of the current version is in [`v0.0.13.md`](../releases/v0.0.13.md), the roadmap in [`next_releases.md`](../next_releases.md), the evidence of closed versions in [`releases.md`](../releases.md) and the incidences in [`issues.md`](../issues.md). The procedures shared with local are in [`k8s-common.md`](k8s-common.md).

Hetzner/K3s es actualmente **preproducción**. Los nombres `-prod` son identificadores técnicos de perfiles y overlays; no acreditan producción. Esta guía sirve también para otro K3s después de adaptar dominio, issuer, Ingress, certificados y comprobaciones de CI al destino.

## Guía rápida de K3s

1. **Clúster limpio:** comprobar contexto, almacenamiento, registro, DNS y borde; aplicar `./skaffold deploy -p setup` y preparar los Secrets y certificados de [§3](#3-secrets-productivos). Desplegar inicialmente `infra-prod` con el `build.json` del mismo SHA, esperar a Keycloak, restaurar o crear realm/clientes base y completar MongoDB y clientes de servicio S03. Seguir la [secuencia detallada](#62-controlled-installation-or-reconstruction).
2. Lanzar después los pipelines protegidos `traefik-prod`, `infra-prod` y `apis-frontend-prod`, por separado, con `BLOCKCHAIN_ENABLED=OFF`. La CI despliega con Skaffold y reconcilia el cliente web de Keycloak; no repetir ese ajuste tras un job correcto.
3. **Clúster existente:** conservar estado, CA y Secrets; revisar contexto, backups, PVC, SHA/digests y modo. Para cambios solo de aplicación, lanzar `apis-frontend-prod`; para cambios de infraestructura, `infra-prod` y luego APIs. Rotar credenciales y certificados con el procedimiento S03/S07a cuando corresponda.
4. Comprobar pods Ready, configuración efectiva, TLS, JWKS y rutas autorizadas/denegadas desde el borde. La aceptación kind no acredita Hetzner ni abre por sí sola las demos externas.

Do not record here chronologies of tests, attempts of pipeline, identifiers, IP addresses, fingerprints, tokens, certificates or personal data.

---

## 1. Current photo

### 1.1 Platform and profiles

| Scope | State in force |
| --- | --- |
| Plataforma | K3s in a single Hetzner node |
| Dominio | `https://assermetry.com`, Proxified by Cloudflare |
| Ingress | Trafik over `websecure` |
| Origin TLS | Cloudflare Origin CA in `kube-system/trustnews-origin-tls` |
| Identity | Keycloak, realm `TrustNews` and display name `Assermetry` |
| Issuer | `https://assermetry.com/auth/realms/TrustNews` |
| Perfiles | `setup`, `traefik-prod`, `infra-prod`, `blockchain-prod`, `news-chain-prod` and `apis-frontend-prod` |
| Overlays productivos | Keycloak, Gateway e Ingress usan `prod-domain` |
| Entry to origin | `TCP/443` only from the verified Cloudflare networks |
| Puertos cerrados | `80/tcp`, `6443/tcp` and the rest of public application ports |

Public contract after completing the `/gui` cutover:

```text
https://assermetry.com/          -> 302 de Cloudflare a /gui/
https://assermetry.com/gui       -> 302 de Cloudflare a /gui/
https://assermetry.com/gui/      -> frontend
https://assermetry.com/backend   -> Gateway
https://assermetry.com/auth      -> Keycloak
```

Internal services, databases, Kafka, IPFS, RPC, panels and administrative APIs remain as `ClusterIP`, without Ingress or NodePort.

### 1.2 Cloudflare

The five custom rules are occupied and retain this order:

| Orden | Regla | Operational status |
| ---: | --- | --- |
| 1 | `Maintenance lock - assermetry.com` | Selective; check it before each window |
| 2 | `Permanent mTLS - administration` | Active and permanent |
| 3 | `Temporary mTLS gate - assermetry.com` | Activate to `v0.0.14` |
| 4 | `Permanent block - non-public resources` | Activa |
| 5 | `Permanent block - unexpected backend methods` | Activa |

The lock exists and, as long as there are no redirects in an earlier phase, it can block the entire hostname. Its status is not assumed: the operator deliberately enables or disables it according to the working window. Its current observed state is disabled. Before changing it, the desired state is confirmed and, at the end, is left registered in the operational evidence, not in this runbook.

The Free Managed Rulet is enabled. The only rule of rate limiting, `Expensive backend operations per IP`, protects the costly operations of the Gateway with the operating threshold of 5 requests for 10 seconds and 10 seconds mitigation. Login, refresh and Polling are not part of that rule.

The hostname mTLS association is preserved. The permanent rule of administration must require valid customer certificate for these paths (without exceptions by method):

```text
/auth/admin
/auth/admin/*
/auth/realms/master
/auth/realms/master/*
/backend/admin/llm
/backend/admin/llm/*
```

The last two are the LLM configuration console. This inclusion is permanent: it does not depend on the time rule, a feature flag or the local environment. Administrative LLM configuration endpoints requires client-certificate authentication.

As long as the time rule is active:

- an administrative route without a certificate is consistent with the permanent rule;
- a non-administrative route without a certificate matches the time rule;
- a valid certificate allows for continuation until subsequent checks;
- a revoked certificate must be rejected.

In `v0.0.14`, only the time rule will be removed. MTLS is not removed from the hostname and the administrative rule, including `/backend/admin/llm` and `/backend/admin/llm/*`, is not removed.

In that same window the time rule is replaced by a permanent `default deny` rule of paths. `/` and `/gui` single redirects do not consume Custom Rules slots. If the maintenance lock is retained, the final composition still occupies five rules: lock, administrative mTLS, non-public resources, Gateway methods and `default deny`. If the lock is removed by a separate operational decision, four remain; the previous three permanent rules alone do not block routes such as `/wp-admin/` in Cloudflare.

### 1.3 Traefik, observability and baseline

Traefik is installed using the `traefik-prod` profile, fixes the `41.0.2` chart and uses:

- `externalTrafficPolicy: Local`;
- `forwardedHeaders.insecure: false`;
- `kubernetesIngress.strictPrefixMatching: true`;
- Cloudflare official networks in `websecure.forwardedHeaders.trustedIPs`;
- JSON log accesses without headers or query parameters;
- Helm upgrades with `--atomic`.

Loki and Grafana use persistent PVC, test and store data and datasource after reacting their pods. Fluent Bit includes `kube-system` to collect Traefik logs.

The historical v0.0.12 operational baseline is summarized in [`v0.0.12.md`](../releases/v0.0.12.md): 29 pods prepared, zero resets, nine PVC `Bound` and `Ready` node. It is the stable baseline for Phase 7 closure. 76% memory, `DNSConfigForming` and Loki's transient planning failure during the rollout are still under observation; they should not become permanent figures within this runbook.

---

## 2. Accesses and variables

The server must have:

- K3s and `kubectl` functional;
- Skaffold;
- SSH access by `2222/tcp` with key for deployment user;
- GitLab Runner with tag `hetzner-runner`;
- Docker for the build job;
- pull secret del GitLab Registry en los namespaces necesarios.

CI/CD variables protected and masked:

```dotenv
HETZNER_IP=<ip-publica-hetzner>
HETZNER_USER=<usuario-ssh>
HETZNER_SSH_KEY_B64=<private-key-ssh-en-base64>
KUBECONFIG_DATA=<kubeconfig-en-base64>
PROFILE=apis-frontend-prod
```

`CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER` and `CI_REGISTRY_PASSWORD` are provided by GitLab.

The `postTFM` branch must be protected when the deployment variables are `Protected`. The scope of the variables must match the environment of the job.

The deployment job opens a local `127.0.0.1:6443 -> Hetzner:127.0.0.1:6443` tunnel and forces the Kubeconfig endpoint to `https://127.0.0.1:6443`. This tunnel is for the K3s API and does not change the application's public issuer.

Para operación interactiva desde un equipo externo, verificar la clave pública del host SSH por un canal independiente y usar `known_hosts` estricto. En el Hetzner actual el puerto SSH es `2222`; en otro K3s usar el configurado allí. Los ejemplos usan variables de la sesión (sin registrar sus valores):

```bash
export K3S_HOST=<host-o-ip>
export K3S_USER=<usuario>
export K3S_KEY=<ruta-clave-ssh>
export K3S_SSH_PORT=2222
ssh -i "$K3S_KEY" -p "$K3S_SSH_PORT" "$K3S_USER@$K3S_HOST" 'kubectl get nodes; kubectl get pods -A'
```

Con kubeconfig local preparado para el certificado del servidor, mantener abierto el túnel de la API y usar `https://127.0.0.1:6443` como endpoint del contexto. No publicar `6443/tcp`:

```bash
ssh -N -i "$K3S_KEY" -p "$K3S_SSH_PORT" -L 6443:127.0.0.1:6443 "$K3S_USER@$K3S_HOST"
```

---

## 3. Secrets productivos

`.env` files and cryptographic material are kept outside the repository.

### 3.1 Helpers idempotentes

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

apply_tls_secret() {
  local namespace="$1"
  local name="$2"
  local file="$3"

  set -a
  . "$file"
  set +a

  test -r "$TLS_CERT_FILE"
  test -r "$TLS_KEY_FILE"

  kubectl create secret tls "$name" \
    --cert="$TLS_CERT_FILE" \
    --key="$TLS_KEY_FILE" \
    -n "$namespace" \
    --dry-run=client -o yaml | kubectl apply -f -
}
```

No borrar primero un Secret para actualizarlo.

### 3.2 Inventario obligatorio

| Namespace | Secret | Fichero privado |
| --- | --- | --- |
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
| `kube-system` | `trustnews-origin-tls` | `tls-origin.env` |

Implementation:

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
apply_tls_secret kube-system trustnews-origin-tls \
  "$HOME/trustnews-origin-ca/tls-origin.env"
```

`MONGO_APP_USER` and `MONGO_APP_PWD` must match the user created by MongoDB's bootstrap. After lifting MongoDB the [`k8s-common.md`](k8s-common.md#7-mongodb-bootstrap)'s idepotent procedure is executed.

### 3.3 Identidad TLS y credenciales S03

Los perfiles `infra-prod` y `apis-frontend-prod` incluyen S03 en sus
manifiestos. **Antes del siguiente despliegue de esos perfiles**, provisionar
manualmente la CA interna y los Secrets `s03-tls-*` del entorno, con los
certificados SAN indicados en [S03 con Skaffold](../security/s03-skaffold.md).
`infra-prod` requiere `s03-tls-keycloak`; `apis-frontend-prod` requiere
`s03-internal-ca` en `apis`, los certificados de las nueve APIs y los clients
de servicio. La CI ejecuta el preflight S03 de la fase correspondiente antes
del deploy. No usar certificados ni `.env` de kind en Hetzner.

Al preparar la activación S03 en preproducción o producción, reconciliar a mano
el realm `TrustNews` contra el Keycloak del entorno. El reconciliador conserva
las identidades ya existentes y escribe un `.env` por client en un directorio
privado fuera del repositorio; nunca muestra los valores. El endpoint debe ser
un port-forward al Keycloak del entorno y las credenciales administrativas se
introducen por el entorno de la sesión, no como argumentos del proceso:

```bash
umask 077
mkdir -p "$HOME/trust-news-secrets/s03-clients"
(
  read -r -p 'Keycloak admin user: ' KC_ADMIN_USER
  read -r -s -p 'Keycloak admin password: ' KC_ADMIN_PASSWORD
  printf '\n'
  export KC_ADMIN_USER KC_ADMIN_PASSWORD
  export KC_ADMIN_URL='http://127.0.0.1:18080/auth'
  python3 scripts/security/reconcile_s03_keycloak.py \
    --output-dir "$HOME/trust-news-secrets/s03-clients"
)
```

Con el port-forward activo, crear/actualizar un Secret por client a partir de
los ficheros generados. Esta operación no imprime el contenido de los Secrets:

```bash
set -o pipefail
while IFS=$'\t' read -r namespace client secret; do
  kubectl create secret generic "$secret" \
    --namespace "$namespace" \
    --from-env-file="$HOME/trust-news-secrets/s03-clients/${client}.env" \
    --dry-run=client -o yaml | kubectl apply -f -
done < <(python3 - <<'PY'
import json
with open('docs/security/s03-local-services.json', encoding='utf-8') as source:
    services = json.load(source)
clients = {}
for service in services:
    client = service.get('client')
    namespace = service.get('namespace')
    if client and namespace:
        secret = service.get('secret_name', f's03-client-{client}')
        clients[(namespace, client, secret)] = True
for namespace, client, secret in sorted(clients):
    print(f'{namespace}\t{client}\t{secret}')
PY
)

bash scripts/security/check_s03_configured_secrets.sh
```

El preflight comprueba, a partir del inventario de servicios, que cada Secret
está presente, que `S03_CLIENT_ID` coincide y que `S03_CLIENT_SECRET` no está
vacío ni contiene un placeholder. También comprueba las dos CA, las claves
TLS, vigencia, SAN, correspondencia clave/certificado y cadena de cada
servicio. Los overlays ya consumen esos Secrets y habilitan S03. El preflight
no sustituye la prueba de autenticación remota; completarla según el runbook
S03. Mantener los `.env` privados hasta
completar esa operación y retirarlos después de acuerdo con el procedimiento
operativo del host.

### 3.4 Pull secret

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

## 4. Domain, Traefik and TLS

### 4.1 Declarative configuration in force

`infra-prod` usa `k8s/infra/keycloak/overlays/prod-domain`.
`apis-frontend-prod` usa:

- `k8s/apis/gateway/overlays/prod-domain`;
- `k8s/ingress/overlays/prod-domain`.

All three Ingress use `host: assermetry.com` and `websecure`. The frontend serves HTTP within the cluster; Traefik finishes TLS and routes `/gui`, `/backend` and `/auth`. A `StripPrefix` middleware eliminates `/gui` before delivering the request to the frontend nginx. There is no Ingress catch-all for `/`.

Do not deploy overlays `local` or `prod` with `localhost` issuer over Hetzner.

### 4.2 Origin CA

The private file `tls-origin.env` reference material, does not contain PEM:

```dotenv
TLS_CERT_FILE=/home/sysadmin/trustnews-origin-ca/assermetry-origin.pem
TLS_KEY_FILE=/home/sysadmin/trustnews-origin-ca/assermetry-origin.key
TLS_CA_FILE=/home/sysadmin/trustnews-origin-ca/cloudflare-origin-ca-rsa-root.pem
```

Before applying:

```bash
test -r "$TLS_CERT_FILE"
test -r "$TLS_KEY_FILE"
test -r "$TLS_CA_FILE"

openssl verify -CAfile "$TLS_CA_FILE" "$TLS_CERT_FILE"
openssl x509 -checkend 2592000 -noout -in "$TLS_CERT_FILE"
openssl x509 -in "$TLS_CERT_FILE" -noout -ext subjectAltName |
  grep -q 'DNS:assermetry.com'
```

Comprobar que certificado y clave forman pareja, aplicar el Secret y validar el
consumidor:

```bash
openssl x509 -in "$TLS_CERT_FILE" -pubkey -noout |
  openssl pkey -pubin -outform PEM |
  sha256sum

openssl pkey -in "$TLS_KEY_FILE" -pubout -outform PEM |
  sha256sum

apply_tls_secret kube-system trustnews-origin-tls \
  "$HOME/trustnews-origin-ca/tls-origin.env"

kubectl get tlsstore default -n kube-system \
  -o jsonpath='{.spec.defaultCertificate.secretName}{"\n"}'
```

The two prints must match and `TLSStore/default` must return `trustnews-origin-tls`. Keep the previously validated material for rollback. Cloudflare revocation is only done after the service is recovered or if there is loss or compromise of the key.

### 4.3 Tunnel diagnosis

The tunnel is a diagnostic tool. It does not restore the old `localhost` issuer.

```bash
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 9443:127.0.0.1:9443 \
  <usuario>@<hetzner-ip> \
  -t "kubectl port-forward --address 127.0.0.1 \
      -n kube-system svc/traefik 9443:443"
```

Validate SNI, hostname and chain:

```bash
openssl s_client \
  -connect 127.0.0.1:9443 \
  -servername assermetry.com \
  -verify_hostname assermetry.com \
  -CAfile origin_ca_rsa_root.pem \
  -verify_return_error </dev/null
```

For HTTP requests, the canonical hostname is preserved:

```bash
curl --resolve assermetry.com:9443:127.0.0.1 \
  --cacert origin_ca_rsa_root.pem \
  https://assermetry.com:9443/gui/
```

The discovery should continue to publish:

```text
https://assermetry.com/auth/realms/TrustNews
```

Para diagnosticar un servicio interno sin publicarlo, abrir un túnel temporal desde el equipo del operador. Sustituir namespace, servicio y puertos según el caso; el HTTP directo omite Traefik y Cloudflare:

```bash
ssh -i "$K3S_KEY" -p "$K3S_SSH_PORT" \
  -L <puerto-local>:127.0.0.1:<puerto-remoto> \
  "$K3S_USER@$K3S_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 -n <namespace> svc/<servicio> <puerto-remoto>:<puerto-servicio>'
```

Ejemplos de puertos internos: Admin API `apis/admin-service:8400`, Gateway `apis/gateway:8500`, Evidence Search `apis/evidence-search:8074`, Source Router `apis/source-router:8075`, Grafana `infra/grafana:3000` y Mongo Express `infra/mongo-express:8081`. Al cerrar, detener el `port-forward` y comprobar que no quedan túneles activos. Para validar OIDC o TLS de extremo a extremo, usar el dominio y la CA del origen o el borde real.

---

## 5. Cloudflare and firewall

### 5.1 Pre-check

Before an operating window:

1. Confirm the deliberate status of the lock.
2. Confirm that the five rules retain the documented order.
3. Confirm that the administrative and temporary mTLS rule are active.
4. Confirm that the Free Managed Rulet and the limit rate are active.
5. Check Security Events without copying IP, Ray ID, Rule ID or sensitive data.
6. Confirm in Hetzner that `443/tcp` only supports Cloudflare and that `80/tcp` and
   `6443/tcp` siguen cerrados.

There are no custom rule-free slots in the current plan.

### 5.2 Expected behaviour of the lock

Before creating the Single Redirects, with the lock enabled all `assermetry.com` is locked even for a valid user or administrator. After creating them, `/` and `/gui` respond with the `302` before reaching WAF; the `/gui/` destination and the rest of the hostname do remain locked. If a window requires an absolute `403` for the entire host, also disable those two redirects while the lock is enabled.

With the lock disabled:

- `/` and non-administrative routes require temporary certification;
- administrative routes are attributed to the mTLS rule on a permanent basis;
- non-public resources and unexpected methods remain blocked;
- Gateway requires JWT on protected routes.

The change in status of the lock does not alter DNS, TLS, mTLS, firewall, Keycloak or Kubernetes.

### 5.3 Reglas permanentes

The administrative rule covers:

```text
/auth/admin
/auth/admin/*
/auth/realms/master
/auth/realms/master/*
```

The non-public resource rule blocks, at a minimum, OpenAPI, Swagger, Redoc and `.git` routes from the public hostname.

The Gateway method rule allows only `GET`, `HEAD`, `POST` and `OPTIONS` under `/backend`.

The body limit is 5 MiB both in Traefik and Gateway.

### 5.4 Redirects and public border after withdrawal of the general mTLS

Create two Single Redirects, initially with `302` and preserving the query:

```text
(http.host eq "assermetry.com" and http.request.uri.path eq "/")
  -> https://assermetry.com/gui/

(http.host eq "assermetry.com" and http.request.uri.path eq "/gui")
  -> https://assermetry.com/gui/
```

Do not use a hostname wildcard: unknown routes must continue to the WAF rule that blocks them, not become `/gui/`.

After checking `/gui/`, add as last Custom Rule:

```text
(http.host eq "assermetry.com" and
 not (
   starts_with(http.request.uri.path, "/gui/") or
   http.request.uri.path eq "/backend" or
   starts_with(http.request.uri.path, "/backend/") or
   http.request.uri.path eq "/auth" or
   starts_with(http.request.uri.path, "/auth/")
 ))
```

Action: `Block`. Comparison remains capital sensitive. Keep URL Normalization, Free Managed Rulet and the limit rate rule on. Exact redirects are evaluated before WAF and are final; therefore `/` and `/gui` are not excluded in `default deny`. If a redirect is disabled by mistake, the path is blocked instead of reaching the source. This allowslist reduces the public surface, but does not replace WAF over valid payloads within `/backend`, `/auth` or `/gui`.

---

## 6. Deployment

### 6.1 Perfiles productivos

| Perfil | Scope |
| --- | --- |
| `setup` | Namespaces |
| `traefik-prod` | Traefik productivo |
| `infra-prod` | MongoDB, Kafka, IPFS, Keycloak and observability |
| `blockchain-prod` | Recursos de Geth (cero réplicas hasta `BLOCKCHAIN_ENABLED=ON`) |
| `news-chain-prod` | Integración blockchain, desplegada por el script de modo ON |
| `apis-frontend-prod` | APIs, Gateway, Frontend and Domain Log-ins |

`infra-basic` es solo para kind; el K3s actual de preproducción usa `infra-prod`.

### 6.2 Controlled installation or reconstruction

En un K3s limpio, la CI actual no completa por sí sola el primer arranque:
`traefik-prod` comprueba el ConfigMap de Keycloak antes de `infra-prod`, y el
job `infra-prod` reconcilia el cliente web antes de que Skaffold haya creado
el realm y los clientes base. La preparación inicial es **manual**, una sola
vez; los despliegues posteriores siguen el pipeline protegido.

1. Confirmar contexto K3s, PVC/almacenamiento, acceso al registro, DNS,
   certificado de origen y reglas del borde. Ejecutar `./skaffold deploy -p
   setup`. Preparar pull secrets, Secrets habituales, CA/TLS S03 y Kafka S07a
   según [§3](#3-secrets-productivos) y [S07a](../security/s07a-kafka-tls.md).
   Los overlays de K3s consumen Secrets existentes; Skaffold no los genera.
   Antes del despliegue inicial de infraestructura, ejecutar
   `S03_PREFLIGHT_PHASE=infra bash scripts/security/check_s03_configured_secrets.sh`.
2. Construir en la CI el perfil `infra-prod` para el SHA elegido y descargar
   su artefacto `build.json` (caduca al día). En un checkout del **mismo SHA**
   con acceso K3s preparado, ejecutar una sola vez:

   ```bash
   kubectl config current-context
   ./skaffold deploy --build-artifacts=build.json -p infra-prod
   kubectl rollout status statefulset/keycloak-db -n infra
   kubectl rollout status deployment/keycloak -n infra
   kubectl rollout status statefulset/mongodb -n infra
   ```

   Este comando aplica el mismo perfil y las imágenes publicadas por CI; no
   ejecuta el postdespliegue del job `infra-prod`. No usar `skaffold run` con
   imágenes locales para un K3s remoto.
3. Restaurar el estado previsto de Keycloak o configurar el realm `TrustNews`
   y sus clientes base `TrustNewsWeb`/`TrustNewsApi` según
   [Keycloak común](k8s-common.md#8-keycloak-and-assessed-contributions).
   Skaffold no crea ese estado. Ejecutar el [bootstrap MongoDB](k8s-common.md#7-mongodb-bootstrap)
   y la [reconciliación web](#65-keycloak-idepotent-alignment) una vez.
4. Reconciliar clientes de servicio S03, crear sus Secrets desde los `.env`
   privados y pasar `scripts/security/check_s03_configured_secrets.sh` como
   indica [§3.3](#33-identidad-tls-y-credenciales-s03). Cerrar los accesos
   temporales usados para Keycloak.
5. Lanzar y esperar los pipelines protegidos `traefik-prod`, `infra-prod` y
   `apis-frontend-prod` en ese orden, con `BLOCKCHAIN_ENABLED=OFF`. La CI
   ejecuta preflight, despliegue Skaffold y reconciliación web. La CI mantiene
   Geth y `news-chain` a cero réplicas y conserva Kafka.
6. Para habilitar blockchain, ejecutar el pipeline con
   `PROFILE=apis-frontend-prod` y `BLOCKCHAIN_ENABLED=ON`. La CI aplica
   `blockchain-prod`, inicia Geth y `news-chain`, y después habilita las APIs.
7. Si se habilitó blockchain, comprobar contrato y categorías; ejecutar la
   verificación completa del modo elegido.

En un **K3s existente**, no repetir los pasos de provisión si CA, certificados,
realm, clientes y Secrets siguen válidos. Revisar respaldo, PVC, contexto,
SHA/digests y modo antes de la [actualización normal](#64-normal-update).
Si el entorno aún usa Kafka PLAINTEXT, el cambio a TLS exige una ventana
coordinada y rollback preparado; no tratarlo como un redespliegue rutinario.

Pipelines manuales:

```dotenv
PROFILE=traefik-prod
PROFILE=infra-prod
PROFILE=blockchain-prod
PROFILE=news-chain-prod
PROFILE=apis-frontend-prod
```

Do not combine profiles in a single window if a failure is being diagnosed.

### 6.3 Contract

If the current contract is retained, verify that bytecode exists:

```bash
export CONTRACT_ADDRESS=0x<direccion-trust-news>
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- \
  geth attach --exec "eth.getCode('$CONTRACT_ADDRESS')"
```

If you change the contract, upgrade `CONTRACT_ADDRESS` on all consumer productive overlays before deploying APIs and regenerating the ABI when applicable.

### 6.4 Normal update

```bash
git checkout postTFM
git fetch origin main
git merge origin/main
git status --short
git push gitlab postTFM
```

In GitLab, the pipeline is run over `postTFM` with the profile corresponding to the changed component. For a normal application update:

```dotenv
PROFILE=apis-frontend-prod
BLOCKCHAIN_ENABLED=OFF
```

`BLOCKCHAIN_ENABLED=OFF` es el valor normal. Con `ON`, la fase posterior al
despliegue usa `set-blockchain-mode.sh`: espera Geth, despliega
`news-chain-prod` con las imágenes de `build.json` y reinicia las APIs. Con
`OFF`, bloquea nuevas órdenes auditables, exige que no haya órdenes BLOCKCHAIN
pendientes y deja Geth y `news-chain` a cero réplicas. Kafka no se detiene.

The initial migration to `/gui` also modifies Trafik. With the lock enabled, run `PROFILE=traefik-prod` first and then `PROFILE=apis-frontend-prod`. Later deployments that do not change Traefik return to only the application profile.

The display uses:

```bash
skaffold deploy --build-artifacts=build.json --profile="$PROFILE"
```

Do not use `kubectl apply`, `helm upgrade` or hand patches as a substitute for the pipeline except in an explicit recovery procedure.

### 6.5 Keycloak idepotent alignment

Reconciliation is a requirement of deployment in Hetzner, not an optional manual step. GitLab YAML automatically executes it after `infra-prod` and `apis-frontend-prod` rollout. Shared script:

- updates and verifies `frontendUrl` of the `TrustNews` realm;
- verifies `TrustNewsWeb` URLs, redirects, post-logout and Web Origins;
- create or recreate the client scope `trustnews-gateway-audience`;
- configura el mapper de audiencia `TrustNewsGateway` en el access token;
- assigns that default scope to `TrustNewsWeb` and `TrustNewsApi`;
- Check that the customers and the mapper were applied.

`TrustNewsApi` remains the backend client; `TrustNewsGateway` is the protected resource audience. The script does not create users or roles and does not print credentials.

Do not run a second manual step after a correct pipeline. If the job fails or a modified configuration needs to be recovered outside the pipeline, run from the root of the repository, with `kubectl` and `python3` available:

```bash
./scripts/k8s/infra/reconcile-keycloak-web-prod.sh
```

The script ends with `keycloak_web_alignment=PASS` only after validating the read state of Keycloak. If `TrustNewsWeb` does not exist exactly once, it fails before modifying the realm or client. Repeating it retains the same result. The expected productive contract is Root URL `https://assermetry.com/gui`, Home URL `https://assermetry.com/gui/`, redirects and post-logout `https://assermetry.com/gui/*`, and Web Origin `https://assermetry.com`.

Después de una reconciliación correcta, los usuarios deben cerrar sesión y
volver a autenticarse para obtener un access token nuevo con
`aud=["TrustNewsGateway"]`. Un login correcto con un token antiguo no acredita
la configuración de audiencia.

---

## 7. Current verification

### 7.1 Kubernetes

```bash
kubectl get pods -A
kubectl get pvc -A
kubectl get ingress -A
kubectl get svc -A
kubectl rollout status deployment/traefik -n kube-system
kubectl get secret trustnews-origin-tls -n kube-system
kubectl get tlsstore default -n kube-system
```

Inner services should not appear with Ingress, NodePort or LoadBalancer. The only web edge is Traefik.

La aceptación S03/S07a exige además comprobar los Secrets por nombre y claves sin mostrar valores, pods Ready, JWKS por HTTPS con CA y hostname verificados, Traefik→Gateway por HTTPS y resultados esperados de rutas autenticadas y denegadas. Seguir la [matriz S03](../security/s03-skaffold.md#comprobaciones-y-rotación) y registrar evidencia separada de kind y K3s. Una configuración declarada o un rollout correcto no sustituyen estas pruebas.

### 7.2 Dominio

Before testing the lock status is checked. If enabled, the general `403` is the expected result.

With the lock disabled and a valid temporary certificate:

- `/gui/`, its assets and discovery respond;
- the issuer is exactly the canonical;
- login, refresh and logout work;
- Gateway rejects without JWT and accepts a valid JWT;
- LIGHT completes its flow; validate blockchain only when `BLOCKCHAIN_ENABLED=ON`;
- `/backend/docs`, Swagger, Redoc and OpenAPI return `404` or are blocked in
the edge;
- Administrative routes require Keycloak certificate and authentication.

In the temporary certificate withdrawal window, the following is added:

- `/` and `/gui` return `302` to `/gui/` from Cloudflare;
- `/wp-admin/`, `/.env`, `/phpmyadmin/` and a random path return `403`;
- `/gui-malicious`, `/backend-malicious` and `/auth-malicious` return `403`;
- `/gui/`, `/backend/*` and `/auth/*` continue to reach their own controls;
- login, refresh, logout and LIGHT run without certificate of user; validate
  blockchain in a deployment with `BLOCKCHAIN_ENABLED=ON`;
- administrative routes continue to reject customers without a certificate.

From an external network it must also be verified that the direct IP of the source and the ports `80` and `6443` do not allow access.

### 7.3 Observabilidad

```bash
kubectl get pvc loki-data grafana-data -n infra
kubectl get pods -n infra
kubectl top nodes
kubectl top pods -A
```

The persistence of Loki can be verified without printing raw logs:

```bash
tests/operations/verify-loki-persistence.sh --execute
```

For Grafana, a port-forward carried by SSH is used; the Service is not published. Check errors and rejections in Loki/Grafana without exporting tokens, headers, bodies, IPs or Cloudflare identifiers.

### 7.4 Viewer de evaluación

Preferir ejecutar el viewer de solo lectura en el checkout local con artefactos descargados, ligado a loopback:

```bash
PYTHONPATH=tests:api .venv/bin/python -m evaluation.viewer.server \
  --artifacts-root tests/data/evaluation/artifacts --host 127.0.0.1 --port 8765
```

Si los artefactos solo están en el servidor K3s, ejecutar allí el mismo comando y abrir desde el equipo del operador un túnel `ssh -N -i "$K3S_KEY" -p "$K3S_SSH_PORT" -L 18765:127.0.0.1:8765 "$K3S_USER@$K3S_HOST"`; acceder a `http://127.0.0.1:18765/`. Detener el viewer y el túnel al terminar. Los E2E contra K3s pueden consumir cuotas y proveedores; seguir [el contrato de pruebas](../../tests/frontend/e2e/README.md) en una ventana autorizada.

---

## 8. Operation and recovery

Rollback Application:

```bash
kubectl rollout undo deployment/gateway -n apis
kubectl rollout undo deployment/news-handler -n apis
kubectl rollout undo deployment/evidence-search -n apis
kubectl rollout undo deployment/frontend-web -n frontend
kubectl rollout status deployment/gateway -n apis --timeout=180s
```

Para un rollback TLS se reaplica el Secret con el material anterior validado y
se repiten las comprobaciones de `TLSStore`, cadena, SNI y hostname.

The removal of PVC belongs only to a complete reconstruction, explicitly authorized and with the processing of data decided. It is not used as routine repair:

```bash
kubectl get pvc -n infra
kubectl get pvc -n blockchain
```

Active PVC destructive restorations are prohibited. La copia protegida y la restauración aislada de MongoDB/Keycloak se adelantan a **v0.0.13b**, antes de migrar datos y abrir beta, según [version.md](../version.md). La cobertura productiva ampliada y la verificación continuada permanecen en `v0.0.16`; esta reasignación no acredita que las pruebas ya estén ejecutadas.

---

## 9. Next steps

### 9.1 Closing of v0.0.12

- Run `infra-prod`, get `keycloak_web_alignment=PASS` on the
reconciliation of `TrustNewsWeb` and revalidate the IODC issuer.
- Confirm the coexistence of the lock, the temporary mTLS and the mTLS
  administrativo.
- Validate from another network with temporary certificate frontend, OIDC and
  LIGHT; include blockchain only with `BLOCKCHAIN_ENABLED=ON`.
- Check Gateway with and without JWT.
- Verify the attribution and access of administrative routes.
- Prove that the lock blocks the entire hostname and leaves it in the operating state
  decidido.
- Register the stable baseline.

### 9.2 v0.0.13

- Run the reproducible regression of GUI and API with synthetic data.
- Keep the mTLS rule on general temporary throughout the version.
- Validate `aud` and `azp` or `client_id` before admitting external evaluators.
- Solve `ISSUE-001` and pass your non-refresher competition tests
LIGHT validator cache manual.
- Run demos from lock controlled windows.

### 9.3 v0.0.14

- Enable the lock during the change window.
- Unfold and validate `/gui` before modifying the Cloudflare border.
- Create the exact `/` and `/gui` redirects to `/gui/` with `302`.
- Replace `Temporary mTLS gate - assermetry.com` with `default deny`
paths; do not open a window without the lock.
- Maintain the mTLS association and the permanent administrative rule.
- Revocation of a disposable administrative certificate and proof of rejection without
affect the administrative endorsement certificate.
- Validate uncertified user OIDC, administration with certificate,
WAF, rate limit, logs and rollback.
- Open beta only after you pass those checks.

Subsequent steps are maintained exclusively in [`next_releases.md`](../next_releases.md) until your version becomes ongoing.
