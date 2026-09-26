# Know Issues & Troubleshooting - Operations Guide

> [!WARNING]
> **ARCHIVADO — NOT USE.** Historical reference; see
> [`README.md`](README.md) and runbooks are in place before operation.


---

## 2. Blockchain (Geth)  Nodos aislados (peerCount == 0)
Nodes are not automatically found.

Solution:

Check status:
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


## 3. Deployment and Registration (GitLab) Problem: ImagePullBackOff The cluster cannot download private images from GitLab.

Solution:

Create registration secret in the corresponding namespace:

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

## 4. Networking and External Access (Port-Forwarding)
If services are not accessible, always use port-forward with --address 0.0.0.0 to allow external connections if you are in a VM:
```bash
Frontend: kubectl port-forward svc/frontend-service -n frontend 7443:443 --address 0.0.0.0

Grafana: kubectl port-forward pod/grafana-xxxxx -n infra 3000:3000 --address 0.0.0.0

Keycloak: kubectl port-forward svc/keycloak -n infra 7443:8443 --address 0.0.0.0
```

## 5. Secrets and Variables
Problem: Verify Secret Content If APIs fail to read secrets, check that they have the correct data.

Solution:

```bash
# Ver secretos en un namespace
kubectl get secrets -n <namespace>

# Ver datos de un secreto específico (ej: mongodb)
kubectl get mongodb-secret -n infra -o jsonpath='{.data}'

# Decodificar valor base64
echo "<VALOR_BASE64>" | base64 --decode
```

6. Restart procedure
If the system presents erratic behaviors, scale all StatefulSets to 0 and then to 1 to force an orderly reconnection:

```bash
# Parar todo
kubectl scale statefulset --all --replicas=0 -n <namespace>

# Iniciar todo
kubectl scale statefulset --all --replicas=1 -n <namespace>
```

## 7. Container connectivity
 ```bash
 kubectl exec -it ipfs-fastapi-7fd856fd48-4ksft -n apis -- bash

appuser@ipfs-fastapi-7fd856fd48-4ksft:/app$ timeout 2 bash -c "</dev/tcp/kafka.infra.svc.cluster.local/9092" && echo "Connection Successful" || echo "Connection Failed"
Connection Successful

 ```

 ## 8. Restart cluster due to local mirror problems when downloading images

```bash
docker stop $(docker ps -q --filter "label=io.x-k8s.kind.cluster")

sudo nano /etc/docker/daemon.json (ex: add "registry-mirrors": ["https://mirror.gcr.io"])

sudo systemctl restart docker 

docker start $(docker ps -a -q --filter "label=io.x-k8s.kind.cluster")

 ```

## 9. Restart cluster due to space problems
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

## 9. if the blockchain nodes have fallen and have been desync.
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
