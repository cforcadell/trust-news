# Working plan - Despliegue de `/gui`, validación y cierre de la frontera pública

Documento de trabajo temporal para desplegar y validar el cambio primero en
Kind, después en Hetzner y finalmente en Cloudflare. No sustituye a los runbooks
permanentes:

- [`deploy/skaffold-local.md`](deploy/skaffold-local.md);
- [`deploy/skaffold-server.md`](deploy/skaffold-server.md);
- [`deploy/k8s-common.md`](deploy/k8s-common.md).

Cuando todos los criterios de salida estén cumplidos, el resultado verificado
se incorporará a [`version.md`](version.md) siguiendo la sección final de este
documento. Mientras quede una casilla obligatoria sin completar, este cambio no
se considera cerrado ni debe abrirse el acceso general.

---

## 1. Objetivo y alcance

El cambio establece este contrato público:

```text
https://assermetry.com/          -> 302 de Cloudflare a /gui/
https://assermetry.com/gui       -> 302 de Cloudflare a /gui/
https://assermetry.com/gui/      -> frontend
https://assermetry.com/backend   -> Gateway
https://assermetry.com/auth      -> Keycloak
```

La aplicación deja de tener un Ingress catch-all en `/`. Traefik solo publica
el frontend bajo `/gui`, elimina ese prefijo antes de entregar la petición a
nginx y usa coincidencia estricta de prefijos. Cloudflare bloquea por defecto
cualquier path que no pertenezca a `/gui/`, `/backend` o `/auth`.

También se valida el comportamiento frontend ya implementado:

- modo LIGHT por defecto;
- checkbox desmarcado con el texto `Auditar y trazabilidad con Blockchain`;
- checkbox marcado equivale a `validation_mode=BLOCKCHAIN`;
- tooltip descriptivo sobre IPFS y blockchain;
- generación de aserciones con progreso, timeout, error y reintento;
- polling de verificación con timeout, errores consecutivos y reintento.

No se cambia la lógica funcional, los payloads ni los contratos de las APIs.

### 1.1 Fuera de alcance

- No cambiar endpoints internos ni nombres de servicios.
- No publicar Swagger, OpenAPI, Grafana, Kafka, MongoDB, IPFS o RPC.
- No retirar el mTLS permanente de administración de Keycloak.
- No modificar usuarios, roles, secretos ni service accounts de Keycloak.
- No reconstruir Kind ni borrar PVC como parte de una actualización normal.
- No convertir los redirects a `301` hasta terminar el periodo de observación.

---

## 2. Estado declarativo que se va a desplegar

Antes de comenzar, confirmar que el árbol de trabajo contiene:

- `k8s/ingress/base/frontend-ingress.yaml` con `path: /gui`;
- `k8s/ingress/base/frontend-middleware.yaml` con `stripPrefix: /gui`;
- los overlays `local`, `prod` y `prod-domain` con `/gui`;
- `k8s/traefik/values.yaml` con `strictPrefixMatching: true`;
- `web_classic/app/index.html` con `<base href="/gui/">`;
- logout del frontend hacia `/gui/`;
- reconciliación de `TrustNewsWeb` bajo `/gui`;
- verificaciones productivas correspondientes en `.gitlab-ci.yml`.

Comprobación:

```bash
git status --short
git diff --check
node --check web_classic/app/js/app.js
node --check web_classic/app/js/i18n.js
bash -n scripts/k8s/infra/reconcile-keycloak-web-prod.sh

rg -n 'path: /gui|frontend-strip-gui' k8s/ingress
rg -n 'strictPrefixMatching: true' k8s/traefik/values.yaml
rg -n 'base href="/gui/"' web_classic/app/index.html
```

No limpiar ni descartar cambios ajenos del árbol de trabajo.

---

## 3. Registro de la ejecución

Completar sin copiar secretos, tokens, claves privadas, cookies, IP de origen,
Ray IDs o cuerpos de noticias reales.

| Campo | Valor |
| --- | --- |
| Fecha de inicio | Pendiente |
| Operador | Pendiente |
| Rama | Pendiente |
| Commit probado en Kind | Pendiente |
| Commit desplegado en Hetzner | Pendiente |
| Pipeline `traefik-prod` | Pendiente |
| Pipeline `apis-frontend-prod` | Pendiente |
| Estado inicial del maintenance lock | Pendiente |
| Estado inicial de la regla mTLS temporal | Pendiente |
| Resultado final | Pendiente |

Para cada fase registrar únicamente:

- `PASS` o `FAIL`;
- timestamp;
- comando o caso ejecutado;
- código HTTP o estado Kubernetes esperado/observado;
- referencia interna a la evidencia sanitizada.

Ante un `FAIL`, detener el avance hacia la siguiente capa. No compensar un
fallo local haciendo cambios manuales directamente en producción.

---

# Parte I - Validación local en Kind

## 4. Preflight local

### 4.1 Confirmar contexto y salud de Kind

```bash
kubectl config current-context
kind get clusters
kubectl get nodes -o wide
kubectl get pods -A
```

Resultado requerido:

- contexto `kind-trust-news`;
- clúster `trust-news` disponible;
- los tres nodos en `Ready`;
- ningún pod esencial en `CrashLoopBackOff`, `ImagePullBackOff` o `Pending` sin
  explicación conocida.

Si el contexto no coincide, detenerse. No aplicar manifests sobre otro
clúster.

### 4.2 Confirmar herramientas

```bash
./skaffold version
kubectl version --client
kind version
helm version --short
docker version
```

Bloqueo conocido: el Helm instalado mediante Snap puede negarse a arrancar por
`snap-confine/AppArmor`. `helm version --short` debe funcionar antes de ejecutar
`./skaffold deploy -p traefik`. Corregir la instalación de Helm o AppArmor de
forma explícita; no sustituir el despliegue declarativo por un parche manual al
Deployment de Traefik.

