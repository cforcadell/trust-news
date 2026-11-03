# Quick start local

Guía corta para levantar Assermetry en una VM local, acceder desde el host,
ejecutar las comprobaciones básicas y abrir el viewer de evaluación. Los
procedimientos completos y las operaciones destructivas están en
[`deploy/skaffold-local.md`](deploy/skaffold-local.md) y
[`deploy/k8s-common.md`](deploy/k8s-common.md).

## 1. Requisitos

Ejecutar los comandos de despliegue desde la raíz del repositorio dentro de la
VM. Se necesitan Docker, Kind, `kubectl`, Skaffold v4, Python con `.venv`,
Node.js 22 o posterior y Google Chrome para el E2E de frontend.

Los ficheros `.env`, credenciales y claves se crean fuera del repositorio. No
se deben escribir secretos en scripts versionados.

Comprobar el contexto antes de operar:

```bash
kubectl config current-context
docker info >/dev/null
```

El contexto local esperado es `kind-trust-news`.

## 2. Crear el clúster y los namespaces

Si el clúster todavía no existe:

```bash
kind create cluster --name trust-news --config kind-config.yaml
```

Crear o verificar los namespaces:

```bash
cd scripts/k8s
./create-namespaces.sh
cd ../..
kubectl get ns blockchain infra apis frontend
```

No se debe recrear un clúster existente como operación rutinaria: eliminarlo
borra los recursos y volúmenes asociados al entorno.

## 3. Levantar la infraestructura

Usar terminales separadas y mantener los procesos `skaffold dev` activos.
`infra-basic` e `infra` son alternativas; no se ejecutan simultáneamente.

Terminal 1, infraestructura completa con observabilidad:

```bash
./skaffold dev -p infra
```

Para un entorno más ligero, sustituirlo por:

```bash
./skaffold dev -p infra-basic
```

Aplicar Traefik desde otra terminal:

```bash
./skaffold deploy -p traefik
kubectl rollout status deployment/traefik -n kube-system
```

Terminal 2, APIs y frontend:

```bash
./skaffold dev -p apis-frontend
```

Mantener el modo LIGHT para el arranque básico:

```bash
BLOCKCHAIN_ENABLED=OFF bash scripts/k8s/set-blockchain-mode.sh
```

