# Assermetry Kubernetes - Despliegue server/Hetzner

Runbook operativo del entorno Hetzner. Este documento contiene únicamente:

- la fotografía técnica vigente;
- procedimientos repetibles de despliegue, verificación y recuperación;
- los próximos pasos que todavía no se han ejecutado.

El estado de la versión actual está en [`version.md`](../version.md), el roadmap
en [`next_releases.md`](../next_releases.md), la evidencia de versiones cerradas
en [`releases.md`](../releases.md) y las incidencias en
[`issues.md`](../issues.md). Los procedimientos compartidos con local están en
[`k8s-common.md`](k8s-common.md).

No registrar aquí cronologías de pruebas, intentos de pipeline, identificadores,
direcciones IP, huellas, tokens, certificados ni datos personales.

---

## 1. Fotografía actual

### 1.1 Plataforma y perfiles

| Ámbito | Estado vigente |
| --- | --- |
| Plataforma | K3s en un único nodo de Hetzner |
| Dominio | `https://assermetry.com`, proxificado por Cloudflare |
| Ingress | Traefik sobre `websecure` |
| TLS de origen | Cloudflare Origin CA en `kube-system/trustnews-origin-tls` |
| Identidad | Keycloak, realm `TrustNews` y display name `Assermetry` |
| Issuer | `https://assermetry.com/auth/realms/TrustNews` |
| Perfiles | `setup`, `traefik-prod`, `infra-prod`, `blockchain-prod` y `apis-frontend-prod` |
| Overlays productivos | Keycloak, Gateway e Ingress usan `prod-domain` |
| Entrada al origen | `TCP/443` solo desde las redes verificadas de Cloudflare |
| Puertos cerrados | `80/tcp`, `6443/tcp` y el resto de puertos públicos de aplicación |

Contrato público:

```text
https://assermetry.com/          -> frontend
https://assermetry.com/backend   -> Gateway
https://assermetry.com/auth      -> Keycloak
```

Los servicios internos, bases de datos, Kafka, IPFS, RPC, paneles y APIs
administrativas permanecen como `ClusterIP`, sin Ingress ni NodePort.

### 1.2 Cloudflare

Las cinco reglas personalizadas están ocupadas y conservan este orden:

| Orden | Regla | Estado operativo |
| ---: | --- | --- |
| 1 | `Maintenance lock - assermetry.com` | Selectivo; comprobarlo antes de cada ventana |
| 2 | `Permanent mTLS - Keycloak administration` | Activa y permanente |
| 3 | `Temporary mTLS gate - assermetry.com` | Activa hasta `v0.0.14` |
| 4 | `Permanent block - non-public resources` | Activa |
| 5 | `Permanent block - unexpected backend methods` | Activa |

El lock existe y puede bloquear todo el hostname. Su estado no se presupone:
el operador lo habilita o deshabilita deliberadamente según la ventana de
trabajo. Su estado observado actual es deshabilitado. Antes de cambiarlo se
confirma el estado deseado y, al terminar, se deja registrado en la evidencia
operativa, no en este runbook.

La Free Managed Ruleset está habilitada. La única regla de rate limiting,
`Expensive backend operations per IP`, protege las operaciones costosas del
Gateway con el umbral operativo de 5 peticiones por 10 segundos y mitigación de
10 segundos. Login, refresh y polling no forman parte de esa regla.

La asociación mTLS del hostname se conserva. Mientras la regla temporal siga
activa:

- una ruta administrativa sin certificado coincide con la regla permanente;
- una ruta no administrativa sin certificado coincide con la regla temporal;
- un certificado válido permite continuar hasta los controles posteriores;
- un certificado revocado debe ser rechazado.

En `v0.0.14` se retirará únicamente la regla temporal. No se desasocia mTLS del
hostname ni se elimina la regla administrativa.

### 1.3 Traefik, observabilidad y línea base

Traefik se instala mediante el perfil `traefik-prod`, fija el chart `41.0.2` y
usa:

- `externalTrafficPolicy: Local`;
- `forwardedHeaders.insecure: false`;
- las redes oficiales de Cloudflare en `websecure.forwardedHeaders.trustedIPs`;
- access logs JSON sin cabeceras ni parámetros de consulta;
- upgrades Helm con `--atomic`.

Loki y Grafana usan PVC persistentes, probes y conservaron datos y datasource
después del reemplazo de sus pods. Fluent Bit incluye `kube-system` para
recoger los logs de Traefik.