### 4.3 Capturar estado no sensible

```bash
kubectl get deployment -A
kubectl get ingress -A
kubectl get middleware -A
kubectl get pvc -A
kubectl get svc -A
```

No reconstruir el clúster por estar vacío. El estado observado antes de este
plan tenía únicamente Traefik y los componentes base de Kind, sin Ingress ni
aplicación desplegada.

---

## 5. Validación estática local

### 5.1 Resolver perfiles Skaffold

```bash
./skaffold diagnose --yaml-only -p traefik >/tmp/assermetry-traefik.yaml
./skaffold diagnose --yaml-only -p blockchain >/tmp/assermetry-blockchain.yaml
./skaffold diagnose --yaml-only -p infra >/tmp/assermetry-infra.yaml
./skaffold diagnose --yaml-only -p apis-frontend >/tmp/assermetry-app.yaml
```

Todos los comandos deben terminar con código `0`.

### 5.2 Renderizar el Ingress local

```bash
kubectl kustomize --load-restrictor=LoadRestrictionsNone \
  k8s/ingress/overlays/local >/tmp/assermetry-ingress-local.yaml

rg -n 'host: localhost|path: /gui|path: /backend|path: /auth' \
  /tmp/assermetry-ingress-local.yaml
rg -n 'frontend-frontend-strip-gui@kubernetescrd|prefixes:' \
  /tmp/assermetry-ingress-local.yaml
```

Revisar que:

- no exista `path: /` para el frontend;
- `/gui` apunte a `frontend-service`;
- `/backend` apunte a `gateway`;
- `/auth` apunte a Keycloak;
- el Ingress del frontend referencie
  `frontend-frontend-strip-gui@kubernetescrd`;
- el middleware elimine `/gui`.

---

## 6. Despliegue local

Los perfiles `blockchain`, `infra` y `apis-frontend` ejecutados con `dev` son
procesos de larga duración. Abrir una terminal distinta para cada uno y no
cerrarla durante la prueba.

### 6.1 Namespaces

```bash
cd scripts/k8s
./create-namespaces.sh
cd ../..

kubectl get ns blockchain infra apis frontend
```

### 6.2 Traefik

```bash
./skaffold deploy -p traefik
kubectl rollout status deployment/traefik -n kube-system --timeout=180s
```

Confirmar la nueva opción:

```bash
kubectl get deployment traefik -n kube-system \
  -o jsonpath='{.spec.template.spec.containers[0].args}' |
  tr ',' '\n' |
  rg -- '--providers.kubernetesingress.strictprefixmatching=true'
```

Si no aparece, detener el plan. No desplegar el nuevo Ingress con un Traefik
que todavía use coincidencia de prefijo no estricta.

### 6.3 Blockchain

Terminal 1:

```bash
./skaffold dev -p blockchain --namespace blockchain
```

En otra terminal:

```bash
kubectl get pods -n blockchain
kubectl wait --for=condition=Ready pod --all -n blockchain --timeout=300s
```

