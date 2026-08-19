# Assermetry Kubernetes - Despliegue server/Hetzner

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
- Skaffold disponible para aplicar los perfiles productivos.
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

### 2.1 Helpers idempotentes

Usar `apply_secret` en lugar de borrar y recrear secrets manualmente. El
certificado TLS de Traefik usa un helper separado porque debe ser un secret de
tipo `kubernetes.io/tls`, no un secret generic desde `.env`.

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

  test -f "$TLS_CERT_FILE"
  test -f "$TLS_KEY_FILE"

  kubectl create secret tls "$name" \
    --cert="$TLS_CERT_FILE" \
    --key="$TLS_KEY_FILE" \
    -n "$namespace" \
    --dry-run=client -o yaml | kubectl apply -f -
}
```

### 2.2 Namespaces

```bash
kubectl apply -f k8s/namespaces.yaml
kubectl get ns blockchain infra apis frontend kube-system
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
| `kube-system` | `trustnews-origin-tls` | `/home/sysadmin/trustnews-origin-ca/tls-origin.env` |

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

apply_tls_secret kube-system trustnews-origin-tls "$HOME/trustnews-origin-ca/tls-origin.env"
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

`tls-origin.env`:

```dotenv
TLS_CERT_FILE=/home/sysadmin/trustnews-origin-ca/assermetry-origin.pem
TLS_KEY_FILE=/home/sysadmin/trustnews-origin-ca/assermetry-origin.key
TLS_CA_FILE=/home/sysadmin/trustnews-origin-ca/cloudflare-origin-ca-rsa-root.pem
```

No incluir el contenido PEM dentro de `tls-origin.env`; este fichero solo debe
referenciar las rutas privadas del servidor. En Hetzner, tanto las pruebas por
tunel como el acceso posterior desde Cloudflare usan este mismo certificado
Origin CA; el certificado local de Kind se genera exclusivamente en su overlay.

### 2.4.1 Script de Secrets y reinstalacion de TLS en Hetzner

En Hetzner, `~/trust-news/secrets/create-secrets.sh` puede seguir creando los
Secrets genericos desde sus `.env`. La seccion de `kube-system` debe aplicar el
certificado Origin CA desde su directorio privado y nunca borrar primero el Secret.

Sustituir la seccion TLS del script por este bloque autocontenido:

```bash
# Namespace: kube-system
set -euo pipefail
TLS_ENV="$HOME/trustnews-origin-ca/tls-origin.env"

test -r "$TLS_ENV"

set -a
. "$TLS_ENV"
set +a

test -r "$TLS_CERT_FILE"
test -r "$TLS_KEY_FILE"
test -r "$TLS_CA_FILE"
openssl verify \
  -CAfile "$TLS_CA_FILE" \
  "$TLS_CERT_FILE"
openssl x509 -checkend 2592000 -noout -in "$TLS_CERT_FILE"
openssl x509 -in "$TLS_CERT_FILE" -noout -ext subjectAltName | \
  grep -q 'DNS:assermetry.com'

kubectl create secret tls trustnews-origin-tls \
  --cert="$TLS_CERT_FILE" \
  --key="$TLS_KEY_FILE" \
  -n kube-system \
  --dry-run=client -o yaml | \
  kubectl apply -f -
```

No usar `tls-fe.crt`, `tls-fe.key` ni `create-fe-certs.sh` como entrada del TLS
productivo. El Nginx del frontend sirve HTTP dentro del cluster; Traefik termina
TLS y consume exclusivamente `kube-system/trustnews-origin-tls`.

Orden para reinstalar desde cero:

1. Crear los namespaces.
2. Crear o aplicar los Secrets genericos desde `~/trust-news/secrets`.
3. Restaurar `~/trustnews-origin-ca` y comprobar permisos `700` para el
   directorio, `600` para la clave y `600` para `tls-origin.env`.
4. Ejecutar el bloque TLS anterior y comprobar la huella instalada.
5. Desplegar los perfiles productivos y verificar `TLSStore/default` antes de
   realizar pruebas por tunel.

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

### 2.6 Traefik, TLS de borde y pull secret

K3s publica HTTPS mediante Traefik. El frontend ya no genera ni monta
`frontend-tls`: su Nginx interno solo sirve estaticos por HTTP dentro del
cluster y Traefik enruta `/`, `/backend` y `/auth` por el entrypoint
`websecure`.

El controlador Traefik se instala y actualiza exclusivamente con Skaffold:
`traefik` en local y `traefik-prod` en Hetzner. Ambos perfiles fijan el
chart `41.0.2` y usan `k8s/traefik/values.yaml`. El job `deploy` instala
el cliente Helm verificado que necesita el deployer Helm de Skaffold. Los
upgrades usan `--atomic`: si el rollout falla, Helm restaura la revision
anterior y el pipeline termina con error. No ejecutar `helm upgrade` ni
parchear el Deployment manualmente.

`k8s/ingress/base/tls-store.yaml` configura `trustnews-origin-tls` como
certificado por defecto de Traefik. En Hetzner/prod ese secret debe crearse antes
de desplegar `apis-frontend-prod` con `apply_tls_secret`; `k8s/ingress/base/kustomization.yaml`
ya no genera certificados desde ficheros versionados del repo. El overlay local
si puede generar `trustnews-origin-tls` desde `web_classic/certs/*` para mantener
comodo el flujo de desarrollo.

Los Ingress estan restringidos a `websecure` con
`traefik.ingress.kubernetes.io/router.entrypoints: websecure` y
`traefik.ingress.kubernetes.io/router.tls: "true"`; no se publican estas rutas
por HTTP plano. Keycloak publica el issuer definido por `KC_HOSTNAME_URL` y el
Gateway valida exactamente esa misma URL mediante `KEYCLOAK_ISSUER_URL`.

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

### 2.7 Publicacion HTTPS: tunel primero, dominio despues

Los manifiestos activos de `k8s/ingress/overlays/prod` habilitan HTTPS en
Traefik con `host: localhost`. El despliegue estable sigue cerrado y se valida
por tunel SSH. Los overlays `prod-domain` contienen la configuracion futura de
`assermetry.com`, pero Skaffold todavia no los referencia.

#### 2.7.1 Despliegue cerrado con tunel SSH

Usar esta fase mientras solo este abierto `2222/tcp` en Hetzner. Mantener la
configuracion productiva temporal:

```text
KC_HOSTNAME_URL=https://localhost:9443/auth
KC_HOSTNAME_ADMIN_URL=https://localhost:9443/auth
KEYCLOAK_ISSUER_URL=https://localhost:9443/auth/realms/TrustNews
```

Abrir el tunel desde la maquina de trabajo:

```bash
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 9443:127.0.0.1:9443 \
  <usuario>@<hetzner-ip> \
  -t "kubectl port-forward --address 127.0.0.1 -n kube-system svc/traefik 9443:443"
```

Mantener esa sesion abierta mientras se validan las rutas:

```bash
curl -k -I https://localhost:9443/
test "$(curl -k -sS -o /dev/null -w '%{http_code}' https://localhost:9443/backend/docs)" = 404
curl -k -I https://localhost:9443/auth/realms/TrustNews/.well-known/openid-configuration
```

El issuer de Keycloak y el esperado por el Gateway deben coincidir exactamente:

```text
https://localhost:9443/auth/realms/TrustNews
```

No abrir `80/tcp` ni `443/tcp` al trafico de Internet durante esta fase.

#### 2.7.2 Despliegue publico con dominio

Cuando el dominio este decidido, pasar a una URL publica estable. Estrategia
recomendada inicial, menor cambio funcional:

```text
https://assermetry.com/          -> frontend
https://assermetry.com/backend   -> gateway
https://assermetry.com/auth      -> keycloak
```

Esta estrategia mantiene el contrato actual del frontend (`/backend` y
`/auth`). Es la opcion mas segura para la primera migracion a Traefik.

Estrategia futura, mas limpia para SaaS:

```text
https://app.assermetry.com       -> frontend
https://api.assermetry.com       -> gateway
https://auth.assermetry.com      -> keycloak
```

No usar subdominios hasta revisar el frontend, `root_path=/backend`, CORS,
redirects OIDC y el issuer de Keycloak.

Crear un registro `A` o `CNAME` hacia la IP publica que recibe Traefik o hacia
el balanceador de Hetzner:

```text
assermetry.com -> <ip-publica-o-load-balancer>
```

En el firewall de Hetzner, abrir solo `80/tcp` y `443/tcp` hacia el borde HTTP.
Mantener SSH restringido a `2222/tcp` y no publicar directamente `Gateway`,
`Keycloak`, `MongoDB`, `Kafka`, `IPFS` ni RPC blockchain.

#### 2.7.3 WAF obligatorio antes de abrir 80/443

No abrir `80/tcp` ni `443/tcp` a trafico general sin un WAF delante del borde
HTTP. El WAF debe estar activo antes de mover usuarios o clientes externos al
dominio real.

Opcion recomendada para la primera exposicion publica: Cloudflare delante del
dominio, con WAF gestionado, rate limiting, proteccion basica de bots y TLS en
modo `Full strict` cuando el origen tenga certificado valido.

