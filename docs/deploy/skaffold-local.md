# Assermetry Kubernetes - Despliegue local

Runbook del entorno local con Kind y perfiles no productivos de Skaffold. Este
documento contiene la fotografía vigente, procedimientos repetibles y próximos
pasos. La evidencia histórica no se conserva aquí.

Los procedimientos compartidos están en
[`k8s-common.md`](k8s-common.md), el estado de la versión actual en
[`version.md`](../version.md) y el roadmap en
[`next_releases.md`](../next_releases.md).

---

## 1. Fotografía local actual

| Ámbito | Estado vigente |
| --- | --- |
| Clúster | Kind, nombre `trust-news` |
| Entrada web | `https://localhost:7443`, conservando el hostname mediante redirección o túnel desde el host |
| Ingress | Overlay `k8s/ingress/overlays/local` con `host: localhost` |
| TLS | Secret local `trustnews-origin-tls` generado desde `web_classic/certs/*` |
| Identidad | Keycloak con issuer `https://localhost:7443/auth/realms/TrustNews` |
| APIs | Documentación disponible por los port-forward locales de Skaffold |
| Cloudflare | No interviene en local |
| mTLS | No se reproducen las reglas Cloudflare en Kind |
| Producción | No se despliegan overlays `prod` ni `prod-domain` |

Perfiles locales:

| Perfil | Alcance |
| --- | --- |
| `traefik` | Traefik local, chart `41.0.2` |
| `blockchain` | Red privada Geth local |
| `infra-basic` | Infraestructura básica sin monitorización |
| `infra` | Infraestructura completa con Kafdrop, Fluent Bit, Loki y Grafana |
| `apis-frontend` | APIs, Gateway, frontend e Ingress local |

`infra-basic` y `infra` son alternativas. No deben ejecutarse simultáneamente:

- usar `infra-basic` para el flujo local ligero sin monitorización;
- usar `infra` cuando se necesiten logs, persistencia de observabilidad,
  Grafana o Kafdrop.

`infra-basic` no existe en producción.

### 1.1 Acceso desde el host de la VM

El entorno local se ejecuta dentro de una VM y los port-forward que deben
abrirse desde el host escuchan deliberadamente en `0.0.0.0`. Esta excepción es
solo local: el adaptador de la VM debe ser `host-only` o una red privada
equivalente, y el firewall del guest debe aceptar esos puertos únicamente desde
la dirección del host. No usar una interfaz puente ni una red compartida no
fiable con esos listeners activos.

El recorrido completo por Traefik debe conservar `localhost`: el Ingress y el
issuer OIDC dependen de ese hostname. Desde el host se
redirige el puerto del hipervisor hacia la VM o se abre un túnel, por ejemplo:

```bash
ssh -L 7443:127.0.0.1:7443 <usuario-vm>@<ip-privada-vm>
```

Después se abre `https://localhost:7443` en el host. No sustituir el hostname
por la IP de la VM para validar login u OIDC. Los paneles y APIs accedidos por
port-forward directo, sin una regla de host canónica, sí pueden abrirse como
`http://<ip-privada-vm>:<puerto>`. Si no se necesita acceso desde el host,
ligar el port-forward a `127.0.0.1`.

---

## 2. Flujo de despliegue

Orden:

1. Crear o comprobar el clúster Kind.
2. Crear namespaces.
3. Desplegar `blockchain`.
4. Desplegar o verificar el contrato.
5. Elegir `infra-basic` o `infra`.
6. Ejecutar el bootstrap de MongoDB.
7. Desplegar `traefik`.
8. Desplegar `apis-frontend`.
9. Configurar Keycloak, cuotas y datos funcionales.
10. Ejecutar la matriz de validación local.

---

## 3. Clúster y namespaces

Crear el clúster:

```bash
kind create cluster --name trust-news --config kind-config.yaml
```

Crear namespaces:

```bash
cd ./scripts/k8s
./create-namespaces.sh
kubectl get ns blockchain infra apis frontend
```

Recrear el clúster es destructivo. Antes de hacerlo:

```bash
kubectl get pvc -A
docker volume ls
df -h /
```

Cuando la reconstrucción esté decidida:

```bash
kind delete cluster --name trust-news
kind create cluster --name trust-news --config kind-config.yaml
```

La limpieza adicional de imágenes o volúmenes Docker se ejecuta por separado y
solo después de revisar sus objetivos.

---

## 4. Blockchain y contrato

Desplegar la red local:

```bash
./skaffold dev -p blockchain --namespace blockchain
```

Comprobar nodos y logs:

```bash
kubectl get pods -n blockchain
kubectl logs -n blockchain -f geth-bootnode-0
kubectl logs -n blockchain -f geth-rpc-endpoint-0
kubectl logs -n blockchain -f geth-miner-0
```

Abrir el RPC solo cuando sea necesario:

```bash
kubectl port-forward svc/geth-rpc-endpoint 8555:8555 -n blockchain
```

Desplegar un contrato local:

```bash
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth
```

Inicializar categorías:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network privateGeth
npx hardhat run scripts/initCategories.js --network privateGeth
unset DEPLOYER_PRIVATE_KEY
```

La segunda ejecución verifica la idempotencia y no debe crear categorías
duplicadas.

---

## 5. Infraestructura local

### 5.1 Perfil básico

`infra-basic` incluye Kafka, IPFS, MongoDB, Mongo Express y Keycloak. Excluye
Kafdrop, Fluent Bit, Loki y Grafana.

```bash
./skaffold dev -p infra-basic
```

Mongo Express queda disponible en:

```text
http://localhost:8081
```

### 5.2 Perfil completo

`infra` añade Kafdrop, Fluent Bit, Loki y Grafana:

```bash
./skaffold dev -p infra
```

Servicios:

```text
Kafdrop:       http://localhost:9000
Grafana:       http://localhost:3000
Mongo Express: http://localhost:8081
```

Si el port-forward de Mongo Express se interrumpe:

```bash
kubectl port-forward --address 0.0.0.0 \
  -n infra svc/mongo-express 8081:8081
```

El listener queda accesible desde el host de acuerdo con el modelo de red
privada descrito en [1.1](#11-acceso-desde-el-host-de-la-vm).

Con cualquiera de los dos perfiles, ejecutar después el bootstrap común:

- [`k8s-common.md - MongoDB bootstrap`](k8s-common.md#6-mongodb-bootstrap).

---

## 6. Traefik, APIs y frontend

Instalar o actualizar Traefik exclusivamente mediante Skaffold:

```bash
./skaffold deploy -p traefik
```

El perfil fija el chart `41.0.2`, usa `k8s/traefik/values.yaml` y aplica
upgrades atómicos. No ejecutar `helm upgrade` ni parchear el Deployment
manualmente.

Comprobar el controlador:

```bash
kubectl rollout status deployment/traefik -n kube-system
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
kubectl get ingress -A
```

Desplegar APIs y frontend:

```bash
./skaffold dev -p apis-frontend
```

Abrir la entrada completa:

```bash
kubectl port-forward --address 0.0.0.0 \
  -n kube-system svc/traefik 7443:443
```

El listener queda accesible desde el host de acuerdo con el modelo de red
privada descrito en [1.1](#11-acceso-desde-el-host-de-la-vm).

Rutas principales:

```text
https://localhost:7443/
https://localhost:7443/backend/docs
https://localhost:7443/auth/admin/master/console/
```

El navegador puede mostrar un aviso por el certificado local.

No usar el port-forward directo del frontend para validar la aplicación
completa: solo sirve los estáticos y deja fuera `/backend` y `/auth`.

---

## 7. Secrets y configuración

Comprobar Secrets sin copiar su contenido al repositorio:

```bash
kubectl get secrets -n infra
kubectl get secrets -n apis
```

La configuración compartida de Keycloak y cuotas está en:

- [`k8s-common.md - Keycloak y cuotas`](k8s-common.md#7-keycloak-y-cuotas).

La configuración funcional y las operaciones de MongoDB están en:

- [`k8s-common.md - Evidence Search`](k8s-common.md#8-evidence-search);
- [`k8s-common.md - MongoDB`](k8s-common.md#9-mongodb-consultas-y-limpieza).

El frontend no termina TLS ni proxifica `/backend` o `/auth`. Traefik publica
esas rutas mediante los manifests de Ingress.

---

## 8. Endpoints locales

La tabla usa `localhost` como referencia canónica. Para el frontend y Keycloak
se conserva mediante redirección o túnel. Un port-forward HTTP directo expuesto
por Skaffold puede usar la IP privada de la VM. Los servicios que Skaffold liga
solo a loopback requieren un túnel o un port-forward explícito con el mismo
criterio de red de [1.1](#11-acceso-desde-el-host-de-la-vm).

| Servicio | URL | Perfil |
| --- | --- | --- |
| Frontend | `https://localhost:7443` | `apis-frontend` |
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
| Mongo Express | `http://localhost:8081` | `infra-basic` o `infra` |
| Grafana | `http://localhost:3000` | `infra` |
| Kafdrop | `http://localhost:9000` | `infra` |
| Keycloak Admin | `https://localhost:7443/auth/admin/master/console/` | `apis-frontend` |