Si el contrato no está desplegado o la dirección configurada no contiene
bytecode, seguir el procedimiento de contrato de
[`deploy/skaffold-local.md`](deploy/skaffold-local.md#4-blockchain-y-contrato).

### 6.4 Infraestructura

Elegir solo una opción. Para esta regresión se recomienda `infra`, porque se
necesitan logs y Grafana.

Terminal 2:

```bash
./skaffold dev -p infra
```

Comprobar:

```bash
kubectl get pods -n infra
kubectl wait --for=condition=Ready pod --all -n infra --timeout=600s
```

Ejecutar después el bootstrap de MongoDB y la configuración compartida de
[`deploy/k8s-common.md`](deploy/k8s-common.md). No ejecutar simultáneamente
`infra` e `infra-basic`.

### 6.5 APIs, frontend e Ingress

Terminal 3:

```bash
./skaffold dev -p apis-frontend
```

Comprobar:

```bash
kubectl rollout status deployment -n apis --timeout=300s
kubectl rollout status deployment/frontend-web -n frontend --timeout=180s
kubectl get ingress -A
kubectl get middleware -A
```

Validar el contrato desplegado:

```bash
test "$(kubectl get ingress frontend-ingress -n frontend \
  -o jsonpath='{.spec.rules[0].http.paths[0].path}')" = "/gui"

test "$(kubectl get ingress frontend-ingress -n frontend \
  -o jsonpath='{.metadata.annotations.traefik\.ingress\.kubernetes\.io/router\.middlewares}')" \
  = "frontend-frontend-strip-gui@kubernetescrd"

test "$(kubectl get middleware frontend-strip-gui -n frontend \
  -o jsonpath='{.spec.stripPrefix.prefixes[0]}')" = "/gui"
```

### 6.6 Alinear Keycloak local

```bash
KEYCLOAK_URL=https://localhost:7443/auth \
FRONTEND_URL=https://localhost:7443/gui \
WEB_ORIGIN=https://localhost:7443 \
./scripts/k8s/infra/reconcile-keycloak-web-prod.sh
```

Resultado requerido:

```text
keycloak_web_alignment=PASS
```

El contrato esperado es:

```text
Root URL:              https://localhost:7443/gui
Home URL:              https://localhost:7443/gui/
Valid Redirect URIs:   https://localhost:7443/gui/*
Post Logout Redirects: https://localhost:7443/gui/*
Web Origins:           https://localhost:7443
```

---

## 7. Pruebas locales

### 7.1 Abrir Traefik

```bash
kubectl port-forward --address 127.0.0.1 \
  -n kube-system svc/traefik 7443:443
```

Si se accede desde el host de una VM, usar el túnel privado descrito en el
runbook local. Conservar siempre el hostname `localhost` para OIDC.

### 7.2 Frontera de rutas

```bash
curl --fail --show-error --cacert web_classic/certs/fullchain.pem \
  -o /dev/null https://localhost:7443/gui/

curl --fail --show-error --cacert web_classic/certs/fullchain.pem \
  -o /dev/null https://localhost:7443/gui/css/style.css

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cacert web_classic/certs/fullchain.pem https://localhost:7443/)" = "404"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cacert web_classic/certs/fullchain.pem \
  https://localhost:7443/gui-malicious)" = "404"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cacert web_classic/certs/fullchain.pem \
  https://localhost:7443/backend-malicious)" = "404"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cacert web_classic/certs/fullchain.pem \
  https://localhost:7443/auth-malicious)" = "404"
```

Kind no reproduce los redirects ni el WAF de Cloudflare. Por eso `/` debe ser
`404`, no `302`, y los paths desconocidos deben quedar sin router.

### 7.3 OIDC

Comprobar discovery:

```bash
curl --fail --show-error --cacert web_classic/certs/fullchain.pem \
  https://localhost:7443/auth/realms/TrustNews/.well-known/openid-configuration \
  -o /tmp/assermetry-local-discovery.json

python3 -m json.tool /tmp/assermetry-local-discovery.json >/dev/null
```

En navegador:

- [ ] abrir directamente `https://localhost:7443/gui/`;
- [ ] iniciar sesión;
- [ ] refrescar la página con sesión activa;
- [ ] esperar o simular refresh de token;
- [ ] cerrar sesión;
- [ ] comprobar que el retorno termina en `/gui/`;
- [ ] comprobar que no aparece un error de `redirect_uri` ni CORS.

### 7.4 Validación frontend y funcional

- [ ] La casilla Blockchain aparece desmarcada al entrar o limpiar el formulario.
- [ ] El texto es exactamente `Auditar y trazabilidad con Blockchain`.
- [ ] Hover y foco muestran el tooltip de IPFS y blockchain.
- [ ] Desmarcada, publicar envía una orden LIGHT.
- [ ] Marcada, publicar envía una orden BLOCKCHAIN.
- [ ] `Generar Aserciones` deshabilita el botón y muestra spinner, etapas y tiempo.
- [ ] Una respuesta correcta muestra el número de aserciones y permite editarlas.
- [ ] Un error HTTP muestra mensaje y botón `Reintentar`.
- [ ] Un fallo de red muestra error de conexión sin borrar el texto.
- [ ] Un timeout de generación aparece al alcanzar 90 segundos.
- [ ] La verificación muestra tiempo transcurrido y actualizaciones periódicas.
- [ ] Tres fallos consecutivos muestran error recuperable.
- [ ] Cinco minutos sin estado terminal muestran timeout y permiten reintentar.
- [ ] LIGHT no intenta presentar trazabilidad blockchain/IPFS inexistente.
- [ ] BLOCKCHAIN completa publicación, IPFS y trazabilidad.
- [ ] Español e inglés muestran textos completos.
- [ ] Chrome, Edge y Firefox no muestran errores relevantes en consola.

Para forzar timeouts o errores usar exclusivamente mecanismos locales y datos
sintéticos. No cambiar la API productiva ni persistir una configuración de
fallo en los manifests.

### 7.5 Logs y recursos

```bash
kubectl get pods -A
kubectl top nodes
kubectl top pods -A
kubectl get events -A --sort-by=.lastTimestamp
```

Revisar Gateway, frontend, Keycloak y workers sin exportar tokens, prompts,
cuerpos completos ni datos personales.

### 7.6 Gate local

No avanzar a Hetzner hasta cumplir todo:

- [ ] manifests y sintaxis válidos;
- [ ] Traefik usa prefijos estrictos;
- [ ] `/gui/` y assets responden;
- [ ] `/`, `/gui-malicious`, `/backend-malicious` y `/auth-malicious` no enrutan;
- [ ] login, refresh y logout funcionan bajo `/gui/`;
- [ ] LIGHT y BLOCKCHAIN completan el flujo;
- [ ] progreso, timeout, error y reintento están validados;
- [ ] no hay defectos P0/P1 ni errores relevantes en logs.

Registrar el commit exacto probado. Hetzner debe desplegar ese mismo commit.

### 7.7 Rollback local

Si falla el cambio:

1. Conservar pods y logs para diagnóstico.
2. Detener únicamente el perfil afectado.
3. Corregir declarativamente y repetir desde la validación estática.
4. Si se necesita volver a una revisión anterior, desplegarla con Skaffold.
5. No borrar PVC, namespaces ni el clúster como reparación rutinaria.

---

# Parte II - Despliegue en Hetzner

## 8. Preflight de producción

### 8.1 Condiciones obligatorias

- [ ] El gate local está completo.
- [ ] El commit probado está enviado a GitLab.
- [ ] Existe una ventana de cambio.
- [ ] Hay acceso administrativo de respaldo a Hetzner, Kubernetes y Cloudflare.
- [ ] Se dispone de certificado cliente administrativo válido y de respaldo.
- [ ] El material TLS de origen anterior está disponible para rollback.
- [ ] Se conoce el estado actual del maintenance lock y de las cinco Custom Rules.
- [ ] No hay una incidencia productiva activa sin relación con este cambio.

### 8.2 Capturar estado de Hetzner

Ejecutar sin imprimir Secrets:

```bash
kubectl config current-context
kubectl get nodes -o wide
kubectl get pods -A
kubectl get deployment -A
kubectl get ingress -A
kubectl get middleware -A
kubectl get pvc -A
kubectl get tlsstore default -n kube-system
kubectl get secret trustnews-origin-tls -n kube-system
```

Guardar las revisiones actuales para rollback:

```bash
kubectl rollout history deployment/traefik -n kube-system
kubectl rollout history deployment/frontend-web -n frontend
kubectl rollout history deployment/gateway -n apis
```

### 8.3 Proteger la ventana con el maintenance lock

En Cloudflare:

1. Seleccionar la cuenta y la zona `assermetry.com`.
2. Abrir `Security` > `Security rules`.
3. Localizar `Maintenance lock - assermetry.com`.
4. Revisar que la expresión afecta únicamente a `assermetry.com` y que la
   acción es `Block`.
5. Activar la regla.
6. Desde una conexión externa confirmar que `/gui/` devuelve `403`.

Antes de crear los nuevos Single Redirects, el lock bloquea el hostname
completo. Después de crearlos, `/` y `/gui` responderán con `302` en una fase
anterior al WAF, aunque `/gui/` siga bloqueado. Si durante la ventana se exige
un `403` absoluto incluso en esos dos paths, mantener los redirects
deshabilitados hasta el momento de abrir el servicio.

No desactivar todavía el mTLS temporal general.

---

## 9. Desplegar primero el origen

La migración cambia Traefik y aplicación. Ejecutar los pipelines manuales en
este orden y no en paralelo.

### 9.1 Traefik productivo

En GitLab, sobre el commit validado:

```dotenv
PROFILE=traefik-prod
```

Esperar a que build, deploy y verificaciones terminen en verde. Después:

```bash
kubectl rollout status deployment/traefik -n kube-system --timeout=180s
kubectl get deployment traefik -n kube-system \
  -o jsonpath='{.spec.template.spec.containers[0].args}' |
  tr ',' '\n' |
  rg -- '--providers.kubernetesingress.strictprefixmatching=true'
```

Si el pipeline falla, no continuar con la aplicación. Helm usa `--atomic`, pero
se debe verificar explícitamente qué revisión quedó activa.

### 9.2 APIs y frontend productivos

Ejecutar después:

```dotenv
PROFILE=apis-frontend-prod
```

Este pipeline debe:

- desplegar las APIs y `frontend-web`;
- aplicar el Ingress `/gui`;
- aplicar y verificar `frontend-strip-gui`;
- esperar los rollouts;
- reconciliar `TrustNewsWeb`;
- terminar con `keycloak_web_alignment=PASS`.

Confirmación manual:

```bash
kubectl rollout status deployment/frontend-web -n frontend --timeout=180s
kubectl rollout status deployment/gateway -n apis --timeout=180s
kubectl get ingress frontend-ingress -n frontend -o yaml
kubectl get middleware frontend-strip-gui -n frontend -o yaml
```

No ejecutar `infra-prod` para este cambio salvo que se esté reconstruyendo la
infraestructura o exista además un cambio explícito en ella.

---

## 10. Validar Hetzner antes de modificar la frontera Cloudflare

La validación se ejecuta desde Windows. Abrir PowerShell y resolver la ruta de
la clave SSH. En una primera terminal, crear el túnel y mantenerla abierta:

```powershell
$SshKey = (Resolve-Path .\id_rsa_hetzner_deploy).Path
$HetznerTarget = "<usuario>@<hetzner-ip>"

ssh.exe -i $SshKey -p 2222 -o ExitOnForwardFailure=yes `
  -L 9443:127.0.0.1:9443 $HetznerTarget -t `
  'sudo k3s kubectl port-forward --address 127.0.0.1 -n kube-system svc/traefik 9443:443'
```

La terminal debe quedar mostrando
`Forwarding from 127.0.0.1:9443 -> 8443`. No usar el puerto local `443`, para
evitar permisos elevados o conflictos en Windows.

En una segunda terminal PowerShell, comprobar primero que el extremo local del
túnel está escuchando. Ejecutar cada bloque completo, no línea por línea:

```powershell
$Tunnel = Test-NetConnection 127.0.0.1 -Port 9443 -WarningAction SilentlyContinue
if ($Tunnel.TcpTestSucceeded) {
  "PASS tunnel 127.0.0.1:9443"
} else {
  throw "FAIL tunnel 127.0.0.1:9443"
}
```

Después, resolver la ruta de `cloudflare-origin-ca-rsa-root.pem` y validar TLS,
hostname, frontend y assets. `curl.exe`, con `--resolve`, `--noproxy` y
`--cacert`, verifica la cadena del certificado y que sea válido para
`assermetry.com`; no usar `-k` ni `--insecure`:

```powershell
$OriginCa = (Resolve-Path .\cloudflare-origin-ca-rsa-root.pem).Path
$Resolve = "assermetry.com:9443:127.0.0.1"

curl.exe --fail --show-error --noproxy assermetry.com `
  --resolve $Resolve --cacert $OriginCa `
  https://assermetry.com:9443/gui/ --output NUL
if ($LASTEXITCODE -eq 0) {
  "PASS /gui/"
} else {
  throw "FAIL /gui/"
}

curl.exe --fail --show-error --noproxy assermetry.com `
  --resolve $Resolve --cacert $OriginCa `
  https://assermetry.com:9443/gui/css/style.css --output NUL
if ($LASTEXITCODE -eq 0) {
  "PASS /gui/css/style.css"
} else {
  throw "FAIL /gui/css/style.css"
}
```

Comprobar que el origen no tiene catch-all:

```powershell
$TestPaths = @("/", "/gui-malicious", "/backend-malicious", "/auth-malicious")

foreach ($TestPath in $TestPaths) {
  $ObservedCode = curl.exe --silent --show-error --output NUL `
    --write-out "%{http_code}" --noproxy assermetry.com `
    --resolve $Resolve --cacert $OriginCa `
    "https://assermetry.com:9443$TestPath"
  if ($LASTEXITCODE -ne 0 -or $ObservedCode -ne "404") {
    throw "FAIL ${TestPath}: ${ObservedCode}"
  }
  "PASS ${TestPath}: 404"
}
```

Validar discovery y su issuer exacto:

```powershell
$DiscoveryFile = Join-Path $env:TEMP "assermetry-prod-discovery.json"
Remove-Item $DiscoveryFile -Force -ErrorAction SilentlyContinue