La última medición operativa disponible está resumida en
[`version.md`](../version.md): 29 pods preparados, cero reinicios, nueve PVC
`Bound` y nodo `Ready`. Todavía no es la línea base estable de cierre de la
Fase 7. La memoria cercana al 80 % y `DNSConfigForming` siguen bajo
observación; no deben convertirse en cifras permanentes dentro de este
runbook.

---

## 2. Accesos y variables

El servidor debe disponer de:

- K3s y `kubectl` funcionales;
- Skaffold;
- acceso SSH por `2222/tcp` con clave para el usuario de despliegue;
- GitLab Runner con tag `hetzner-runner`;
- Docker para el job de build;
- pull secret del GitLab Registry en los namespaces necesarios.

Variables CI/CD protegidas y enmascaradas:

```dotenv
HETZNER_IP=<ip-publica-hetzner>
HETZNER_USER=<usuario-ssh>
HETZNER_SSH_KEY_B64=<private-key-ssh-en-base64>
KUBECONFIG_DATA=<kubeconfig-en-base64>
PROFILE=apis-frontend-prod
```

`CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER` y
`CI_REGISTRY_PASSWORD` los aporta GitLab.

La rama `postTFM` debe estar protegida cuando las variables de despliegue sean
`Protected`. El scope de las variables debe coincidir con el environment del
job.

El job de despliegue abre un túnel local
`127.0.0.1:6443 -> Hetzner:127.0.0.1:6443` y fuerza el endpoint del kubeconfig
a `https://127.0.0.1:6443`. Este túnel es para el API de K3s y no cambia el
issuer público de la aplicación.

---

## 3. Secrets productivos

Los ficheros `.env` y el material criptográfico se mantienen fuera del
repositorio.

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

Aplicación:

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