Opcion in-cluster: desplegar un WAF compatible con OWASP CRS, por ejemplo
ModSecurity/Coraza, delante de Traefik o como proxy intermedio. Esta opcion da
mas control, pero introduce mas operacion y debe probarse con el login OIDC y
las APIs antes de abrir trafico.

Controles minimos requeridos:

- bloquear metodos HTTP no esperados;
- limitar tamano maximo de request body;
- aplicar rate limit a `/auth`, `/backend` y endpoints de token/login;
- activar reglas OWASP CRS en modo deteccion antes de bloquear;
- registrar eventos WAF y revisar falsos positivos;
- restringir el origen para que el trafico publico llegue por el WAF cuando sea posible.

En el plan Cloudflare Free no esta disponible la accion `Log` para reglas WAF
personalizadas. La fase de deteccion se adapta sin abrir el origen: mantener el
gate mTLS, revisar las muestras de Security Events de las ultimas 24 horas y
probar cada regla con trafico controlado antes de conservar el bloqueo. El plan
permite cinco reglas personalizadas y una regla de rate limiting; no repartir
esa unica regla entre refresh o polling y endpoints costosos sin medir primero
el trafico legitimo.

#### 2.7.3.1 Fase 5, paso 5.0: inventario sin despliegue

En Cloudflare, abrir la zona `assermetry.com` y registrar sin secretos:

1. `Security > WAF > Managed rules`: estado de `Cloudflare Free Managed
   Ruleset`.
2. `Security > WAF > Custom rules`: nombre, expresion resumida, accion y estado
   de cada regla. Debe seguir activa `Temporary mTLS gate - assermetry.com`.
3. `Security > WAF > Rate limiting rules`: confirmar si la unica regla
   disponible esta libre u ocupada.
4. `Security > Events`: revisar las ultimas 24 horas y anotar servicios,
   acciones y posibles falsos positivos. En Free son muestras, no un log
   exhaustivo.

Evidencia registrada el 2026-07-31:

- `Temporary mTLS gate - assermetry.com`: activa, accion `Block`, una de
  cinco reglas personalizadas y 238 eventos mostrados;
- rate limiting: cero de una regla, slot libre;
- `Cloudflare managed ruleset`: `Always active` en
  `Security > Settings > Web application exploits`; contiene 31 reglas
  visibles, con firmas generales y otras especificas de WordPress; las diez
  primeras reglas mostradas tienen accion `Block`;
- Security Events, filtrado por el Rule ID del gate mTLS y por 24 horas: todas
  las muestras visibles tienen accion `Block`, servicio `Custom rules`,
  varios paises y rafagas repetidas desde un mismo origen. No se guardan IP en
  Git;
- muestras inspeccionadas: `GET /backend/.git/config`, `GET /.git/config`
  y `GET /`, todas sobre `assermetry.com` y bloqueadas por el gate. Las dos
  primeras son reconocimiento hostil. La intencion de `GET /` es
  indeterminada, pero el bloqueo es correcto durante la fase privada porque no
  presento un certificado cliente valido. No hay evidencia de bloqueo a un
  tester autorizado. Incluir `/.git` y archivos sensibles en la proteccion
  permanente;
- sustitucion de librerias JavaScript inseguras: activa;
- modo `I'm under attack`: desactivado.

En Hetzner, sin aplicar manifests, contrastar el estado real:

```bash
kubectl get ingress -A -o wide
kubectl get svc -A \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,TYPE:.spec.type,PORTS:.spec.ports[*].port'
kubectl get pods -A \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount'
kubectl get pvc -A
kubectl get daemonset fluent-bit -n infra
kubectl get deployment loki grafana -n infra
```

El resultado esperado es:

- solo `frontend-ingress`, `gateway-ingress` y `keycloak-ingress`;
- ningun Service de aplicacion con tipo `NodePort` o `LoadBalancer`;
- Fluent Bit, Loki y Grafana presentes para la observabilidad in-cluster;
- ningun cambio en `prod-domain`, DNS, issuer, TLS o firewall.

Resultado contrastado en K3s el 2026-07-31:

- solo existen `gateway-ingress`, `frontend-ingress` y
  `keycloak-ingress`, todos con `host: localhost`;
- todos los Services de aplicacion e infraestructura son `ClusterIP`;
- MongoDB, Keycloak DB, Kafka, Kafdrop, Mongo Express, IPFS, RPC Ethereum y
  `admin-service` no tienen Ingress ni `NodePort`;
- el unico Service `LoadBalancer` es Traefik en `80/443`, el borde previsto
  cuyo acceso publico continua controlado por el firewall externo;
- no se guardan direcciones del cluster en Git.

Guardar la fecha y el resumen de resultados en
[`../version.md`](../version.md). No copiar IPs, tokens, certificados ni datos
personales a Git.

Estado de workloads y volumenes contrastado:

- 29 pods preparados y con cero reinicios, incluido el pod de balanceo de
  Traefik con sus dos contenedores preparados;
- siete PVC en estado `Bound` y StorageClass `local-path`: tres de
  blockchain y cuatro de infraestructura;
- capacidades declaradas: 2 GiB para el minero y 1 GiB para cada uno de los
  demas PVC. `kubectl get pvc` no informa del espacio realmente utilizado;
- Loki y Grafana no tienen PVC en los manifests actuales. Sus datos y
  configuracion son efimeros;
- Fluent Bit excluye `kube-system` en su filtro actual, de modo que los logs
  de Traefik no llegan a Loki.

Las dos ultimas brechas se resolveran en el paso de observabilidad de la Fase 5.

Linea base de recursos y observabilidad:

- Fluent Bit: `1/1`; Loki: `1/1`; Grafana: `1/1`; antiguedad 108 dias;
- nodo: 5% de CPU y 76% de memoria;
- disco raiz y almacenamiento `local-path`: 75 GiB totales, 38 GiB usados,
  35 GiB disponibles y 53% de ocupacion;
- consumidores destacados en la muestra: los tres nodos Geth suman
  aproximadamente 1,9 GiB, Kafka 577 MiB y Keycloak 469 MiB;
- umbrales propuestos: memoria 80% aviso y 90% critico; disco 75% aviso y 85%
  critico.

Comprobacion de APIs:

- Loki permite consultas y devuelve streams de `apis`, `blockchain` e
  `infra`;
- `kube-system` no aparece, como corresponde al filtro que excluye Traefik;
- `frontend` no aparece en la ventana consultada; puede no haber emitido logs
  recientes;
- Grafana responde con base de datos `ok`;
- una primera consulta a `/ready` mediante el proxy de la API de Kubernetes
  responde `ServiceUnavailable`;
- dos consultas directas consecutivas dentro del contenedor responden
  `HTTP 200` y `ready`. El `503` se considera transitorio o propio del
  camino de proxy, no una indisponibilidad persistente;
- Loki y Grafana tienen endpoints internos validos;
- el Deployment de Loki no define `readinessProbe` ni `livenessProbe`;
- los logs revisados solo muestran subida y limpieza normal de indices TSDB, sin
  errores en la muestra.

El inventario 5.0 queda cerrado. La ausencia de probes, persistencia de
Loki/Grafana y logs de Traefik se trata en el paso de observabilidad.


#### 2.7.3.2 Fase 5, paso 5.1: aislar la administracion

Mantener la asociacion Application Security mTLS de `assermetry.com`. La
asociacion hace que Cloudflare solicite y valide certificados; son las reglas
WAF las que deciden para que rutas son obligatorios.

Usar dos reglas personalizadas:

1. `Permanent mTLS - Keycloak administration`, activa permanentemente y antes
   de la regla temporal.
2. `Temporary mTLS gate - assermetry.com`, ya existente, activa durante las
   pruebas y desactivada unicamente en la Fase 9.
Estado comprobado tras la creacion:

- regla permanente: activa, accion `Block` y posicion 1. Dos peticiones sin
  certificado a `/auth/admin/master/console/` y
  `/auth/realms/master/.well-known/openid-configuration` devolvieron `403` y
  quedaron registradas como dos eventos en esta regla;
- regla temporal: activa, accion `Block` y posicion 2;
- ocupacion: dos de cinco reglas personalizadas.

La separacion entre ambas reglas se comprobo con peticiones sin certificado a
`/` y `/auth/realms/TrustNews/.well-known/openid-configuration`: ambas
devolvieron `403`. Security Events atribuyo expresamente la ruta del realm
`TrustNews` a la regla temporal. Su contador visible paso a 146 y la regla
permanente permanecio en 4, por lo que las rutas de aplicacion no coincidieron
con la proteccion administrativa. Los contadores mostrados son muestras
agregadas; no debe exigirse que aumenten exactamente una unidad por cada
peticion de prueba.

La prueba positiva posterior desde Microsoft Edge devolvio `403` para `/` y
`/auth/admin/master/console/`, no el `522` esperado mientras el origen esta
cerrado. Esto indica que Edge no presento un certificado que Cloudflare
considerase valido. Antes de reintentar, comprobar
`AutoSelectCertificateForUrls` en `edge://policy` y que
`cforcadell-win11-01` siga instalado con clave privada en el almacen personal
del usuario. No revocar ni reemitir el certificado durante este diagnostico.

