# TrustNews Kubernetes - Despliegue local

Runbook para entorno local con `kind` y perfiles no productivos de Skaffold.
Los procedimientos compartidos viven en [`k8s-common.md`](k8s-common.md).

Orden recomendado:

1. Recrear cluster local si se quiere empezar desde cero.
2. Crear namespaces.
3. Levantar blockchain.
4. Desplegar contrato local.
5. Levantar infraestructura.
6. Levantar APIs y frontend.
7. Configurar Keycloak, cuotas y usuarios.
8. Cargar configuraciones funcionales.
9. Consultar datos, endpoints y colecciones.

---

## 1. Recrear cluster local

Usar esta seccion cuando se quiera empezar desde cero. Es destructiva: borra el
cluster `kind`, imagenes/volumenes Docker no usados y limpia espacio local.

Inspeccion previa:

```bash
kubectl get pvc -A
docker volume ls
df -h /
```

Borrar cluster:

```bash
kind delete cluster --name trust-news
```

Limpieza local:

```bash
docker system prune -a -f
sudo journalctl --vacuum-size=300M
sudo apt clean
sudo apt autoremove -y
docker volume prune -f
df -h /
docker volume ls
```

Crear cluster:

```bash
kind create cluster --name trust-news --config kind-config.yaml
```

---

## 2. Crear namespaces

```bash
cd ./scripts/k8s
./create-namespaces.sh
kubectl get ns blockchain infra apis frontend
```

