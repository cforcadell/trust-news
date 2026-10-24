# Quick start Hetzner

Guía corta para desplegar y operar Assermetry en Hetzner sin publicar los
servicios internos. El runbook normativo sigue siendo
[`deploy/skaffold-server.md`](deploy/skaffold-server.md); los secretos, la
configuración de Cloudflare y las reconstrucciones no se resumen aquí.

## 1. Modelo operativo

- El despliegue productivo se realiza mediante el pipeline protegido de
  GitLab sobre `postTFM`.
- Los perfiles productivos son `traefik-prod`, `infra-prod` y
  `apis-frontend-prod`. No se usan overlays `local` ni perfiles locales.
- La aplicación pública conserva el issuer
  `https://assermetry.com/auth/realms/TrustNews`.
- APIs administrativas, observabilidad y bases de datos permanecen como
  `ClusterIP`. Para operar fuera de la GUI se accede mediante SSH y
  `kubectl port-forward`, siempre ligados a loopback.
- Antes de probar el dominio se debe conocer el estado deliberado del lock y
  de las reglas mTLS de Cloudflare.

## 2. Despliegue básico

Para una instalación inicial, lanzar pipelines separados y esperar a que cada
uno termine correctamente:

```dotenv
PROFILE=traefik-prod
PROFILE=infra-prod
PROFILE=apis-frontend-prod
BLOCKCHAIN_ENABLED=OFF
```

Para una actualización normal de aplicación:

```dotenv
PROFILE=apis-frontend-prod
BLOCKCHAIN_ENABLED=OFF
```

El pipeline aplica el artefacto construido, espera los rollouts y ejecuta la
reconciliación idempotente de Keycloak. No sustituir este flujo por
`kubectl apply`, parches manuales o `helm upgrade`.

## 3. Acceso SSH y Kubernetes

Variables usadas en los ejemplos:

```bash
export HETZNER_HOST=<ip-o-hostname>
export HETZNER_USER=<usuario>
export HETZNER_KEY=<ruta-clave-ssh>
```

Comprobar el servidor:

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  "$HETZNER_USER@$HETZNER_HOST" \
  'kubectl get nodes; kubectl get pods -A'
```

Si se opera con un kubeconfig local preparado para el certificado del K3s,
abrir en una terminal el túnel de la API:

```bash
ssh -N -i "$HETZNER_KEY" -p 2222 \
  -L 6443:127.0.0.1:6443 \
  "$HETZNER_USER@$HETZNER_HOST"
```

El kubeconfig de esa terminal debe usar `https://127.0.0.1:6443`. No se debe
publicar `6443/tcp` en el firewall.

## 4. Patrón de túnel para servicios internos

Cada comando siguiente ocupa una terminal. El puerto del servicio solo se
abre en loopback dentro de Hetzner y se transporta por SSH hasta el equipo del
operador:

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  -L <puerto-local>:127.0.0.1:<puerto-remoto> \
  "$HETZNER_USER@$HETZNER_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 \
      -n <namespace> svc/<servicio> <puerto-remoto>:<puerto-servicio>'
```

Usar puertos locales alternativos evita colisiones con un entorno Kind que
esté ejecutándose en el mismo equipo.

### 4.1 Admin API

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  -L 18400:127.0.0.1:18400 \
  "$HETZNER_USER@$HETZNER_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 \
      -n apis svc/admin-service 18400:8400'
```

Abrir `http://127.0.0.1:18400/docs` únicamente durante la operación.

### 4.2 Gateway directo

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  -L 18500:127.0.0.1:18500 \
  "$HETZNER_USER@$HETZNER_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 \
      -n apis svc/gateway 18500:8500'
```

Abrir `http://127.0.0.1:18500/docs`. Este acceso directo sirve para diagnóstico
y no reproduce los controles de Cloudflare o Traefik.

### 4.3 Evidence Search y Source Router

Evidence Search:

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  -L 18074:127.0.0.1:18074 \
  "$HETZNER_USER@$HETZNER_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 \
      -n apis svc/evidence-search 18074:8074'
```

Source Router:

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  -L 18075:127.0.0.1:18075 \
  "$HETZNER_USER@$HETZNER_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 \
      -n apis svc/source-router 18075:8075'
```