Se comprobo que Edge carga y acepta la politica obligatoria, aplicada al
dispositivo, con patron `https://assermetry.com` y filtro
`CN=cforcadell-win11-01`. En `CurrentUser\My` tambien se verifico el
certificado esperado, vigente del 6 de agosto de 2026 al 5 de agosto de 2028,
con clave privada y EKU `Client Authentication`
(`1.3.6.1.5.5.7.3.2`). Antes de revisar Cloudflare, cerrar la sesion TLS de
Edge y repetir la prueba con una negociacion nueva.

El reinicio completo de Edge tampoco cambio el resultado: las rutas de
aplicacion y administracion siguieron devolviendo `403`. Comprobar ahora, sin
modificarlo, que el certificado figure `Active` en Cloudflare y que
`assermetry.com` siga asociado a la CA gestionada.

La inspeccion posterior confirmo ambos extremos: el hostname figura en `Hosts`
y `CN=cforcadell-win11-01, OU=Tester, O=Assermetry` esta `Active`, emitido por
la CA gestionada de la cuenta y vigente hasta el 5 de agosto de 2028. Para
separar un fallo de Edge de un rechazo de Cloudflare, presentar a continuacion
el certificado de forma explicita con `curl.exe` y Schannel desde el almacen de
Windows.

La prueba explicita devolvio `522` para `/` y para
`/auth/admin/master/console/`. Esto confirma que Cloudflare acepta el
certificado y que las reglas temporal y permanente permiten sus rutas cuando
`cert_verified` es verdadero; el firewall cerrado del origen produce despues
el timeout esperado. Los `403` del navegador quedan aislados a la seleccion
automatica de Edge y no justifican revocar ni reemitir el certificado.

Google Chrome reprodujo el `403` sin mostrar selector de certificado. Como
`curl.exe` con Schannel si presenta la misma credencial, probar Chromium con
QUIC/HTTP/3 desactivado de forma temporal antes de revisar VPN, proxy o la
cadena de emisores anunciada en la negociacion.

Al desactivar temporalmente `Experimental QUIC protocol`, Chrome mostro el
selector, presento el certificado y recibio `522`. El mTLS de navegador queda
validado sobre HTTP/2 y el timeout confirma que el origen sigue cerrado. Los
`403` anteriores quedan atribuidos al uso de QUIC/HTTP/3. Mantener la
restriccion sin QUIC en el navegador administrativo mientras las rutas
permanentes dependan de mTLS.

Edge tambien devolvio `522` para `/` despues de desactivar
`Experimental QUIC protocol`; la politica selecciono el certificado sin
mostrar dialogo. `/auth/admin/master/console/` tambien devolvio `522`, por lo
que quedan validadas la seleccion automatica y las reglas temporal y permanente
con certificado valido. Sustituir ahora el flag por la politica estable
`QuicAllowed=0`.

Configuracion durable validada en PowerShell con privilegios administrativos:

```powershell
New-ItemProperty `
  -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' `
  -Name 'QuicAllowed' `
  -PropertyType DWord `
  -Value 0 `
  -Force
```

Tras comprobar `QuicAllowed: false` en `edge://policy`, se devolvio
`Experimental QUIC protocol` a `Default` y se reinicio Edge. `/` y
`/auth/admin/master/console/` conservaron el `522`, confirmando que la politica
estable sustituye correctamente al flag. La politica desactiva QUIC para todo
Edge en ese dispositivo y debe mantenerse mientras sea el navegador
administrativo mTLS. Rollback, solo si deja de ser necesaria:

```powershell
Remove-ItemProperty `
  -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' `
  -Name 'QuicAllowed'
```

En esa prueba, `curl` notifico `certificate is not yet valid`. El uso puntual
de `-k` permitio aislar la validacion WAF, pero no constituye una solucion ni
debe incorporarse a scripts o procedimientos normales. La comprobacion mostro
que el cliente marcaba `2026-07-31 05:05 UTC` y no estaba sincronizado, aunque
NTP figuraba activo. El certificado servido para `assermetry.com` es valido
desde `2026-08-04 14:21:20 UTC`, y Cloudflare ya registraba eventos del 12 de
agosto. El reinicio de `systemd-timesyncd` no corrigio el reloj:
`timesync-status` mostro cero paquetes y el
journal registro timeouts para todos los destinos de `ntp.ubuntu.com`, tanto
IPv4 como IPv6. Esto apunta a falta de conectividad saliente UDP/123; no a un
fallo del certificado de Cloudflare. Ademas, el cliente se ejecuta sobre
VirtualBox y su `vboxadd-service` 7.0.12, aunque instalado y habilitado, estaba
inactivo desde el 13 de junio. Tras arrancarlo, Guest Additions corrigio el
reloj a `2026-08-12`; `curl` sin `-k` valido TLS correctamente y la ruta
administrativa devolvio el `403` esperado. En este escenario, `System clock
synchronized: no` refleja el estado de `systemd-timesyncd`; no invalida la
hora ya corregida por VirtualBox. El servicio de Guest Additions debe permanecer
activo.

Expresion de la regla permanente:

```text
(http.host eq "assermetry.com" and
 (
  http.request.uri.path eq "/auth/admin" or
  starts_with(http.request.uri.path, "/auth/admin/") or
  http.request.uri.path eq "/auth/realms/master" or
  starts_with(http.request.uri.path, "/auth/realms/master/")
 ) and
 (not cf.tls_client_auth.cert_verified or
  cf.tls_client_auth.cert_revoked))
```

Accion: `Block`. La comparacion exacta mas el prefijo terminado en `/` evita
afectar por accidente a rutas cuyo nombre solo comience de forma parecida.

Mientras ambas reglas estan activas:

- una peticion administrativa sin certificado coincide primero con la regla
  permanente;
- una peticion no administrativa sin certificado coincide con la temporal;
- cualquier ruta con certificado valido continua;
- Security Events permite revisar por separado ambos tipos de rechazo.

En la Fase 9 se desactiva solo `Temporary mTLS gate - assermetry.com`. No
desasociar mTLS del hostname y no desactivar la regla permanente.

La administracion por tunel SSH hacia Traefik evita Cloudflare y debe preservar
Host y SNI `assermetry.com`. El firewall del origen debe continuar impidiendo
que Internet use esa ruta directa. La documentacion del Gateway permanece
desactivada en `k8s/apis/gateway/overlays/prod`.

La parte Cloudflare/navegador del paso 5.1 queda cerrada tras probar ambas reglas
con y sin certificado. La disponibilidad real de `TrustNews` y el acceso
administrativo por tunel con Host/SNI canonico se validan en las Fases 6-7,
despues de activar `prod-domain`; no se abre ahora el firewall del origen.


#### 2.7.3.3 Fase 5, paso 5.2: metodos, cuerpos y rechazos

Gateway y Traefik limitan el cuerpo de las rutas `/backend` a 5 MiB
(`5242880` bytes). El valor de `GATEWAY_MAX_REQUEST_BODY_BYTES` debe coincidir
con `gateway-request-body-limit.spec.buffering.maxRequestBodyBytes`. Traefik
rechaza primero el trafico publico; Gateway repite el control para accesos
directos al Service y para cuerpos sin `Content-Length`. El limite incluye los
cuerpos fragmentados y se aplica antes de autenticacion y proxy.

Gateway emite un evento JSON `gateway_access` por respuesta. Incluye
`request_id`, metodo, ruta sin query string, estado, bytes recibidos y duracion.
No registra cabeceras de autorizacion ni el cuerpo. Los estados
`401/403/405/413/429` usan nivel warning y los `5xx` nivel error. Si el cliente
envia un `X-Request-ID` ASCII seguro se conserva; en otro caso se genera uno y
se devuelve en la respuesta.

Validacion automatizada:

```bash
cd api
tests/venv/bin/python -m pytest -q tests/test_gateway_security.py
cd ..
python3 -m py_compile api/gateway/main.py api/gateway/security.py

kubectl kustomize --load-restrictor=LoadRestrictionsNone \
  k8s/apis/gateway/overlays/local >/tmp/gateway-local.yaml
kubectl kustomize --load-restrictor=LoadRestrictionsNone \
  k8s/ingress/overlays/local >/tmp/ingress-local.yaml
```

La prueba del 2026-08-13 produjo ocho tests correctos y renders validos para
Gateway e Ingress, tanto local como prod. La imagen real del Gateway tambien se
construyo e importo correctamente con el maximo de `5242880`.

Con Gateway y Traefik desplegados en Kind, abrir temporalmente el borde:

```bash
kubectl port-forward -n kube-system svc/traefik 7443:443
```

En otra terminal, comprobar el metodo y ambos lados del limite:

```bash
curl -sk -o /dev/null -w "%{http_code}\n" -X DELETE \
  https://localhost:7443/backend/orders/list

head -c 5242880 /dev/zero | curl -sk -o /dev/null -w "%{http_code}\n" \
  -X POST -H "Content-Type: application/octet-stream" --data-binary @- \
  https://localhost:7443/backend/orders/publishNew

head -c 5242881 /dev/zero | curl -sk -o /dev/null -w "%{http_code}\n" \
  -X POST -H "Content-Type: application/octet-stream" --data-binary @- \
  https://localhost:7443/backend/orders/publishNew