Ejecutar el bootstrap idempotente de MongoDB y la configuración de Keycloak
descritos en
[`deploy/k8s-common.md`](deploy/k8s-common.md#7-mongodb-bootstrap) antes de
las pruebas funcionales.

Comprobar el despliegue:

```bash
kubectl get pods -A
kubectl get ingress -A
kubectl get svc -A
```

## 4. Entrada TLS y túnel VM → host

Dentro de la VM, abrir Traefik únicamente en loopback:

```bash
kubectl port-forward --address 0.0.0.0 \
  -n kube-system svc/traefik 7443:443
```

En el host, abrir el túnel SSH y mantenerlo activo:

```bash
ssh -N \
  -L 7443:127.0.0.1:7443 \
  -L 8400:127.0.0.1:8400 \
  -L 8500:127.0.0.1:8500 \
  -L 8074:127.0.0.1:8074 \
  -L 8075:127.0.0.1:8075 \
  -L 8765:127.0.0.1:8765 \
  <usuario-vm>@<ip-privada-vm>
```

Los puertos `8400`, `8500`, `8074` y `8075` los crea el perfil
`apis-frontend`. El `8765` corresponde al viewer, que se inicia en la sección
7. Si se usa `infra`, pueden añadirse al mismo comando:

```text
-L 3000:127.0.0.1:3000
-L 8081:127.0.0.1:8081
-L 9000:127.0.0.1:9000
```

Desde el host:

| Servicio | URL |
| --- | --- |
| Frontend | `https://localhost:7443/gui/` |
| Gateway por Ingress | `https://localhost:7443/backend/docs` |
| Keycloak | `https://localhost:7443/auth/admin/master/console/` |
| Admin API | `http://localhost:8400/docs` |
| Gateway directo | `http://localhost:8500/docs` |
| Evidence Search | `http://localhost:8074/docs` |
| Source Router | `http://localhost:8075/docs` |

El nombre `localhost` debe conservarse en el acceso por Traefik porque forma
parte del issuer OIDC local. El certificado local puede requerir aceptar la
excepción del navegador.

Con el túnel activo, reconciliar idempotentemente el cliente web y la
audiencia del Gateway antes del primer login:

```bash
KEYCLOAK_URL=https://localhost:7443/auth \
FRONTEND_URL=https://localhost:7443/gui \
WEB_ORIGIN=https://localhost:7443 \
./scripts/k8s/infra/reconcile-keycloak-web-prod.sh
```

## 5. Comprobaciones básicas

Validar Python y JavaScript modificados:

```bash
python3 -m py_compile <fichero.py>
node --check <fichero.js>
```

Ejecutar los tests de evaluación, sin proveedores externos:

```bash
PYTHONPATH=tests:api .venv/bin/pytest -q tests/evaluation
```

Validar los recursos del E2E de frontend sin abrir Chrome:

```bash
node tests/frontend/e2e/run-regression.js --validate
```

Comprobar la entrada desplegada:

```bash
curl --fail --show-error --cacert web_classic/certs/fullchain.pem \
  -o /dev/null https://localhost:7443/gui/
curl --fail --show-error --cacert web_classic/certs/fullchain.pem \
  -o /dev/null https://localhost:7443/backend/docs
```

## 6. E2E

### 6.1 Evaluación del pipeline desplegado

El túnel de `7443` debe seguir activo. Cargar las credenciales sin guardarlas
en el script:

```bash
export ASSERMETRY_KEYCLOAK_CLIENT_ID=TrustNewsApi
read -rsp 'TrustNewsApi client secret: ' ASSERMETRY_KEYCLOAK_CLIENT_SECRET
export ASSERMETRY_KEYCLOAK_CLIENT_SECRET
printf '\n'

PYTHONPATH=tests:api .venv/bin/python -m evaluation.pipeline \
  --dataset tests/data/benchmark/resources/cases/official-gold-v0 \
  --mode full \
  --publish \
  --repetitions 1 \
  --output "tests/data/evaluation/artifacts/e2e-$(date +%Y%m%d-%H%M%S)"

unset ASSERMETRY_KEYCLOAK_CLIENT_SECRET
```

La campaña correcta termina con `phase=campaign.complete`. Un informe
`COMPLETED_WITH_ERRORS` requiere revisar `execution_failures`; no acredita que
el E2E haya pasado.

### 6.2 Smoke LIGHT del frontend

```bash
export ASSERMETRY_USERNAME=<usuario-local>
read -rsp 'Password: ' ASSERMETRY_PASSWORD
export ASSERMETRY_PASSWORD
printf '\n'

ASSERMETRY_CASE_FILE=tests/data/frontend-e2e/resources/cases/light.json \
  node tests/frontend/e2e/ui-smoke-test.js

unset ASSERMETRY_PASSWORD
```

La regresión completa LIGHT + BLOCKCHAIN requiere dos identidades, cuotas y
el modo blockchain preparado. Seguir
[`../tests/frontend/e2e/README.md`](../tests/frontend/e2e/README.md) antes de
ejecutar:

```bash
node tests/frontend/e2e/run-regression.js
```

## 7. Viewer local

Iniciar el viewer dentro de la VM desde la raíz del repositorio:

```bash
PYTHONPATH=tests:api .venv/bin/python -m evaluation.viewer.server \
  --artifacts-root tests/data/evaluation/artifacts \
  --host 0.0.0.0 \
  --port 8765
```

Abrir `http://127.0.0.1:8765/` en la VM o en el host si el túnel SSH de la
sección 4 incluye el puerto `8765`.

Solo las campañas que contienen diagnósticos `*-viewer.json` o un informe
reconocible aparecen con información navegable. El viewer es de solo lectura
y no vuelve a ejecutar búsquedas ni modelos.

## 8. Parada

Detener los `port-forward`, el viewer y los procesos `skaffold dev` con
`Ctrl+C`. Esto conserva el clúster y sus volúmenes. No usar
`kind delete cluster` salvo que se haya decidido expresamente reconstruir el
entorno.