Las URLs locales son `http://127.0.0.1:18074/docs` y
`http://127.0.0.1:18075/docs`.

### 4.4 Grafana y Mongo Express

Grafana:

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  -L 13300:127.0.0.1:13300 \
  "$HETZNER_USER@$HETZNER_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 \
      -n infra svc/grafana 13300:3000'
```

Abrir `http://127.0.0.1:13300`.

Mongo Express, solo cuando su uso esté autorizado:

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  -L 18081:127.0.0.1:18081 \
  "$HETZNER_USER@$HETZNER_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 \
      -n infra svc/mongo-express 18081:8081'
```

Abrir `http://127.0.0.1:18081`. No copiar datos productivos a artefactos de
test ni a la documentación.

### 4.5 Traefik/origen

Este túnel es de diagnóstico TLS; no cambia el issuer productivo ni sustituye
la validación pública por Cloudflare:

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  -L 9443:127.0.0.1:9443 \
  "$HETZNER_USER@$HETZNER_HOST" \
  -t 'kubectl port-forward --address 127.0.0.1 \
      -n kube-system svc/traefik 9443:443'
```

Validar conservando hostname y SNI:

```bash
curl --resolve assermetry.com:9443:127.0.0.1 \
  --cacert <cloudflare-origin-ca.pem> \
  https://assermetry.com:9443/gui/
```

No usar `https://localhost:9443` para validar OIDC productivo.

## 5. Comprobaciones básicas

Estado de Kubernetes:

```bash
kubectl get pods -A
kubectl get pvc -A
kubectl get ingress -A
kubectl get svc -A
kubectl rollout status deployment/traefik -n kube-system
```

Los servicios internos no deben aparecer publicados mediante Ingress o
NodePort. Antes de comprobar el dominio, confirmar el estado del lock y de
mTLS según el runbook productivo.

Las pruebas unitarias y la validación estática se ejecutan en el checkout del
operador o en CI, no dentro de los pods productivos:

```bash
PYTHONPATH=tests:api .venv/bin/pytest -q tests/evaluation
node tests/frontend/e2e/run-regression.js --validate
```

El E2E contra producción consume cuotas y puede llamar proveedores externos.
Solo se ejecuta en una ventana autorizada, con identidades sintéticas,
Cloudflare en el estado acordado y los hooks de preparación/limpieza definidos
en [`../tests/frontend/e2e/README.md`](../tests/frontend/e2e/README.md).

## 6. Viewer de evaluación

La opción preferida es descargar o generar los artefactos en el checkout
local y ejecutar allí el viewer de solo lectura:

```bash
PYTHONPATH=tests:api .venv/bin/python -m evaluation.viewer.server \
  --artifacts-root tests/data/evaluation/artifacts \
  --host 127.0.0.1 \
  --port 8765
```

Abrir `http://127.0.0.1:8765/`.

Si excepcionalmente los artefactos solo están en Hetzner, iniciar el viewer
allí ligado a `127.0.0.1`:

```bash
cd <ruta-checkout>
PYTHONPATH=tests:api .venv/bin/python -m evaluation.viewer.server \
  --artifacts-root tests/data/evaluation/artifacts \
  --host 127.0.0.1 \
  --port 8765
```

Desde el equipo del operador, transportarlo sin publicar el puerto:

```bash
ssh -N -i "$HETZNER_KEY" -p 2222 \
  -L 18765:127.0.0.1:8765 \
  "$HETZNER_USER@$HETZNER_HOST"
```

Abrir entonces `http://127.0.0.1:18765/`.

## 7. Cierre de la operación

Finalizar cada túnel con `Ctrl+C`, comprobar que no quedan `port-forward`
activos en el servidor y borrar las variables de la sesión:

```bash
ssh -i "$HETZNER_KEY" -p 2222 \
  "$HETZNER_USER@$HETZNER_HOST" \
  "pgrep -af '[k]ubectl port-forward' || true"

unset HETZNER_HOST HETZNER_USER HETZNER_KEY
```

Los túneles son herramientas temporales de operación; nunca justifican abrir
puertos adicionales en el firewall de Hetzner.