```

El resultado observado fue `405`, `403` y `413`. El `403` de la peticion de
exactamente 5 MiB es esperado sin bearer token y demuestra que Traefik la
entrego a Gateway; el byte adicional fue rechazado por Traefik. Una prueba
directa al Service confirmo que la defensa interna de Gateway tambien devuelve
`413`. Los logs mostraron eventos JSON para `403`, `405` y `413`.

La comprobacion funcional de cuerpos superiores al limite se restringio a dos
peticiones: 5242918 bytes con `validation_mode=LIGHT` y 5242923 bytes con
`validation_mode=BLOCKCHAIN`. Las dos devolvieron `413` en Traefik y no
alcanzaron Gateway, por lo que no iniciaron procesamiento ni consumieron cuotas.

El despliegue en Hetzner se acepto el 2026-08-13 con el perfil
`apis-frontend-prod`. ConfigMap y middleware mostraron `5242880`; a traves de Traefik
se obtuvieron `405`, `401` y `413`, y el acceso directo a Gateway tambien
devolvio `413`. Su evento estructurado registro `body_bytes=5242881`, estado
`413` y `request_id`. El pod de Gateway permanecio preparado y sin reinicios.
Las ordenes legitimas Light y Blockchain completaron el flujo extremo a
extremo. La carrera de cache de validadores detectada durante la prueba Light
queda documentada como `ISSUE-001` en `docs/issues.md`; su mitigacion permitio
recibir las nueve respuestas esperadas, pero la correccion definitiva sigue
pendiente. El rate limiting de Cloudflare pertenece al paso 5.3; en 5.2 solo se
comprueba que Gateway puede registrar un `429` emitido por una dependencia.

#### 2.7.3.4 Fase 5, paso 5.3: Cloudflare

El paso se inicio el 2026-08-14. No requiere desplegar Kubernetes mientras no
cambien Gateway, Traefik ni sus manifests. La configuracion se aplica en la zona
`assermetry.com`, manteniendo activa la regla
`Temporary mTLS gate - assermetry.com` durante todas las pruebas.

El plan Free permite cinco reglas WAF personalizadas, sin accion `Log`, y una
regla de rate limiting. La regla de rate limiting solo puede filtrar por ruta,
usa la IP como caracteristica de conteo y ofrece una ventana y mitigacion de
10 segundos. Estas restricciones se deben volver a comprobar en el dashboard
antes de desplegar porque son limites del plan, no del repositorio. Referencias:

- [disponibilidad de WAF](https://developers.cloudflare.com/waf/);
- [reglas WAF personalizadas](https://developers.cloudflare.com/waf/custom-rules/);
- [limites de rate limiting](https://developers.cloudflare.com/waf/rate-limiting-rules/).

##### Inventario previo obligatorio

Antes de crear reglas, comprobar y anotar sin direcciones IP ni identificadores
de cuenta:

1. `Cloudflare Free Managed Ruleset` continua `Always active`.
2. `Permanent mTLS - Keycloak administration` continua activa y en primer
   lugar.
3. `Temporary mTLS gate - assermetry.com` continua activa y en segundo lugar.
4. Hay tres slots WAF libres y el unico slot de rate limiting sigue libre.
5. Security Events de las ultimas 24 horas no muestra falsos positivos para el
   tester autorizado.

No activar `Cloudflare Managed Ruleset` ni `Cloudflare OWASP Core Ruleset`: no
estan incluidos en Free. No habilitar manualmente reglas especificas de
WordPress; Assermetry no usa esa tecnologia. Conservar la configuracion por
defecto de la Free Managed Ruleset y revisar sus eventos muestreados.

Evidencia del 2026-08-14: el dashboard mostro `Cloudflare managed ruleset`
como `Always active`; las dos reglas mTLS continuaban activas y ordenadas, con
tres slots WAF y el slot de rate limiting libres. Tras aplicar la configuracion,
las dos reglas WAF permanentes nuevas quedaron activas en las posiciones 3 y 4,
el quinto slot quedo libre y `Expensive backend operations per IP` quedo activa
como unica regla de rate limiting (`1/1`) con umbral `5/10 s`. Las pruebas de
rechazo y los flujos legitimos siguen pendientes.

##### Regla personalizada 3: recursos no publicos

Nombre: `Permanent block - non-public resources`

Expresion:

```text
(http.host eq "assermetry.com" and
 (
  lower(http.request.uri.path) in {
   "/backend/docs"
   "/backend/docs/"
   "/backend/redoc"
   "/backend/redoc/"
   "/backend/openapi.json"
   "/.git"
   "/backend/.git"
  } or
  starts_with(lower(http.request.uri.path), "/.git/") or
  starts_with(lower(http.request.uri.path), "/backend/.git/")
 ))
```

Accion: `Block`. Situarla despues de las dos reglas mTLS. Agrupar documentacion
y metadatos Git en una sola regla conserva un slot para ajustes posteriores.
La documentacion del Gateway ya esta desactivada en produccion; esta regla es
una defensa externa adicional.

Pruebas controladas con certificado cliente valido:

```text
GET /backend/openapi.json -> 403 de Cloudflare
GET /.git/config         -> 403 de Cloudflare
GET /backend/.git/config -> 403 de Cloudflare
GET /                    -> no coincide con esta regla
```

Revisar el Ray ID de cada rechazo en Security Events y confirmar que el servicio
es `Custom rules` y que coincide con esta regla. No guardar el Ray ID ni la IP
del cliente en Git.

Prueba aceptada el 2026-08-14 desde Edge con certificado cliente valido:
`GET /` devolvio `522`, demostrando que la conexion supero el gate mTLS y
alcanzo el origen cerrado. En la misma sesion, `GET /backend/openapi.json`,
`GET /.git/config` y `GET /backend/.git/config` devolvieron `403`. El
contraste con el control `522` confirma que los tres recursos fueron bloqueados
en Cloudflare por la nueva proteccion y no por ausencia de certificado.

##### Regla personalizada 4: metodos del Gateway

Nombre: `Permanent block - unexpected backend methods`

Expresion:

```text
(http.host eq "assermetry.com" and
 (http.request.uri.path eq "/backend" or
  starts_with(http.request.uri.path, "/backend/")) and
 not (http.request.method in {"GET" "HEAD" "POST" "OPTIONS"}))
