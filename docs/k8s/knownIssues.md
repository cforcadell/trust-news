# Known Issues & Troubleshooting - Guía de Operaciones



---

## 2. Blockchain (Geth)  Nodos aislados (peerCount == 0)
Los nodos no se encuentran automáticamente.

Solución:

Verificar estado:
```bash

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
Añadir peers manualmente (ejemplo):


kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("enode://<ENODE_ID>@<IP>:<PORT>")'
Problema: Acceso a Geth desde host local (Hardhat/Deploy)
Necesitas conectar tu máquina local al nodo RPC dentro de Kubernetes.

Solución:


# Abrir túnel SSH + Port Forwarding
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 8565:localhost:8555 sysadmin@135.181.80.57 -t "kubectl port-forward pod/geth-rpc-endpoint-0 -n blockchain 8555:8555"
Configuración en hardhat.config.js: url: "http://localhost:8565"
```


## 3. Despliegue y Registro (GitLab) Problema: ImagePullBackOff El clúster no puede descargar imágenes privadas de GitLab.

Solución:

Crear secreto de registro en el namespace correspondiente:

```bash
kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=<USER> \
  --docker-password=<TOKEN> \
  --docker-email=<EMAIL> \
  --namespace=<NS>
Aplicar al ServiceAccount:


kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=<NS>
```

## 4. Networking y Acceso Externo (Port-Forwarding)
Si los servicios no son accesibles, utiliza siempre port-forward con --address 0.0.0.0 para permitir conexiones externas si estás en una VM:
```bash
Frontend: kubectl port-forward svc/frontend-service -n frontend 7443:443 --address 0.0.0.0

Grafana: kubectl port-forward pod/grafana-xxxxx -n infra 3000:3000 --address 0.0.0.0

Keycloak: kubectl port-forward svc/keycloak -n infra 7443:8443 --address 0.0.0.0
```

## 5. Secretos y Variables
Problema: Verificar contenido de secretos
Si las APIs fallan al leer secretos, verifica que tengan los datos correctos.

Solución:

```bash
# Ver secretos en un namespace
kubectl get secrets -n <namespace>

# Ver datos de un secreto específico (ej: mongodb)
kubectl get mongodb-secret -n infra -o jsonpath='{.data}'

# Decodificar valor base64
echo "<VALOR_BASE64>" | base64 --decode
```

6. Procedimiento de Reinicio General
Si el sistema presenta comportamientos erráticos, escala todos los StatefulSets a 0 y luego a 1 para forzar una reconexión ordenada:

```bash
# Parar todo
kubectl scale statefulset --all --replicas=0 -n <namespace>

# Iniciar todo
kubectl scale statefulset --all --replicas=1 -n <namespace>
```

## 7. COnectividad entre contenedores
 ```bash
 kubectl exec -it ipfs-fastapi-7fd856fd48-4ksft -n apis -- bash

appuser@ipfs-fastapi-7fd856fd48-4ksft:/app$ timeout 2 bash -c "</dev/tcp/kafka.infra.svc.cluster.local/9092" && echo "Connection Successful" || echo "Connection Failed"
Connection Successful

 ```

 ## 8. Reiniciar cluster por problemas de mirrors en local al descargar imagenes 

```bash
docker stop $(docker ps -q --filter "label=io.x-k8s.kind.cluster")

sudo nano /etc/docker/daemon.json (ex: add "registry-mirrors": ["https://mirror.gcr.io"])

sudo systemctl restart docker 

docker start $(docker ps -a -q --filter "label=io.x-k8s.kind.cluster")

 ```

## 9. Reiniciar cluster por problemas de espacio
```bash 
 # Ver clusters Kind existentes
kind get clusters

# Borrar el cluster (esto elimina los 3 volúmenes gigantes)
kind delete cluster --name trust-news

# Recrearlo
kind create cluster --name trust-news --config kind-config.yaml

#ir limpiando por nodos
 docker exec <nodo-kind> crictl rmi --prune 

```

## 9. si han caido los nodos de blockchain y se han desincronizados.
```bash 

sysadmin@trust-news-prod:~/trust-news/scripts$ kubectl exec -it geth-miner-0 -n blockchain -- /bin/sh
Defaulted container "geth-miner" out of: geth-miner, init-blockchain (init)
/ # rm -rf /root/.ethereum/geth/chaindata
/ # rm /root/.ethereum/geth/nodekey # Opcional, fuerza a generar un nuevo ID de nodo
/ # exit

sysadmin@trust-news-prod:~/trust-news/scripts$ kubectl exec -it geth-rpc-enndpoint-0 -n blockchain -- /bin/sh
Defaulted container "geth-miner" out of: geth-miner, init-blockchain (init)
/ # rm -rf /root/.ethereum/geth/chaindata
/ # rm /root/.ethereum/geth/nodekey # Opcional, fuerza a generar un nuevo ID de nodo
/ # exit
```