Ver tambien: [`k8s-common.md#1-namespaces`](k8s-common.md#1-namespaces).

---

## 3. Desplegar blockchain local

```bash
./skaffold dev -p blockchain --namespace blockchain
# ./skaffold dev -p blockchain --namespace blockchain --cleanup=false
```

Verificaciones comunes:

- [`k8s-common.md#4-blockchain`](k8s-common.md#4-blockchain)

Logs directos:

```bash
kubectl logs -n blockchain -f geth-bootnode-0
kubectl logs -n blockchain -f geth-rpc-endpoint-0
kubectl logs -n blockchain -f geth-miner-0
```

Conectar al RPC:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555
```

Abrir RPC local:

```bash
kubectl port-forward svc/geth-rpc-endpoint 8555:8555 -n blockchain
```

---

## 4. Desplegar smart contract local

Atencion: si se despliega un contrato nuevo, revisar primero
[`k8s-common.md#5-smart-contract`](k8s-common.md#5-smart-contract).

Desplegar:

```bash
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth
```

Fondear cuentas desde geth:

```bash
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555
```

Ejemplo dentro de la consola:

```javascript
eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "0xa28885a13a7b4d3561a7af64ea1ba0f82ed9f06b",
  value: web3.toWei(10, "ether")
})
```

Inicializar categorias:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network privateGeth
npx hardhat run scripts/initCategories.js --network privateGeth
unset DEPLOYER_PRIVATE_KEY
```

---

## 5. Desplegar infraestructura local

```bash
./skaffold dev -p infra
./skaffold dev -p infra-basic
```

Servicios expuestos por Skaffold:

```text
Kafdrop: http://localhost:9000
Grafana: http://localhost:3000
Mongo Express: http://localhost:18081
```

Si se rompe el tunel de Mongo Express:

```bash
kubectl port-forward --address 0.0.0.0 -n infra svc/mongo-express 8081:8081
```

Despues de levantar MongoDB, ejecutar el bootstrap comun:

- [`k8s-common.md#6-mongodb-bootstrap`](k8s-common.md#6-mongodb-bootstrap)

---

## 6. Desplegar APIs y frontend local

```bash
./skaffold dev -p apis-frontend
# ./skaffold dev -p apis-frontend --cache-artifacts=true --cleanup=false
```

Estado:

```bash
kubectl get pods -n apis
kubectl get pods -n frontend
kubectl logs -n apis -f
```

El frontend ya no termina TLS ni proxifica `/backend` o `/auth`; esas rutas las publica Traefik mediante los manifiestos de `k8s/ingress`. El overlay local de ingress genera `trustnews-origin-tls` desde `web_classic/certs/fullchain.pem` y `web_classic/certs/privkey.pem`; en prod/Hetzner ese secret se crea manualmente segun el runbook server. En `kind`, Traefik debe estar instalado en el cluster antes de usar la entrada HTTPS local:

```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update

helm upgrade --install traefik traefik/traefik \
  --namespace kube-system \
  --set ingressClass.enabled=true \
  --set ingressClass.isDefaultClass=true \
  --set providers.kubernetesIngress.enabled=true \
  --set providers.kubernetesCRD.enabled=true
```

Comprobar que el controlador esta listo:

```bash
kubectl rollout status deployment/traefik -n kube-system
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
kubectl get ingress -A
```

Despues de levantar `./skaffold dev -p apis-frontend`, abrir el tunel local hacia Traefik:

```bash
kubectl port-forward --address 0.0.0.0 -n kube-system svc/traefik 7443:443
```

Mantener ese `port-forward` activo mientras se use la entrada web. Usar `https://localhost:7443` como `traefik-host`; el navegador puede mostrar aviso por certificado local.

URLs mediante Traefik:

```text
https://localhost:7443/
https://localhost:7443/backend/docs
https://localhost:7443/auth/admin/master/console/
```

No usar el port-forward directo al Service del frontend para validar la aplicacion completa: `kubectl port-forward svc/frontend-service -n frontend 7080:80` solo sirve los estaticos y deja fuera `/backend` y `/auth`.

Ver nginx del frontend:

```bash
kubectl exec -it -n frontend <frontend-pod> -- cat /etc/nginx/conf.d/default.conf
```

---

## 7. Secretos y configuracion local

Comprobar secretos:

```bash
kubectl get secrets -n infra
kubectl get secret mongodb-secret -n infra -o jsonpath='{.data}'
kubectl get secrets -n apis
kubectl get secret mongodb-app-secret -n apis -o jsonpath='{.data}'
```

Decodificar un valor:

```bash
echo "<valor-base64>" | base64 --decode
```

Keycloak via Traefik:

```bash
kubectl port-forward --address 0.0.0.0 -n kube-system svc/traefik 7443:443
```

Comprobacion:

```bash
curl -v -k https://localhost:7443/auth/admin/master/console
```

Configuracion comun de Keycloak y cuotas:

- [`k8s-common.md#7-keycloak-y-cuotas`](k8s-common.md#7-keycloak-y-cuotas)

---

## 8. Configuraciones funcionales

Evidence Search, perfiles de dominios y normalizacion:

- [`k8s-common.md#8-evidence-search`](k8s-common.md#8-evidence-search)

MongoDB, limpieza runtime y colecciones:

- [`k8s-common.md#9-mongodb-consultas-y-limpieza`](k8s-common.md#9-mongodb-consultas-y-limpieza)

---

## 9. Endpoints locales

| Servicio | URL | Perfil |
|---|---|---|
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
| Grafana | `http://localhost:3000` | `infra` |
| Mongo Express | `http://localhost:8081` | `infra` |
| Kafdrop | `http://localhost:9000` | `infra` |
| Keycloak Admin | `https://localhost:7443/auth/admin/master/console/` | `apis-frontend` |

---

## 10. Mantenimiento local

Limpiar imagenes no usadas dentro de nodos kind:

```bash
docker system df

for node in trust-news-control-plane trust-news-worker trust-news-worker2; do
  docker exec "$node" crictl rmi --prune || true
done
```

Borrar PVCs de infra solo si se reconstruye el entorno:

```bash
kubectl get pvc -n infra
kubectl delete pvc ipfs-storage-ipfs-0 -n infra
kubectl delete pvc kafka-data-kafka-0 -n infra
kubectl delete pvc mongodb-storage-mongodb-0 -n infra
```