```

Accion: `Block`. Situarla despues de `Permanent block - non-public resources`.
La regla solo afecta al Gateway; no limita operaciones administrativas de
Keycloak, que permanecen bajo mTLS. `OPTIONS` se conserva para preflight y
`HEAD` para comprobaciones de bajo coste.

Pruebas controladas con certificado valido:

```text
DELETE /backend/orders/list -> 403 de Cloudflare
GET    /backend/orders/list -> alcanza el Gateway y exige autenticacion
POST   /backend/orders/publishNew -> alcanza el Gateway y exige autenticacion
```

No usar una peticion de publicacion valida en esta comprobacion inicial. Un
`POST` sin bearer token basta para demostrar que el metodo atraviesa el WAF sin
crear una orden.

Prueba aceptada el 2026-08-14 desde la misma sesion mTLS de Edge:
`DELETE /backend/orders/list` devolvio `403`, mientras que el control
`GET /backend/orders/list` devolvio `522` al continuar hasta el origen
cerrado. Esto confirma que la regla bloquea el metodo inesperado y permite el
metodo valido.

##### Unica regla de rate limiting

Nombre: `Expensive backend operations per IP`

Expresion compatible con Free:

```text
http.request.uri.path in {
 "/backend/extract_text_from_url"
 "/backend/assertions/generate"
 "/backend/orders/publishNew"
 "/backend/orders/publishWithAssertions"
}
```

Configuracion inicial:

- caracteristica: IP, con el centro de datos que Cloudflare incorpora al
  contador;
- limite: 5 peticiones por 10 segundos;
- accion: `Block`;
- duracion: 10 segundos;
- respuesta: la predeterminada de Cloudflare (`429`); Free no permite una
  respuesta de bloqueo personalizada.

La expresion no incluye metodo ni hostname porque esos campos no estan
disponibles para rate limiting en Free. Las reglas WAF anteriores ya restringen
el hostname y los metodos publicos previstos.

No incluir el endpoint de token de Keycloak. Login y refresh comparten
`/auth/realms/TrustNews/protocol/openid-connect/token`, y Free no permite
distinguir `grant_type=password` o `grant_type=refresh_token` en el cuerpo. Una
regla por ruta bloquearia tambien refresh legitimos. Tampoco incluir listados,
consulta de ordenes, eventos ni ningun endpoint de polling.

Validar el umbral sin ejecutar importaciones, IA ni publicaciones reales:

1. Con certificado cliente valido, enviar peticiones `HEAD` escalonadas a una
   de las cuatro rutas dentro de una ventana de 10 segundos. Gateway puede
   responder `405`, pero la ruta incrementa el contador sin iniciar el trabajo
   costoso.
2. Confirmar que alguna peticion posterior al umbral devuelve `429` de
   Cloudflare. El rate limiting no garantiza que la sexta peticion sea la
   primera bloqueada: Cloudflare documenta un retardo de hasta varios segundos
   entre la deteccion y la actualizacion del contador.
3. Esperar mas de 10 segundos y comprobar que deja de responder `429`.
4. Filtrar Security Events por `Rate limiting rules` y revisar la muestra.
5. Ejecutar una vez los flujos legitimos de importar, generar, publicar Light y
   publicar Blockchain. Ninguno debe recibir `429`.

El umbral `5/10 s` es inicial. Mantenerlo solo si las pruebas funcionales y las
muestras no muestran falsos positivos; cualquier ajuste debe documentar el
motivo y conservar fuera de la regla los endpoints de refresh y polling.

La primera prueba del 2026-08-14 envio seis `HEAD` simultaneos a
`/backend/assertions/generate`; los seis devolvieron `522` y no se observo
`429`. Este resultado no valida el bloqueo, pero es compatible con el retardo
de actualizacion documentado para rafagas simultaneas. Se conserva la regla sin
cambios y se repite una sola vez con peticiones escalonadas dentro de la misma
ventana.

La prueba definitiva evito el timeout del origen usando una sonda Log4J inerte,
con destino `.invalid`, en la query string de la misma ruta. La Free Managed
Ruleset, que se ejecuta despues de rate limiting, devolvio rapidamente `403`
sin alcanzar el origen. Tras limpiar la ventana, quince peticiones `HEAD`
secuenciales produjeron cinco respuestas `403` y diez respuestas `429`: el
bloqueo comenzo exactamente en la sexta peticion. Pasados 15 segundos, una
peticion de recuperacion volvio a obtener `403`, confirmando que la mitigacion
de 10 segundos habia expirado. La ruta temporal `/cdn-cgi/trace`, usada en un
intento anterior, se retiro de la expresion definitiva porque las respuestas
internas de Cloudflare no incrementaron este contador.

Security Events confirmo despues, mediante logs muestreados y sin exportarlos,
los tres servicios esperados: `Custom rules` para las cuatro comprobaciones de
recursos y metodos, `Managed rules` para la sonda controlada y
`Rate limiting rules` para los `429`. El detalle de una muestra de rate
limiting identifico `Expensive backend operations per IP`, metodo `HEAD` y
ruta `/backend/assertions/generate`. No se conservan en Git IP, Ray ID, Rule ID
ni Ruleset ID. No se observaron falsos positivos en la muestra revisada.

##### Orden final y criterio de aceptacion

Orden de reglas personalizadas:

1. `Permanent mTLS - Keycloak administration`.
2. `Temporary mTLS gate - assermetry.com`.
3. `Permanent block - non-public resources`.
4. `Permanent block - unexpected backend methods`.

El quinto slot permanece libre. El gate temporal no se desactiva en este paso.
Cloudflare evalua rate limiting despues de las reglas personalizadas, por lo
que el trafico sin certificado seguira bloqueado por el gate durante las
pruebas.

Marcar 5.3 como completado cuando:

- la Free Managed Ruleset y las cuatro reglas personalizadas consten activas;
- los recursos no publicos y los metodos inesperados devuelvan `403`;
- la rafaga controlada produzca `429` y se recupere tras la mitigacion;
- Security Events atribuya correctamente los rechazos, sin falsos positivos;
- no se hayan abierto el firewall del origen ni `prod-domain`.

Estos criterios de borde quedaron aceptados el 2026-08-14. Login, refresh,
polling, importacion, generacion y ambos modos de publicacion no se pueden
probar a traves de Cloudflare mientras el origen permanece cerrado. Su regresion
funcional se conserva como gate obligatorio de las Fases 6-7, antes de admitir
trafico general; no se abre el firewall ni se activa `prod-domain` para cerrar
5.3.

#### 2.7.3.5 Fase 5, paso 5.4: observabilidad y cierre

El primer incremento de 5.4 corrige las brechas detectadas en 5.0 sin exponer
ningun servicio nuevo:

- Loki dispone de un PVC montado en `/loki`, la ruta usada por su
  configuracion local: 2 GiB en Kind y 5 GiB en Hetzner;
- Grafana dispone de un PVC de 1 GiB montado en `/var/lib/grafana`;
- ambos Deployments tienen `startupProbe`, `readinessProbe` y
  `livenessProbe` sobre sus endpoints HTTP internos;
- Fluent Bit deja de excluir `kube-system` y publica la etiqueta
  `container`, lo que permite aislar los logs de Traefik en Loki. Se siguen
  excluyendo `local-path-storage` e `ingress-nginx`.

Los PVC usan la StorageClass predeterminada para conservar la compatibilidad
entre Kind y K3s. En K3s se espera `local-path`. No se crea Ingress,
`NodePort` ni `LoadBalancer` adicional.

Antes del primer despliegue, exportar los dashboards o configuraciones de
Grafana que deban conservarse y guardar las evidencias de Loki necesarias. Los
datos actuales son efimeros: al montar los PVC nuevos, el contenido del
filesystem de los pods anteriores no se migra automaticamente.

Validacion estatica realizada:

```bash
git diff --check
./skaffold render --offline -p infra -o /tmp/skaffold-infra.yaml
./skaffold render --offline -p infra-prod -o /tmp/skaffold-infra-prod.yaml
```

Validacion local en Kind del 2026-08-17: ambos PVC quedaron `Bound` con
StorageClass `standard`; Loki, Grafana y los dos pods de Fluent Bit quedaron
preparados y sin reinicios. `/ready` respondio `ready` y
`/api/health` devolvio base de datos `ok`. Loki mostro los valores
`kube-system` y `traefik` en sus catalogos de etiquetas despues de reiniciar
Traefik de forma controlada. La consulta de sus lineas no se da aun por
aceptada: durante la prueba el reloj del entorno salto del 14 al 17 de agosto,
Loki marco transitoriamente su ingester como no saludable y Fluent Bit recibio
`500`; los reintentos posteriores terminaron correctamente. Repetir la
consulta con relojes coherentes en Hetzner antes de cerrar la brecha.

El despliegue en Hetzner se ejecuto el 2026-08-17 y la evidencia posdespliegue
quedo aceptada el 2026-08-18. El flujo reproducible es GitLab CI: publicar los
cambios y lanzar el pipeline manual sobre `postTFM` con:

```dotenv
PROFILE=infra-prod
```

El job `build` incluye cambios bajo `k8s/infra/**`; el job `deploy`
ejecuta `skaffold deploy --build-artifacts=build.json --profile=infra-prod`.
Skaffold renderiza `frontend-logs/overlays/prod`, donde el patch eleva solo
`loki-data` a 5 GiB. La anotacion de checksum del DaemonSet provoca el
rollout de Fluent Bit al cambiar su ConfigMap. El propio job espera los
rollouts de Loki, Grafana y Fluent Bit y falla si los PVC no solicitan
respectivamente 5 GiB y 1 GiB. No usar `kubectl apply` manual para este
despliegue.

Evidencia recogida el 2026-08-17 a las 14:35 UTC: los rollouts de Loki, Grafana
y Fluent Bit finalizaron correctamente; `loki-data` y `grafana-data` estaban
`Bound` sobre `local-path` con 5 GiB y 1 GiB; los tres componentes estaban
preparados y sin reinicios. Se omiten nombres de pod y datos identificativos
del servidor.

Salud validada el 2026-08-17 a las 14:37 UTC: dos muestras separadas por 16
segundos devolvieron Loki `ready` y Grafana 11.5.2 con base de datos `ok`.
Loki, Grafana y Fluent Bit permanecieron preparados y con cero reinicios.

La primera consulta de ingesta en Hetzner devolvio correctamente el catalogo
de namespaces de Loki, incluidos `apis` y `kube-system`, pero no encontro
streams de Traefik ni Gateway en las ultimas 24 horas. La consulta ampliada
confirmo ingesta actual a las 14:44 UTC desde `coredns`, `news-chain` y
`evidence-search`; no hay una interrupcion general entre Fluent Bit y Loki.
El resumen de 162 lineas internas de Fluent Bit se clasifico despues en once
eventos entre las 09:04:43 y las 09:06:39 UTC: seis errores genericos, dos
fallos de envio, dos reintentos y una respuesta HTTP 500 de Loki. La ultima
hora no contenia eventos y la ingesta actual estaba confirmada; se consideran
transitorios del despliegue, no un fallo persistente. Una peticion GET
controlada, sin credenciales y sin escritura devolvio el `403` esperado;
Gateway genero dos muestras en Loki a las 14:50:00 UTC. Traefik no genero
muestras en la misma ventana. Sus argumentos activos no habilitan access log;
tampoco existe un `HelmChartConfig/traefik` ni un `HelmChart/traefik`
empaquetado de K3s. El Deployment pertenece a la release Helm `traefik`,
revision 1, con chart `traefik-41.0.2` e imagen
`docker.io/traefik:v3.7.6`. La release figura desplegada y el Deployment no
tiene `ownerReference`, como es habitual con Helm. La revision del proyecto y
de su historial confirmo que Skaffold desplegaba los Ingress, pero no declaraba
el chart ni la release Traefik. La correccion queda preparada en Git: los
perfiles `traefik` y `traefik-prod` fijan el chart `41.0.2`, consumen
`k8s/traefik/values.yaml` y activan access log JSON sin cabeceras ni
parametros de consulta. GitLab CI instala Helm 3.21.0 con SHA-256 verificado
en los jobs `build` y `deploy`, aplica el upgrade con `--atomic` y
comprueba el rollout y `--accesslog=true`. El esquema, el render real del
chart, el `build.json` sin imagenes y el YAML estan validados. No ejecutar
`helm upgrade` manual ni parchear el Deployment.

El primer pipeline `traefik-prod` fallo en `build` porque Helm solo estaba
instalado en `deploy`; no hubo cambios en Kubernetes. El segundo actualizo la
release a la revision 2, pero termino con codigo 1 porque el perfil heredaba el
deployer global `kubectl` sin manifests. El tercero, con Helm en ambos jobs y
los perfiles exclusivamente Helm, finalizo correctamente el 2026-08-17 a las
15:41 UTC: release en revision 3, Deployment preparado, rollout aceptado y
comprobacion de access log superada. A las 15:44 UTC se confirmaron de nuevo el
rollout, un pod preparado con cero reinicios y los argumentos de access log,
formato JSON, descarte de cabeceras y descarte de parametros de consulta. A las
15:46 UTC, las peticiones controladas devolvieron frontend `200`, discovery
OIDC `200` y Gateway protegido `403`. Loki respondio `success`, pero el
primer extractor no encontro `DownstreamStatus`. La lectura directa y
resumida de stdout confirmo 25 lineas, tres JSON de access log y los tres
eventos controlados: dos `200` y un `403`. Traefik genera correctamente los
registros. La consulta estructural de Loki devolvio tres streams y 50 muestras
con campos superiores `kubernetes` y `log`: Fluent Bit conserva el evento en
`log` con un prefijo anterior al JSON. La ingesta quedo confirmada con una
correlacion final que recupero exactamente los tres eventos de las 15:46:23
UTC: `GET /` con `200`, discovery OIDC con `200` y
`GET /backend/orders/list` con `403`.

La linea base de persistencia de las 15:53 UTC confirmo ambos PVC `Bound`, pods
preparados y sin reinicios, la base de Grafana presente con 1.110.016 bytes y
Loki `ready`. Los identificadores y el hash se conservan solo para la
comparacion operativa y no se registran en esta guia.

A las 15:55 UTC, el reinicio controlado de Loki creo un pod nuevo preparado y
sin reinicios, mantuvo el mismo PVC de 5 GiB y devolvio `ready`. La primera
consulta historica devolvio cero eventos mientras el pod anterior aun figuraba
preparado y pendiente de terminar. Tras quedar una sola replica preparada, la
consulta del mismo intervalo devolvio cero streams y cero muestras. El
diagnostico confirmo la causa: el PVC estaba montado en `/tmp/loki`, vacio,
mientras la configuracion efectiva usa `/loki` para `path_prefix`, chunks y
WAL. El manifiesto quedo corregido para montar `loki-data` en `/loki`.
El overlay productivo se renderizo localmente y conserva la imagen 3.0.0, las
probes y `claimName: loki-data`, con `mountPath: /loki`. `infra-prod` desplego
la correccion y, a las 16:05 UTC, el mismo PVC de 5 GiB estaba `Bound` en
`/loki`, con cuatro archivos, WAL bajo el PVC, pod preparado sin reinicios y
Loki `ready`. El probe controlado devolvio `404`, aparecio una vez antes del
segundo reinicio y permanecio una vez despues. El pod fue reemplazado, quedo
preparado y con cero reinicios. Grafana tambien reemplazo su pod y conservo la
base persistente, el datasource Loki y la consulta del mismo probe. La
persistencia de ambos componentes queda aceptada.

**Cierre del 2026-08-18:** Loki y Grafana conservaron respectivamente el probe
y el datasource tras reemplazar sus pods. Los `401` y `403` se correlacionaron
en Gateway y Loki; Cloudflare produjo cinco `403`, diez `429` y recupero el
`403` tras 15 segundos; una consulta blockchain imposible y de solo lectura
produjo un `500` correlacionado en Gateway y Loki. Security Events mostro las
diez acciones de rate limiting esperadas, sin falsos positivos visibles.

Desde una sesion operativa en el servidor, la parte de Loki se puede ejecutar
sin imprimir logs crudos mediante:

```bash
./scripts/k8s/infra/verify-loki-persistence.sh --execute
```

El script exige el PVC productivo `loki-data` de 5 GiB sobre `local-path`,
comprueba el montaje en `/loki`, genera el probe contra el origen local,
verifica su ingesta antes y despues de reemplazar el pod y solo devuelve
codigos de estado, recuentos y salud. No sustituye la comprobacion visual en
Grafana Explore.

El procedimiento reproducible es publicar los cambios y lanzar un pipeline
manual sobre `postTFM` con:

```dotenv
PROFILE=traefik-prod
```

El servidor no dispone de `jq`; usar `python3` para resumir el JSON sin
mostrar lineas de log y sin instalar paquetes adicionales.

Comprobar dos veces `/ready` de Loki y `/api/health` de Grafana, y confirmar
que los pods permanecen preparados y sin reinicios. En Loki, usar estas
consultas iniciales sin copiar tokens, IP, Ray IDs ni cuerpos a Git:

Para acceder a Grafana desde Windows sin publicar ningun puerto del servicio,
crear el port-forward remoto y transportarlo por SSH. Se usa el puerto local
`13000` porque el `3000` puede estar ocupado o reservado por Windows:

```bat
ssh -o ExitOnForwardFailure=yes -i .\id_rsa_hetzner_deploy -p 2222 -L 13000:127.0.0.1:3000 sysadmin@<SERVER_IP> -t "kubectl port-forward --address 127.0.0.1 -n infra svc/grafana 3000:3000"
```

Abrir `http://127.0.0.1:13000`. El mensaje remoto
`Forwarding from 127.0.0.1:3000` confirma el `kubectl port-forward`; la opcion
`ExitOnForwardFailure=yes` evita mantener la sesion si falla el enlace local.
No registrar la IP real del servidor en Git. Este acceso se valido el
2026-08-17, pero solo demuestra alcanzabilidad: ejecutar igualmente las
comprobaciones de salud, persistencia y reinicios.

##### Consultar los logs desde Grafana

El manifiesto actual no provisiona automaticamente un datasource. El
datasource Loki se configuro y su persistencia se valido el 2026-08-18. Para
reproducir la configuracion, tras abrir
`http://127.0.0.1:13000`, iniciar sesion con las credenciales operativas sin
copiarlas a Git. Ir a **Connections > Data sources** y comprobar si existe
`Loki`. Si no existe, seleccionar **Add data source > Loki**, usar como URL
interna `http://loki.infra.svc.cluster.local:3100` y pulsar **Save & test**. No
habilitar autenticacion basica ni introducir secretos: Grafana y Loki se
comunican dentro del namespace `infra`. Esta configuracion queda en
`/var/lib/grafana/grafana.db` y formara parte de la prueba de persistencia de
Grafana.

Ir a **Explore**, seleccionar el datasource `Loki`, elegir un intervalo que
incluya la prueba y usar el modo **Code** con estas consultas:

```text
{namespace="kube-system", container="traefik"}
{namespace="kube-system", container="traefik"} |= "/observability-persistence-probe-20260817T1605Z"
{namespace="apis", container="gateway"} | json | event="gateway_access"
{namespace="apis", container="gateway"} | json | status=~"401|403|429|5.."
{namespace="infra", container="keycloak"} |~ "(?i)(error|exception)"
```

La primera consulta permite navegar por los access logs de Traefik y la
segunda aisla el probe persistido. Expandir una fila solo durante la revision
operativa; no exportar ni copiar a Git lineas crudas que puedan contener IP,
identificadores o rutas sensibles.

Las evidencias controladas y su correlacion quedaron aceptadas el 2026-08-18.
Metrics Server no proporciona almacenamiento historico ni alertas. Hasta
incorporar un backend de metricas, comprobar los umbrales de memoria (80%/90%)
y disco (75%/85%) con `kubectl top nodes`, `kubectl top pods -A` y `df` en el
nodo. La muestra de cierre registro CPU 5%, memoria 78%, disco 56% y 31,7 GiB
disponibles; 29 de 29 pods activos preparados, 9 de 9 PVC `Bound` y cero
reinicios. La memoria queda por debajo del aviso, pero debe vigilarse durante
la Fase 6. El paso 5.4 y la Fase 5 quedan cerrados.

#### 2.7.4 TLS del origen con Cloudflare Origin CA

La estrategia productiva usa un certificado Cloudflare Origin CA emitido y
rotado manualmente. Traefik lo consume desde
`kube-system/trustnews-origin-tls` mediante `TLSStore/default`.

Esta CA esta pensada para el tramo Cloudflare-origen. Un navegador conectado
directamente por tunel no confia en ella por defecto; la validacion operativa se
realiza con la raiz Origin CA correspondiente. El aviso visual por tunel es
esperado y no afecta a `Full (strict)`.

##### 2.7.4.1 Emitir el certificado

En una maquina de operacion privada, generar la clave y el CSR para evitar que la
clave privada se genere o almacene en Cloudflare:

```bash
umask 077
openssl genpkey -algorithm RSA \
  -pkeyopt rsa_keygen_bits:3072 \
  -out assermetry-origin.key

openssl req -new \
  -key assermetry-origin.key \
  -out assermetry-origin.csr \
  -subj '/CN=assermetry.com' \
  -addext 'subjectAltName=DNS:assermetry.com'
```

En Cloudflare:

1. Abrir `SSL/TLS > Origin Server > Origin Certificates`.
2. Seleccionar `Create Certificate`.
3. Elegir `Use my private key and CSR` y pegar el CSR, nunca la clave.
4. Confirmar que el unico hostname requerido es `assermetry.com`.
5. Elegir y registrar el periodo de validez.
6. Seleccionar formato PEM y guardar el certificado firmado como
   `assermetry-origin.pem` fuera de Git.

Cloudflare no envia actualmente avisos de expiracion de Origin CA. Registrar
`notAfter` en el inventario y crear una alerta operativa anterior a esa fecha.

##### 2.7.4.2 Validar antes de instalar

```bash
chmod 600 assermetry-origin.key assermetry-origin.csr assermetry-origin.pem

openssl x509 -in assermetry-origin.pem -noout \
  -subject -issuer -dates -fingerprint -sha256 -ext subjectAltName

openssl x509 -in assermetry-origin.pem -pubkey -noout |
  openssl pkey -pubin -outform PEM |
  sha256sum

openssl pkey -in assermetry-origin.key -pubout -outform PEM |
  sha256sum
```

Las dos ultimas huellas deben ser identicas. El SAN debe incluir exactamente
`DNS:assermetry.com` y el certificado debe estar vigente. No continuar si falla
alguna comprobacion.

Descargar tambien la raiz que corresponda al algoritmo elegido. Para RSA:

```text
https://developers.cloudflare.com/ssl/static/origin_ca_rsa_root.pem
```

La raiz es publica y sirve solo para validar la cadena; no debe confundirse con
la clave privada del certificado.

##### 2.7.4.3 Instalar en K3s

Conservar los ficheros del certificado anterior y su `tls-origin.env` para
rollback. Preparar un nuevo fichero privado:

```dotenv
TLS_CERT_FILE=/home/sysadmin/trustnews-origin-ca/assermetry-origin.pem
TLS_KEY_FILE=/home/sysadmin/trustnews-origin-ca/assermetry-origin.key
TLS_CA_FILE=/home/sysadmin/trustnews-origin-ca/cloudflare-origin-ca-rsa-root.pem
```

Aplicar mediante el helper idempotente:

```bash
apply_tls_secret kube-system trustnews-origin-tls "$HOME/trustnews-origin-ca/tls-origin.env"
```

Comprobar el Secret y el consumidor sin mostrar la clave:

```bash
kubectl get secret trustnews-origin-tls -n kube-system \
  -o custom-columns='NAME:.metadata.name,TYPE:.type,CREATED:.metadata.creationTimestamp'

kubectl get tlsstore default -n kube-system \
  -o jsonpath='{.spec.defaultCertificate.secretName}{"\n"}'

kubectl get secret trustnews-origin-tls -n kube-system \
  -o jsonpath='{.data.tls\.crt}' |
  base64 -d |
  openssl x509 -noout -subject -issuer -dates -fingerprint -sha256 -ext subjectAltName
```

El `TLSStore` debe seguir devolviendo `trustnews-origin-tls`.

##### 2.7.4.4 Validar por tunel y hacer rollback

Con el tunel `127.0.0.1:9443` activo, validar cadena, SNI y hostname sin `-k`:

```bash
openssl s_client \
  -connect 127.0.0.1:9443 \
  -servername assermetry.com \
  -verify_hostname assermetry.com \
  -CAfile origin_ca_rsa_root.pem \
  -verify_return_error </dev/null
```

El resultado debe contener `Verify return code: 0 (ok)`. Repetir frontend,
Gateway y discovery OIDC por tunel. No activar `prod-domain` ni abrir el
firewall en esta fase.

Rollback: preparar un fichero privado que apunte al material anterior validado:

```dotenv
TLS_CERT_FILE=/home/sysadmin/trustnews-origin-ca/rollback-20260811T155518Z/tls.crt
TLS_KEY_FILE=/home/sysadmin/trustnews-origin-ca/rollback-20260811T155518Z/tls.key
```

Aplicarlo mediante el mismo helper idempotente:

```bash
apply_tls_secret kube-system trustnews-origin-tls "$HOME/trustnews-origin-ca/tls-origin-rollback.env"
```

Verificar de nuevo `TLSStore`, huella y pruebas funcionales. La revocacion del
certificado Origin CA en Cloudflare es irreversible y solo se realiza despues
del rollback si la clave se ha perdido o comprometido.

Los Ingress deben conservar estas anotaciones Traefik:

```yaml
metadata:
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
```

En `gateway-ingress` conservar tambien la anotacion del middleware:

```yaml
traefik.ingress.kubernetes.io/router.middlewares: apis-gateway-strip-backend-prefix@kubernetescrd
```

#### 2.7.5 Fijar host en los Ingress

Como preparacion estatica de la Fase 6, Skaffold referencia ya
`k8s/ingress/overlays/prod-domain` para que los tres Ingress tengan el mismo
`host`:

```yaml
spec:
  ingressClassName: traefik
  rules:
    - host: assermetry.com
      http:
        paths:
          - path: /backend
            pathType: Prefix
            backend:
              service:
                name: gateway
                port:

                  number: 8500
```

Aplicar el mismo `host` a:

```text
k8s/ingress/base/frontend-ingress.yaml   path /
k8s/ingress/base/gateway-ingress.yaml    path /backend
k8s/ingress/base/keycloak-ingress.yaml   path /auth
```

Los parches se mantienen en `k8s/ingress/overlays/prod-domain`; `base` continua
sin dominio para reutilizarlo en local e integracion. El cambio de referencia
esta preparado y renderizado, pero aun no se ha desplegado en K3s.

#### 2.7.6 Alinear Keycloak y Gateway

El dominio publico cambia el issuer de los tokens. Antes de desplegar, alinear
Keycloak y Gateway.

En `k8s/infra/keycloak/overlays/prod-domain/kustomization.yaml`:

```yaml
configMapGenerator:
- name: keycloak-env-config
  namespace: infra
  behavior: merge
  literals:
    - KC_HOSTNAME_URL="https://assermetry.com/auth"
    - KC_HOSTNAME_ADMIN_URL="https://assermetry.com/auth"
```

En `k8s/apis/gateway/overlays/prod-domain/kustomization.yaml`:

```yaml
configMapGenerator:
- name: gateway-config
  namespace: apis
  behavior: merge
  literals:
    - KEYCLOAK_ISSUER_URL="https://assermetry.com/auth/realms/TrustNews"
    - GATEWAY_API_DOCS_ENABLED="false"
```

La URL JWKS completa se mantiene comun en el ConfigMap base y usa la red interna:

```text
http://keycloak.infra.svc.cluster.local:8080/auth/realms/TrustNews/protocol/openid-connect/certs
```

El issuer esperado por Gateway debe coincidir exactamente con el issuer real de
Keycloak:

```text
https://assermetry.com/auth/realms/TrustNews
```

No añadir `:443`: el puerto HTTPS implicito no forma parte del issuer canonico.

El display name `Assermetry` del realm y los redirects, post-logout redirects y
Web Origins de `TrustNewsWeb` se almacenan en PostgreSQL. Preparar sus valores en
la Fase 1, pero aplicarlos coordinadamente con estos overlays en la Fase 6 para
no romper antes el acceso por `https://localhost:9443`.

#### 2.7.7 Orden de despliegue recomendado para apertura publica

1. Validar primero la aplicacion completa por tunel SSH segun la seccion 2.7.1.
2. Instalar/configurar el WAF y dejarlo en modo deteccion si aplica.
3. Crear DNS y verificar que resuelve al WAF, a Traefik o al balanceador.
4. Emitir e instalar manualmente el certificado Cloudflare Origin CA segun la
   seccion 2.7.4, conservando el certificado anterior para rollback.
5. Verificar que `TLSStore` apunta a `trustnews-origin-tls` y validar por tunel
   la cadena, SNI y hostname con la raiz Origin CA correspondiente.
6. **Despliegue iniciado el 2026-08-18:** Skaffold usa los overlays
   `prod-domain`. `infra-prod` se aplico correctamente mediante el pipeline
   `#2770049730`; `apis-frontend-prod` permanece pendiente hasta validar
   Keycloak. El diff renderizado solo cambia las dos URLs externas de Keycloak,
   el issuer del Gateway y los tres hosts a `assermetry.com`, manteniendo TLS en
   `websecure`.
7. Verificar `KC_HOSTNAME_URL` y `KEYCLOAK_ISSUER_URL`.
8. Lanzar el pipeline con `PROFILE=infra-prod`. El job
   `check_phase6_origin_tls` debe completar antes de `deploy`: comprueba que
   `TLSStore/default` referencia `trustnews-origin-tls`, que el Secret tiene el
   tipo TLS, que el certificado corresponde a `assermetry.com`, conserva al
   menos 30 dias de vigencia y forma pareja con su clave. No continuar si
   falla este gate.
9. `infra-prod` se desplego en el pipeline `#2770049730`. Validar ahora el
   rollout, las URLs externas y el issuer del discovery OIDC de Keycloak antes
   de iniciar el siguiente pipeline.
   La repeticion sobre `77e189ef` confirmo el rollout y las dos URLs. El intento
   siguiente, `3c99a48e`, reprodujo las cabeceras del proxy y observo el issuer
   `https://localhost/auth/realms/TrustNews`. El valor procede del atributo
   persistido `frontendUrl` del realm y prevalece sobre el ConfigMap.
   El gate autentica ahora `kcadm` dentro del pod, actualiza unicamente
   `attributes.frontendUrl=https://assermetry.com/auth`, elimina su fichero de
   sesion temporal y exige despues el issuer definitivo. La operacion es
   idempotente y no modifica clientes ni secretos. Si se decide rollback antes
   de desplegar APIs, usar el mismo procedimiento administrativo para restaurar
   `attributes.frontendUrl=https://localhost/auth` y comprobar discovery; no
   cambiar el firewall.
   El job posterior sobre `dc81ca9` completo la migracion y observo el issuer
   `https://assermetry.com/auth/realms/TrustNews`; `infra-prod` queda aceptado.
   El 2026-08-19 se aplico y verifico mediante `kcadm` sobre `TrustNewsWeb`:
   `rootUrl=https://assermetry.com`, `baseUrl=https://assermetry.com/`,
   redirects y post-logout `https://assermetry.com/*`, y Web Origin
   `https://assermetry.com`. El rollback anterior quedo documentado y
   `TrustNewsApi` conservo su configuracion confidencial y su service account
   sin cambios.

##### Cierre operativo del 2026-08-19: clientes alineados mediante `kcadm`

No se uso la consola administrativa ni se abrio el firewall. Durante el estado
transitorio, la consola cargada como `https://localhost:9443` bloqueaba por CSP
los recursos que Keycloak ya generaba para `assermetry.com`, mientras los
Ingress activos todavia esperaban `host: localhost`. La administracion se hizo
con `kcadm` dentro del pod y una sesion temporal eliminada al terminar.

La operacion localizo dinamicamente ambos clientes, capturo los cinco valores
no secretos de rollback de `TrustNewsWeb`, actualizo solo ese cliente y comparo
antes y despues la configuracion no secreta de `TrustNewsApi`.

Estado aceptado:

- Realm name: `TrustNews` (sin cambios).
- Frontend URL: `https://assermetry.com/auth`.
- Display name: `Assermetry`.
- `TrustNewsWeb` Root URL: `https://assermetry.com`.
- `TrustNewsWeb` Home URL: `https://assermetry.com/`.
- Redirect URI: `https://assermetry.com/*`.
- Post logout redirect URI: `https://assermetry.com/*`.
- Web Origin: `https://assermetry.com`.
- `TrustNewsApi`: habilitado, confidencial mediante `client-secret` y con
  service account activa; no se consulto ni modifico el secret.

Rollback capturado para `TrustNewsWeb`:

```text
Root URL:                       https://localhost:9443
Home URL:                       vacio
Valid redirect URIs:            https://localhost:9443/*
Valid post logout redirect URIs:ausente
Web Origins:                    *
```

La sesion temporal de `kcadm` se elimino. El discovery se consulto mediante
port-forward al Service de Keycloak, emulando `Host`, `X-Forwarded-Host` y
`X-Forwarded-Proto`, y devolvio el issuer exacto
`https://assermetry.com/auth/realms/TrustNews`.

La consulta abreviada `--fields realm,displayName,attributes` puede mostrar
`attributes` vacio aunque el mapa este persistido. Para comprobar
`frontendUrl` se debe consultar la representacion completa del realm.

El segundo despliegue con `PROFILE=apis-frontend-prod` ya fue aplicado. La
evidencia aportada muestra 29 de 29 pods preparados, cero reinicios, nueve PVC
`Bound` y los tres Ingress en `assermetry.com`. La repeticion desde Windows con
la raiz Origin CA y sin `-k` obtuvo frontend `200` y los endpoints OIDC
definitivos. Gateway sin credenciales devolvio `403`; OpenAPI, Redoc y Swagger
devolvieron `404`. El nodo estaba al 5% de CPU y 74% de memoria una hora
despues del rollout, sin pods `Pending` ni reinicios.

10. **Aplicado; Fase 6 cerrada:**
    `PROFILE=apis-frontend-prod` desplego
    Gateway, APIs, frontend e Ingress. Registrar el identificador del pipeline
    cuando este disponible y no repetir `infra-prod` ni `blockchain-prod`.
11. Mantener `80/tcp` cerrado y abrir `443/tcp` exclusivamente a los rangos de
    Cloudflare cuando Access mTLS, WAF, TLS, DNS e issuer esten verificados.
12. Verificar:

```bash
kubectl get ingress -A
kubectl get secret trustnews-origin-tls -n kube-system
kubectl get tlsstore default -n kube-system \
  -o jsonpath='{.spec.defaultCertificate.secretName}{"\n"}'
curl -I https://assermetry.com/
test "$(curl -sS -o /dev/null -w '%{http_code}' https://assermetry.com/backend/docs)" = 404
curl -I https://assermetry.com/auth/realms/TrustNews/.well-known/openid-configuration
```

13. **Completado parcialmente:** frontend y discovery pasaron sin `-k`;
    Gateway sin credenciales devolvio `403`; los tres endpoints OpenAPI
    devolvieron `404`; recursos, pods y reinicios quedaron dentro del gate.
14. **Completado:** Keycloak emitio un token `client_credentials` para
    `TrustNewsApi` y Gateway acepto el JWT. `GET /backend/orders/list` devolvio
    `404` desde `news-handler` porque no habia noticias para el `client_id` del
    service account; no fue un rechazo de autenticacion. Con un token nuevo,
    `GET /backend/auth/is-admin` devolvio `HTTP 200` e `is_admin:false`. El
    primer `403` de esta ruta uso una variable de token vacia y se descarta como
    fallo del cliente. No se registraron el secret ni el token.
15. **Completado por confirmacion del operador:** acceso privado de navegador,
    login, refresh, logout, redirects, Web Origins y smoke tests Light y
    Blockchain hasta el punto 6 del procedimiento. Los identificadores y datos
    funcionales no se registran en Git.
16. **Limpieza completada; `ISSUE-002` resuelto:** se retiraron la entrada
    temporal de `hosts`, la raiz Origin CA importada, el tunel SSH y las
    variables. El operador confirmo que el secret de `ISSUE-002` no coincide con produccion;
    no rotar `TrustNewsApi` por este hallazgo. El valor por defecto no vacio se
    elimino. Revisar su posible alcance historico en tests queda como
    recomendacion no bloqueante y la Fase 7 puede comenzar.

No abrir el servicio a clientes hasta que el issuer de Keycloak, el certificado
TLS, las redirecciones OIDC y el WAF esten verificados con el dominio final.

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

Probar entrada HTTPS mediante Traefik:

```bash
kubectl get ingress -A
kubectl get svc -n kube-system traefik
kubectl get secret trustnews-origin-tls -n kube-system
```

Si se esta en modo tunel, abrir el tunel de la seccion 2.7.1 y validar:

```text
https://localhost:9443/
https://localhost:9443/backend/docs -> 404 esperado
https://localhost:9443/auth/admin/master/console/
```

Si ya se abrio el despliegue publico con dominio, validar usando el dominio
final:

```text
https://assermetry.com/
https://assermetry.com/backend/docs -> 404 esperado
https://assermetry.com/auth/admin/master/console/
```

Si solo se quiere comprobar que los estaticos del frontend responden, se puede abrir un port-forward interno, pero no valida Gateway ni Keycloak porque esas rutas ya no las proxifica Nginx:

```bash
kubectl port-forward service/frontend-service -n frontend 10080:80
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
- Traefik esta activo y los Ingress de `frontend`, `apis` e `infra` aparecen en `kubectl get ingress -A`.
- Antes del modo publico, `trustnews-origin-tls` contiene un certificado
  Cloudflare Origin CA vigente cuyo SAN incluye `assermetry.com`.
- `TLSStore/default` referencia `trustnews-origin-tls` y la cadena se valida por
  tunel con SNI y la raiz Origin CA correspondiente.
- En modo tunel, HTTPS responde en `https://localhost:9443` y Keycloak/Gateway mantienen el issuer temporal de localhost.
- En modo publico, WAF esta instalado, `80/tcp` y `443/tcp` estan abiertos solo hacia el borde HTTP, y `host`, certificado definitivo, `KC_HOSTNAME_URL` y variables de issuer del Gateway estan alineados segun la seccion 2.7.
- `CONTRACT_ADDRESS` en overlays prod coincide con el contrato desplegado.
- `initCategories.js` se ha ejecutado y la segunda ejecucion no cambia nada.
- `scripts/k8s/init-mongodb-server.sh` se ha ejecutado despues de levantar MongoDB.
- El pipeline GitLab usa `PROFILE=apis-frontend-prod` para actualizaciones normales.