`MONGO_APP_USER` y `MONGO_APP_PWD` deben coincidir con el usuario creado por el
bootstrap de MongoDB. Después de levantar MongoDB se ejecuta el procedimiento
idempotente de [`k8s-common.md`](k8s-common.md#6-mongodb-bootstrap).

### 3.3 Pull secret

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

## 4. Dominio, Traefik y TLS

### 4.1 Configuración declarativa vigente

`infra-prod` usa `k8s/infra/keycloak/overlays/prod-domain`.
`apis-frontend-prod` usa:

- `k8s/apis/gateway/overlays/prod-domain`;
- `k8s/ingress/overlays/prod-domain`.

Los tres Ingress usan `host: assermetry.com` y `websecure`. El frontend sirve
HTTP dentro del clúster; Traefik termina TLS y enruta `/`, `/backend` y
`/auth`.

No desplegar overlays `local` o `prod` con issuer `localhost` sobre Hetzner.

### 4.2 Origin CA

El fichero privado `tls-origin.env` referencia el material, no contiene PEM:

```dotenv
TLS_CERT_FILE=/home/sysadmin/trustnews-origin-ca/assermetry-origin.pem
TLS_KEY_FILE=/home/sysadmin/trustnews-origin-ca/assermetry-origin.key
TLS_CA_FILE=/home/sysadmin/trustnews-origin-ca/cloudflare-origin-ca-rsa-root.pem
```

Antes de aplicar:

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

Las dos huellas deben coincidir y `TLSStore/default` debe devolver
`trustnews-origin-tls`. Conservar el material anterior validado para rollback.
La revocación en Cloudflare solo se realiza después de recuperar el servicio o
si existe pérdida o compromiso de la clave.

### 4.3 Diagnóstico por túnel

El túnel es una herramienta de diagnóstico. No restaura el antiguo issuer de
`localhost`.

```bash
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 9443:127.0.0.1:9443 \
  <usuario>@<hetzner-ip> \
  -t "kubectl port-forward --address 127.0.0.1 \
      -n kube-system svc/traefik 9443:443"
```

Validar SNI, hostname y cadena:

```bash
openssl s_client \
  -connect 127.0.0.1:9443 \
  -servername assermetry.com \
  -verify_hostname assermetry.com \
  -CAfile origin_ca_rsa_root.pem \
  -verify_return_error </dev/null
```

Para peticiones HTTP se preserva el hostname canónico:

```bash
curl --resolve assermetry.com:9443:127.0.0.1 \
  --cacert origin_ca_rsa_root.pem \
  https://assermetry.com:9443/
```

El discovery debe seguir publicando:

```text
https://assermetry.com/auth/realms/TrustNews
```

---

## 5. Cloudflare y firewall

### 5.1 Comprobación previa

Antes de una ventana operativa:

1. Confirmar el estado deliberado del lock.
2. Confirmar que las cinco reglas conservan el orden documentado.
3. Confirmar que la regla mTLS administrativa y la temporal están activas.
4. Confirmar que la Free Managed Ruleset y el rate limit están activos.
5. Revisar Security Events sin copiar IP, Ray ID, Rule ID ni datos sensibles.
6. Confirmar en Hetzner que `443/tcp` solo admite Cloudflare y que `80/tcp` y
   `6443/tcp` siguen cerrados.

No hay slots libres de reglas personalizadas en el plan actual.

### 5.2 Comportamiento esperado del lock

Con el lock habilitado, todo `assermetry.com` queda bloqueado incluso para un
usuario o administrador con certificado válido.

Con el lock deshabilitado:

- `/` y las rutas no administrativas exigen el certificado temporal;
- las rutas administrativas se atribuyen a la regla mTLS permanente;
- los recursos no públicos y métodos inesperados siguen bloqueados;
- Gateway exige JWT en las rutas protegidas.

El cambio de estado del lock no altera DNS, TLS, mTLS, firewall, Keycloak ni
Kubernetes.

### 5.3 Reglas permanentes

La regla administrativa cubre:

```text
/auth/admin
/auth/admin/*
/auth/realms/master
/auth/realms/master/*
```

La regla de recursos no públicos bloquea, como mínimo, OpenAPI, Swagger, Redoc
y rutas `.git` del hostname público.

La regla de métodos del Gateway permite únicamente `GET`, `HEAD`, `POST` y
`OPTIONS` bajo `/backend`.

El límite de cuerpo es 5 MiB tanto en Traefik como en Gateway.

---

## 6. Despliegue

### 6.1 Perfiles productivos

| Perfil | Alcance |
| --- | --- |
| `setup` | Namespaces |
| `traefik-prod` | Traefik productivo |
| `infra-prod` | MongoDB, Kafka, IPFS, Keycloak y observabilidad |
| `blockchain-prod` | Red privada Geth |
| `apis-frontend-prod` | APIs, Gateway, frontend e Ingress del dominio |

No existe `infra-basic` en producción.

### 6.2 Instalación o reconstrucción controlada

Orden:

1. Aplicar `setup`.
2. Crear Secrets y pull secrets.
3. Instalar `traefik-prod`.
4. Desplegar `infra-prod` y ejecutar el bootstrap de MongoDB.
5. Desplegar `blockchain-prod`.
6. Verificar contrato y categorías.
7. Desplegar `apis-frontend-prod`.
8. Ejecutar la verificación completa.

Pipelines manuales:

```dotenv
PROFILE=traefik-prod
PROFILE=infra-prod
PROFILE=blockchain-prod
PROFILE=apis-frontend-prod
```

No combinar perfiles en una única ventana si se está diagnosticando un fallo.

### 6.3 Contrato

Si se conserva el contrato actual, verificar que existe bytecode:

```bash
export CONTRACT_ADDRESS=0x<direccion-trust-news>
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- \
  geth attach --exec "eth.getCode('$CONTRACT_ADDRESS')"
```

Si cambia el contrato, actualizar `CONTRACT_ADDRESS` en todos los overlays
productivos consumidores antes de desplegar las APIs y regenerar el ABI cuando
corresponda.

### 6.4 Actualización normal

```bash
git checkout postTFM
git fetch origin main
git merge origin/main
git status --short
git push gitlab postTFM
```

En GitLab se ejecuta el pipeline sobre `postTFM` con el perfil que corresponda
al componente cambiado. Para una actualización normal de aplicación:

```dotenv
PROFILE=apis-frontend-prod
```

El despliegue usa:

```bash
skaffold deploy --build-artifacts=build.json --profile="$PROFILE"
```

No usar `kubectl apply`, `helm upgrade` ni parches manuales como sustituto del
pipeline salvo en un procedimiento explícito de recuperación.

### 6.5 Alineación idempotente de Keycloak

El job `deploy` de GitLab ejecuta automáticamente la alineación después del
rollout de `infra-prod`. El script compartido actualiza `frontendUrl` del realm
`TrustNews` y las URLs, redirects, post-logout y Web Origins de
`TrustNewsWeb`; después lee los campos y exige que coincidan exactamente con el
contrato productivo. No crea clientes, no modifica `TrustNewsApi`, sus secretos,
usuarios ni roles, y no muestra credenciales.

No ejecutar un segundo paso manual después de un pipeline correcto. Si el job
falla o se necesita recuperar una configuración modificada fuera del pipeline,
ejecutar desde la raíz del repositorio, con `kubectl` y `python3` disponibles:

```bash
./scripts/k8s/infra/reconcile-keycloak-web-prod.sh
```

El script termina con `keycloak_web_alignment=PASS` únicamente tras validar el
estado leído de Keycloak. Si `TrustNewsWeb` no existe exactamente una vez, falla
antes de modificar el realm o el cliente. Repetirlo conserva el mismo resultado.

---

## 7. Verificación vigente

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

No deben aparecer servicios internos con Ingress, NodePort o LoadBalancer. El
único borde web es Traefik.

### 7.2 Dominio

Antes de probar se comprueba el estado del lock. Si está habilitado, el `403`
general es el resultado esperado.

Con el lock deshabilitado y un certificado temporal válido:

- frontend y discovery responden;
- el issuer es exactamente el canónico;
- login, refresh y logout funcionan;
- Gateway rechaza sin JWT y acepta un JWT válido;
- Light y Blockchain completan sus flujos;
- `/backend/docs`, Swagger, Redoc y OpenAPI devuelven `404` o son bloqueados en
  el borde;
- las rutas administrativas requieren certificado y autenticación de Keycloak.

Desde una red externa debe comprobarse también que la IP directa del origen y
los puertos `80` y `6443` no permiten acceso.

### 7.3 Observabilidad

```bash
kubectl get pvc loki-data grafana-data -n infra
kubectl get pods -n infra
kubectl top nodes
kubectl top pods -A
```

La persistencia de Loki puede verificarse sin imprimir logs crudos:

```bash
./scripts/k8s/infra/verify-loki-persistence.sh --execute
```

Para Grafana se usa un port-forward transportado por SSH; no se publica el
Service. Revisar errores y rechazos en Loki/Grafana sin exportar tokens,
cabeceras, cuerpos, IP ni identificadores de Cloudflare.

---

## 8. Operación y recuperación

Rollback de aplicación:

```bash
kubectl rollout undo deployment/gateway -n apis
kubectl rollout undo deployment/news-handler -n apis
kubectl rollout undo deployment/evidence-search -n apis
kubectl rollout undo deployment/frontend-web -n frontend
kubectl rollout status deployment/gateway -n apis --timeout=180s
```

Para un rollback TLS se reaplica el Secret con el material anterior validado y
se repiten las comprobaciones de `TLSStore`, cadena, SNI y hostname.

La eliminación de PVC solo pertenece a una reconstrucción completa,
explícitamente autorizada y con el tratamiento de datos decidido. No se usa
como reparación rutinaria:

```bash
kubectl get pvc -n infra
kubectl get pvc -n blockchain
```

Las restauraciones destructivas sobre PVC activos están prohibidas. Los backups
y la restauración aislada completa pertenecen a `v0.0.16`.

---

## 9. Próximos pasos

### 9.1 Cierre de v0.0.12

- Ejecutar `infra-prod`, obtener `keycloak_web_alignment=PASS` en la
  reconciliación de `TrustNewsWeb` y volver a validar el issuer OIDC.
- Confirmar la convivencia del lock, el mTLS temporal y el mTLS
  administrativo.
- Validar desde otra red con certificado temporal frontend, OIDC, Light y
  Blockchain.
- Verificar Gateway con y sin JWT.
- Verificar la atribución y el acceso de las rutas administrativas.
- Revocar un certificado administrativo desechable y demostrar su rechazo.
- Probar que el lock bloquea todo el hostname y dejarlo en el estado operativo
  decidido.
- Registrar la línea base estable.

### 9.2 v0.0.13

- Ejecutar la regresión reproducible de GUI y API con datos sintéticos.
- Mantener activa la regla mTLS general temporal durante toda la versión.
- Validar `aud` y `azp` o `client_id` antes de admitir evaluadores externos.
- Resolver `ISSUE-001` y superar sus pruebas de concurrencia sin refresco
  manual de la caché de validadores LIGHT.
- Ejecutar las demos desde ventanas controladas por el lock.

### 9.3 v0.0.14

- Habilitar el lock durante la ventana de cambio.
- Retirar únicamente `Temporary mTLS gate - assermetry.com`.
- Mantener la asociación mTLS y la regla administrativa permanente.
- Validar OIDC de usuario sin certificado, administración con certificado,
  WAF, rate limit, logs y rollback.
- Abrir la beta solo después de superar esas comprobaciones.

Los pasos posteriores se mantienen exclusivamente en
[`next_releases.md`](../next_releases.md) hasta que su versión pase a estar en
curso.