curl.exe --fail --show-error --noproxy assermetry.com `
  --resolve $Resolve --cacert $OriginCa `
  https://assermetry.com:9443/auth/realms/TrustNews/.well-known/openid-configuration `
  --output $DiscoveryFile
if ($LASTEXITCODE -ne 0) { throw "FAIL OIDC discovery" }

$Issuer = (Get-Content -Raw $DiscoveryFile | ConvertFrom-Json).issuer
$ExpectedIssuer = "https://assermetry.com/auth/realms/TrustNews"
if ($Issuer -ne $ExpectedIssuer) {
  throw "FAIL issuer: ${Issuer}"
}
"PASS issuer: ${Issuer}"
```

Si el origen falla, no modificar todavía redirects ni reglas Cloudflare.

---

# Parte III - Cutover de Cloudflare

## 11. Fotografía y configuración previa

### 11.1 Inventario de Custom Rules

En `Security` > `Security rules`, confirmar y registrar sin copiar Rule IDs:

1. `Maintenance lock - assermetry.com`.
2. `Permanent mTLS - Keycloak administration`.
3. `Temporary mTLS and public path gate - assermetry.com`.
4. `Permanent block - non-public resources`.
5. `Permanent block - unexpected backend methods`.

Guardar de forma segura la expresión de la regla temporal para rollback. No
borrarla antes de tener el lock activo.

Mientras el servicio siga cerrado a clientes, la expresión de esta regla debe
ser la condición mTLS temporal existente `OR` la condición de bloqueo de
namespaces de la sección 13.1. La acción continúa siendo `Block`. No crear una
segunda regla para este bloqueo: así, editar el mismo slot al abrir clientes
permite retirar solo mTLS y conservar la protección de rutas.

La composición durante la v0.0.13 será:

1. maintenance lock, si se conserva;
2. mTLS permanente de administración;
3. `Temporary mTLS and public path gate - assermetry.com` (mTLS general más
  bloqueo de namespaces no permitidos);
4. bloqueo de recursos no públicos;
5. bloqueo de métodos inesperados del Gateway.

La retirada de mTLS y el cambio de nombre para abrir clientes están fuera de
este plan y se ejecutarán como primer paso de la v0.0.14, según
[`next_releases.md`](next_releases.md).

### 11.2 URL Normalization

Cloudflare normaliza las URLs antes de las Custom WAF Rules, evitando que
variantes codificadas eludan una comparación de paths.

En el dashboard:

1. Abrir `Rules` > `Settings`.
2. Entrar en la pestaña `URL Normalization`.
3. Activar `Normalize incoming URLs`.
4. Si está disponible y ya es compatible con el origen, activar también la
   normalización de la URL enviada al origen.
5. Guardar.

Antes de activarla, revisar reglas antiguas que dependan deliberadamente de
`//`, segmentos codificados o de los campos raw. La documentación oficial está
en [URL Normalization](https://developers.cloudflare.com/rules/normalization/)
y [configuración en dashboard](https://developers.cloudflare.com/rules/normalization/manage/).

### 11.3 Comprobar protecciones complementarias

- [ ] El registro DNS de `assermetry.com` está proxificado.
- [ ] Free Managed Ruleset está habilitado.
- [ ] La regla de rate limiting de operaciones costosas está activa.
- [ ] El firewall de Hetzner acepta `443/tcp` únicamente desde rangos vigentes
  de Cloudflare.
- [ ] `80/tcp`, `6443/tcp` y puertos internos no están publicados.
- [ ] No hay registros DNS-only que revelen la IP del origen.

Cloudflare recomienda bloquear el acceso directo al origen y mantener
actualizados sus rangos: [protección del origen](https://developers.cloudflare.com/fundamentals/security/protect-your-origin-server/)
y [direcciones IP de Cloudflare](https://developers.cloudflare.com/fundamentals/concepts/cloudflare-ip-addresses/).

---

## 12. Crear los redirects exactos

Los Single Redirects se ejecutan antes de URL Normalization y antes del WAF.
Una acción Redirect es terminante. Por ello las reglas deben ser exactas y no
deben convertir paths desconocidos en rutas válidas.

La interfaz oficial se documenta en
[Create a redirect rule in the dashboard](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/create-dashboard/).

### 12.1 Redirect exacto de `/`

1. Abrir la zona `assermetry.com`.
2. Ir a `Rules` > `Overview`.
3. Seleccionar `Create rule` > `Redirect Rule`.
4. Nombre: `Redirect exact root to GUI`.
5. Elegir `Custom filter expression`.
6. Seleccionar `Edit expression` y pegar:

```text
(http.host eq "assermetry.com" and http.request.uri.path eq "/")
```

7. Tipo de destino: URL estática.
8. Target URL:

```text
https://assermetry.com/gui/
```

9. Status code: `302`.
10. Activar `Preserve query string`.
11. Guardar como draft si aún se exige un `403` absoluto durante el lock; en
    caso contrario seleccionar `Deploy`.

### 12.2 Redirect exacto de `/gui`

Repetir con:

- nombre: `Redirect exact GUI slash`;
- expresión:

```text
(http.host eq "assermetry.com" and http.request.uri.path eq "/gui")
```

- target: `https://assermetry.com/gui/`;
- status: `302`;
- `Preserve query string`: activado.

No crear reglas wildcard para `/*`, `/gui*` ni para todo el hostname.

### 12.3 Validar redirects

Con las reglas desplegadas:

```bash
curl --silent --show-error --head https://assermetry.com/
curl --silent --show-error --head https://assermetry.com/gui
curl --silent --show-error --head \
  'https://assermetry.com/gui?deployment_probe=1'
```

Resultados:

- `/` devuelve `302` y `Location: https://assermetry.com/gui/`;
- `/gui` devuelve `302` al mismo destino;
- la query `deployment_probe=1` se conserva;
- `/gui/` no entra en bucle;
- `/wp-admin/` no se redirige a `/gui/`.

También puede usarse Cloudflare Trace para confirmar qué regla se ejecuta. Los
ajustes de código y preservación de query están documentados en
[Single Redirects settings](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/settings/).

---

## 13. Estado que se entrega a la v0.0.14

La retirada del mTLS temporal y la apertura a clientes no forman parte de la
v0.0.13. Se ejecutarán como primer paso de la v0.0.14, con una ventana
controlada y rollback preparado.

Hasta entonces, la regla del punto 11 mantiene mTLS general y protección de
rutas en el mismo slot. La combinación bloquea si no hay certificado cliente
válido **o** si el path no pertenece a un namespace permitido. No sustituye la
autenticación, autorización ni el aislamiento que aplican Gateway y las APIs.

### 13.1 Estado temporal validado

Nombre temporal:

```text
Temporary mTLS and public path gate - assermetry.com
```

Expresión conceptual que debe conservarse validada en Cloudflare:

```text
(http.host eq "assermetry.com" and
 (not cf.tls_client_auth.cert_verified or
  not (
    starts_with(http.request.uri.path, "/gui/") or
    http.request.uri.path eq "/backend" or
    starts_with(http.request.uri.path, "/backend/") or
    http.request.uri.path eq "/auth" or
    starts_with(http.request.uri.path, "/auth/")
  )))
```

La condición `not cf.tls_client_auth.cert_verified` representa la condición
mTLS temporal existente. Si la regla actual usa otra expresión equivalente,
conservar esa expresión exacta y combinarla con `OR` con el bloqueo de
namespaces. La acción es `Block`.

### 13.2 Expresión final de la v0.0.14

Nombre final después de abrir clientes:

```text
Default deny - public path namespaces
```

Expresión:

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

Acción:

```text
Block
```

No exceptuar `/` ni `/gui`: sus Single Redirects terminan antes de alcanzar el
WAF. Si cualquiera de esos redirects se desactiva accidentalmente, el
`default deny` bloqueará el path en vez de dejarlo llegar al origen.

La comparación se mantiene sensible a mayúsculas. Con URL Normalization activa,
las Custom Rules reciben el path normalizado.

La edición se realizará en el primer paso de la v0.0.14, no durante este plan.

### 13.3 Alcance real de la regla

La regla bloquea `/wp-admin/`, `/.env`, `/phpmyadmin/`, rutas aleatorias y
prefijos falsos como `/gui-malicious`.

No bloquea por sí sola `/gui/wp-admin` o `/backend/ruta-inexistente`, porque ya
pertenecen a un namespace permitido. Esas peticiones deben terminar en `404`,
autenticación, validación de método o Managed WAF según corresponda. La
allowlist de namespaces reduce superficie, pero no sustituye los controles de
cada aplicación.

---

## 14. Validar el estado cerrado de la v0.0.13

### 14.1 Preparar rollback inmediato

Antes de apagar el lock:

- dejar abierta la pantalla de edición de la regla temporal combinada;
- tener disponible la expresión anterior del mTLS temporal;
- confirmar acceso a GitLab y Hetzner;
- disponer del certificado y la clave del cliente temporal, y de un certificado
  temporal revocado para la prueba negativa;
- confirmar que el certificado administrativo de respaldo está disponible;
- elegir una ventana de observación sin otras modificaciones simultáneas.

### 14.2 Desactivar el maintenance lock

1. En `Security` > `Security rules`, desactivar únicamente
   `Maintenance lock - assermetry.com`.
2. No tocar las otras cuatro reglas.
3. Si los redirects estaban guardados como draft o desactivados, activarlos
   ahora.
4. Ejecutar inmediatamente la matriz siguiente.

### 14.3 Matriz externa con certificado cliente temporal

Definir las rutas de los certificados solo en la sesión de terminal. No
guardarlas en el repositorio ni imprimir certificados, claves o tokens:

```bash
read -rp 'Ruta del certificado cliente temporal: ' ASSERMETRY_CLIENT_CERT
read -rp 'Ruta de la clave cliente temporal: ' ASSERMETRY_CLIENT_KEY

CLIENT_TLS=(--cert "$ASSERMETRY_CLIENT_CERT" --key "$ASSERMETRY_CLIENT_KEY")
```

```bash
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "${CLIENT_TLS[@]}" \
  https://assermetry.com/)" = "302"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "${CLIENT_TLS[@]}" \
  https://assermetry.com/gui)" = "302"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "${CLIENT_TLS[@]}" \
  https://assermetry.com/gui/)" = "200"

for test_path in \
  /wp-admin/ \
  /.env \
  /phpmyadmin/ \
  /path-deployment-probe \
  /gui-malicious \
  /backend-malicious \
  /auth-malicious; do
  observed_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    "${CLIENT_TLS[@]}" \
    "https://assermetry.com${test_path}")"
  test "$observed_code" = "403" || {
    echo "FAIL ${test_path}: ${observed_code}"
    exit 1
  }
done
```

Comprobar rutas conocidas:

```bash
curl --fail --show-error \
  "${CLIENT_TLS[@]}" \
  https://assermetry.com/auth/realms/TrustNews/.well-known/openid-configuration \
  -o /tmp/assermetry-public-discovery.json

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "${CLIENT_TLS[@]}" \
  https://assermetry.com/backend/docs)" = "403"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "${CLIENT_TLS[@]}" \
  -X DELETE https://assermetry.com/backend/orders/deployment-probe)" = "403"
```

Una ruta protegida válida del Gateway sin JWT debe llegar al Gateway y devolver
`401` o `403` según el endpoint, no el bloqueo por path desconocido:

```bash
gateway_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "${CLIENT_TLS[@]}" \
  https://assermetry.com/backend/orders/list)"
case "$gateway_code" in
  401|403) ;;
  *) echo "FAIL /backend/orders/list: ${gateway_code}"; exit 1 ;;
esac
echo "PASS /backend/orders/list: ${gateway_code}"
```

### 14.4 Administración Keycloak

Sin certificado cliente general, una ruta pública y una ruta administrativa
deben quedar bloqueadas por sus reglas mTLS:

```bash
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://assermetry.com/gui/)" = "403"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://assermetry.com/auth/admin/)" = "403"
```

Con certificado administrativo válido, usar rutas locales protegidas y no
registrar sus nombres reales en el repositorio:

```bash
read -rp 'Ruta del certificado administrativo: ' ASSERMETRY_ADMIN_CERT
read -rp 'Ruta de la clave administrativa: ' ASSERMETRY_ADMIN_KEY

curl --cert "$ASSERMETRY_ADMIN_CERT" \
  --key "$ASSERMETRY_ADMIN_KEY" \
  --silent --show-error --head \
  https://assermetry.com/auth/admin/

unset ASSERMETRY_ADMIN_CERT ASSERMETRY_ADMIN_KEY
```

Resultado: la petición supera mTLS y llega a Keycloak, donde todavía se exige
autenticación administrativa. Un certificado revocado debe seguir recibiendo
`403`.

Probar también el certificado temporal revocado contra `/gui/` y conservar solo
el resultado HTTP:

```bash
read -rp 'Ruta del certificado cliente temporal revocado: ' ASSERMETRY_REVOKED_CERT
read -rp 'Ruta de la clave cliente temporal revocada: ' ASSERMETRY_REVOKED_KEY

test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cert "$ASSERMETRY_REVOKED_CERT" \
  --key "$ASSERMETRY_REVOKED_KEY" \
  https://assermetry.com/gui/)" = "403"

unset ASSERMETRY_REVOKED_CERT ASSERMETRY_REVOKED_KEY
unset ASSERMETRY_CLIENT_CERT ASSERMETRY_CLIENT_KEY CLIENT_TLS
```

### 14.5 Regresión funcional pública

Desde una ventana limpia y con el certificado cliente temporal:

- [ ] `/` redirige una sola vez a `/gui/`;
- [ ] login, refresh y logout funcionan;
- [ ] logout vuelve a `/gui/`;
- [ ] LIGHT completa una orden;
- [ ] BLOCKCHAIN completa una orden con IPFS y trazabilidad;
- [ ] generación de aserciones muestra progreso y resultado;
- [ ] error y timeout muestran mensajes recuperables;
- [ ] polling termina o presenta timeout/reintento;
- [ ] roles, cuotas y aislamiento siguen funcionando;
- [ ] consola del navegador no muestra errores relevantes;
- [ ] el uso normal funciona con el certificado cliente temporal;
- [ ] administración continúa exigiendo certificado.

Repetir desde una segunda red para descartar dependencias de caché, allowlists o
sesión local.

### 14.6 Security Events y origen

En Cloudflare `Security` > `Events` comprobar, sin exportar identificadores:

- scanner paths atribuidos al gate temporal combinado;
- `/backend/docs` atribuido al bloqueo de recursos no públicos;
- `DELETE /backend/...` atribuido al bloqueo de métodos;
- administración sin certificado atribuida al mTLS permanente;
- ausencia de bloqueos inesperados sobre `/gui/`, OIDC y operaciones normales.

Desde una red externa no autorizada, la IP directa del origen no debe aceptar
conexiones a `443`; `80` y `6443` también deben permanecer cerrados. No guardar
la IP del origen en este documento.

---

## 15. Observación, estabilización y rollback

### 15.1 Observación

Mantener una ventana de observación de al menos 30 minutos y repetir la matriz
de smoke cada 10 minutos desde la conexión autorizada y una conexión sin
certificado. Registrar timestamp, ruta, código HTTP y resultado `PASS`/`FAIL`,
sin guardar identificadores de Cloudflare, IP, tokens ni cuerpos de respuesta.
La observación termina en `PASS` si no aparece ningún fallo P0/P1, ningún
bloqueo inesperado de rutas permitidas y no hay una subida sostenida de `5xx`.

Durante la ventana definida revisar:

```bash
kubectl get pods -A
kubectl top nodes
kubectl top pods -A
kubectl get events -A --sort-by=.lastTimestamp
```

En Grafana/Loki revisar tasas de `4xx`, `5xx`, errores OIDC, timeouts y reinicios
sin copiar tokens, cuerpos, IP o datos personales.

Comprobar además que los `403` esperados se atribuyen a la regla correcta y que
las solicitudes permitidas llegan a Traefik/Gateway/Keycloak. Un `403` no basta
por sí solo para demostrar que la regla correcta se ejecutó.

Mantener los redirects en `302` durante esta fase. Cambiar a `301` únicamente
cuando varias regresiones consecutivas sean correctas y se acepte el efecto de
caché de un redirect permanente.

### 15.2 Criterios de rollback inmediato

- `/gui/` no carga o pierde assets;
- login o logout entra en bucle;
- Keycloak rechaza redirects válidos;
- LIGHT o BLOCKCHAIN deja de funcionar;
- una ruta administrativa queda accesible sin certificado;
- paths desconocidos alcanzan el origen;
- aparecen errores P0/P1 o una subida sostenida de `5xx`.

### 15.3 Rollback Cloudflare

1. Activar inmediatamente el maintenance lock.
2. Si se exige bloqueo absoluto, desactivar también los dos Single Redirects.
3. Editar la regla del mismo slot.
4. Restaurar nombre, expresión combinada y acción de
  `Temporary mTLS and public path gate - assermetry.com`.
5. Confirmar que el mTLS temporal vuelve a bloquear rutas no administrativas
   sin certificado y que los namespaces no permitidos siguen bloqueados.
6. Mantener intacta la regla mTLS administrativa.
7. Repetir la matriz mínima: `/gui/` con certificado temporal válido debe
  responder `200`, sin certificado debe responder `403`, y un path fuera de
  namespace debe responder `403` incluso con certificado válido.

### 15.4 Rollback Kubernetes

Si el defecto está en aplicación o Ingress, desplegar mediante GitLab el commit
anterior conocido. Para una recuperación puntual y controlada:

```bash
kubectl rollout undo deployment/frontend-web -n frontend
kubectl rollout undo deployment/gateway -n apis
kubectl rollout status deployment/frontend-web -n frontend --timeout=180s
kubectl rollout status deployment/gateway -n apis --timeout=180s
```

Si se revierte el contrato `/gui`, restaurar de forma coordinada Ingress,
frontend, redirects y URLs de Keycloak. No dejar Keycloak apuntando a una ruta
que el frontend ya no sirve.

No borrar PVC ni Secrets y no hacer `git reset --hard` como rollback operativo.

Después de cualquier rollback de Kubernetes, repetir como mínimo el smoke de
`/gui/`, sus assets, discovery OIDC y una ruta válida del Gateway. Confirmar
también que no se ha reintroducido el catch-all `/` ni se ha desalineado
`TrustNewsWeb`.

---

# Parte IV - Cierre e incorporación a `version.md`

## 16. Criterio de salida completo

- [ ] Gate local completo sobre el commit desplegado.
- [ ] Pipelines `traefik-prod` y `apis-frontend-prod` en verde.
- [ ] Traefik productivo con prefijos estrictos.
- [ ] `/gui` desplegado y Keycloak alineado.
- [ ] Redirects exactos activos con `302` y query preservada.
- [ ] Antes de abrir clientes: gate temporal con mTLS general y bloqueo de
  namespaces no permitidos validado.
- [ ] La retirada de mTLS queda fuera de esta versión y se traslada al primer
  paso de la v0.0.14.
- [ ] Scanner paths y prefijos falsos bloqueados con `403`.
- [ ] Administración sin certificado bloqueada.
- [ ] Administración con certificado válido llega a Keycloak.
- [ ] LIGHT y BLOCKCHAIN funcionan con el certificado cliente temporal.
- [ ] Timeout, error y reintento del frontend comprobados.
- [ ] Origen no accesible directamente desde una red no autorizada.
- [ ] Sin defectos P0/P1 ni regresiones sostenidas durante la observación.
- [ ] Rollback documentado y expresión mTLS temporal conservada de forma segura.

## 17. Promoción a `version.md`

Solo después de completar la sección 16:

1. Actualizar la tabla de la sección 3 de este documento con commit, pipelines,
   fecha y resultado `PASS`.
2. En [`version.md`](version.md), dentro de `Fase 13.2 - Regresión de GUI`,
   sustituir los puntos de trabajo relativos a `/gui` por un bloque de resultado
   verificado que indique:
   - despliegue validado primero en Kind y después en Hetzner;
   - frontend publicado exclusivamente bajo `/gui/`;
   - Keycloak alineado con redirects y post-logout `/gui/*`;
   - LIGHT por defecto y Blockchain mediante checkbox;
   - progreso, timeouts, errores y reintentos comprobados;
   - redirects exactos de Cloudflare activos;
  - gate temporal combinado validado y mTLS administrativo conservado;
   - commit y referencias sanitizadas de pipelines/evidencias.
3. Actualizar el estado o criterio de salida de la versión únicamente si el
   resto de fases de `v0.0.13` también lo permite.
4. Consolidar cualquier aprendizaje permanente en
   `deploy/skaffold-local.md` o `deploy/skaffold-server.md`.
5. Eliminar `working.md` en el mismo commit de promoción o reemplazarlo por una
   nota corta que enlace al resultado en `version.md`. No mantener dos fuentes
   vigentes con instrucciones divergentes.

Texto base sugerido para la promoción:

```markdown
#### Resultado verificado - publicación bajo `/gui/`

- Validado en Kind y desplegado posteriormente en Hetzner desde el mismo commit.
- Frontend servido bajo `/gui/`, con prefijos estrictos y sin catch-all `/`.
- `TrustNewsWeb` alineado con redirects y post-logout `/gui/*`.
- LIGHT es el modo predeterminado; Blockchain se activa mediante checkbox.
- Progreso, timeout, errores y reintentos de aserciones/verificación validados.
- Cloudflare usa redirects exactos de `/` y `/gui`, el gate temporal combinado
  de mTLS y namespaces públicos, y conserva mTLS para la administración de
  Keycloak.
- Regresión LIGHT/BLOCKCHAIN, OIDC, WAF y acceso al origen: PASS.
```

---

## 18. Referencias oficiales

- [Traefik Kubernetes Ingress y strict prefix matching](https://doc.traefik.io/traefik/providers/kubernetes-ingress/)
- [Cloudflare: fases del Ruleset Engine](https://developers.cloudflare.com/ruleset-engine/reference/phases-list/)
- [Cloudflare: comportamiento terminante de reglas](https://developers.cloudflare.com/ruleset-engine/about/rules/)
- [Cloudflare: crear Single Redirect en dashboard](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/create-dashboard/)
- [Cloudflare: ajustes de Single Redirects](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/settings/)
- [Cloudflare: crear Custom Rule en dashboard](https://developers.cloudflare.com/waf/custom-rules/create-dashboard/)
- [Cloudflare: URL Normalization](https://developers.cloudflare.com/rules/normalization/)
- [Cloudflare: proteger el servidor de origen](https://developers.cloudflare.com/fundamentals/security/protect-your-origin-server/)