---

## 9. Validación local vigente

Local valida aplicación y manifests sin reproducir los controles externos de
Cloudflare.

### 9.1 Render

```bash
kubectl kustomize --load-restrictor=LoadRestrictionsNone \
  k8s/ingress/overlays/local > /tmp/assermetry-ingress-local.yaml

rg -n 'host: localhost|gateway-strip-backend-prefix' \
  /tmp/assermetry-ingress-local.yaml
```

El render no debe contener `prod-domain`, el issuer público ni bloqueos
exclusivos de Cloudflare.

### 9.2 Matriz funcional

La validación debe cubrir:

- login, refresh, logout y expiración;
- navegación y autorización por rol;
- polling y cuotas;
- flujos Light y Blockchain;
- métodos válidos e inválidos;
- autenticación ausente, expirada o manipulada;
- cuerpo dentro de 5 MiB y por encima del límite;
- documentación del Gateway y consola de Keycloak accesibles en local;
- ausencia de errores relevantes en Gateway, workers, Traefik y frontend.

Resultados esperados de los controles técnicos:

| Caso | Resultado |
| --- | --- |
| API protegida sin token | `401` o `403` según la capa |
| Método no permitido | `405` |
| Cuerpo superior a 5 MiB | `413` |
| Documentación local | Accesible |
| Rate limiting Cloudflare | No aplica |
| mTLS Cloudflare | No aplica |

Cuando cambien Gateway, Traefik o sus manifests se repite esta matriz antes de
desplegar en Hetzner.

---

## 10. Mantenimiento local

Estado y consumo:

```bash
kubectl get pods -A
kubectl get pvc -A
docker system df
```

Detener primero los procesos `skaffold dev` para evitar que vuelvan a importar
imágenes mientras se ejecuta la limpieza.

Limpiar imágenes no usadas dentro de los nodos Kind:

```bash
for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  docker exec "$node" crictl rmi --prune || true
done
```

`crictl rmi --prune` puede conservar las imágenes temporales cargadas por
Skaffold porque containerd mantiene referencias con nombres
`import-<fecha>@sha256:<digest>`. Previsualizar siempre esas referencias antes
de eliminarlas:

```bash
for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo "=== $node ==="
  docker exec "$node" sh -c \
    'ctr --namespace k8s.io images list -q | grep "^import-" || true'
done
```

Cuando no haya despliegues de Skaffold activos, borrar las referencias
temporales por su nombre exacto y solicitar después una nueva poda a CRI:

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

Verificar que no quedan referencias temporales y medir el espacio recuperado:

```bash
for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  echo "=== $node ==="
  docker exec "$node" sh -c \
    'ctr --namespace k8s.io images list -q | grep -c "^import-" || true'
  docker exec "$node" du -sh /var/lib/containerd
done

df -h /
```

Cada contador debe quedar en `0`. Las imágenes necesarias se reconstruyen o
se vuelven a cargar en el siguiente despliegue de Skaffold. Este procedimiento
no elimina el clúster ni sus PVC. No borrar manualmente
`/var/lib/containerd` ni los volúmenes Docker asociados a los nodos Kind.

La eliminación de PVC solo pertenece a una reconstrucción local deliberada.
Inspeccionar siempre antes:

```bash
kubectl get pvc -n infra
kubectl get pvc -n blockchain
```

---

## 11. Próximos pasos

### v0.0.13

- Crear el conjunto reproducible de datos sintéticos.
- Ejecutar la regresión completa de GUI y API.
- Añadir pruebas negativas de `aud`, `azp` o `client_id`, issuer, expiración y
  firma.
- Demostrar aislamiento entre organizaciones.
- Repetir tres demos internas consecutivas con la misma inicialización y
  limpieza.

### Versiones posteriores

- Mantener local sin Cloudflare, certificados cliente ni `prod-domain`.
- Usar local como destino aislado para pruebas de restauración cuando
  `v0.0.16` defina el procedimiento.
- No incorporar Cloudflare Tunnel al perfil local.

El detalle y los criterios de salida se mantienen en
[`next_releases.md`](../next_releases.md).
