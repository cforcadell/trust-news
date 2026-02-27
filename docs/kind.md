
**Crear el cluster:**
```bash
kind create cluster --config kind-config.yaml
```
Puede tardar un rato...

Creating cluster "trust-news" ...
 ✓ Ensuring node image (kindest/node:v1.29.2) 🖼 
 ✓ Preparing nodes 📦 📦 📦  
 ✓ Writing configuration 📜 
 ✓ Starting control-plane 🕹️ 
 ✓ Installing CNI 🔌 
 ✓ Installing StorageClass 💾 
 ✓ Joining worker nodes 🚜 

```bash
kubectl get nodes
```

**Estructura Kubernettes:**
```bash

```

**Aplicar Namespaces**

```bash
kubectl apply -f k8s/namespaces.yaml
kubectl get ns
```

**Verificar StorageClass**
```bash
kubectl get storageclass
```

**mongodb**

```bash

kubectl create secret generic mongodb-secret \
  --from-literal=MONGO_INITDB_ROOT_USERNAME=root \
  --from-literal=MONGO_INITDB_ROOT_PASSWORD=********* \
  -n infra

kubectl apply -f k8s/infra/mongodb/service.yaml
kubectl apply -f k8s/infra/mongodb/statefulset.yaml

kubectl get pods -n infra
kubectl logs mongodb-0 -n infra
kubectl exec -it mongodb-0 -n infra -- mongo -u root -p XXXXXXXX --authenticationDatabase admin
```

kubectl exec -it mongodb-0 -n infra -- mongo -u root -p cforcadellm --authenticationDatabase admin

**ipfs**
```bash


kubectl apply -f k8s/infra/ipfs/service.yaml
kubectl apply -f k8s/infra/ipfs/statefulset.yaml

kubectl get pods -n infra
kubectl logs ipfs-0 -n infra
```

**Zookeeper**
```bash


kubectl apply -f k8s/infra/zookeeper/configmap.yaml
kubectl apply -f k8s/infra/zookeeper/service.yaml
kubectl apply -f k8s/infra/zookeeper/statefulset.yaml

kubectl get pods -n infra
kubectl logs zookeeper-0 -n infra
```

**kafka**
```bash

kubectl apply -f k8s/infra/kafka/service.yaml
kubectl apply -f k8s/infra/kafka/statefulset.yaml


kubectl get pods -n infra

kubectl logs kafka-0 -n infra

kubectl get svc -n infra

 kubectl get pods,secrets,pvc,configmaps,svc -n infra
```


**blockchain**
```bash
kubectl apply -f k8s/blockchain/configmap.yaml -f k8s/blockchain/secret-template.yaml -f k8s/blockchain/ethereum-keystores.yaml
# (Variables y cuentas).

kubectl apply -f k8s/blockchain/bootnode/service.yaml -f k8s/blockchain/bootnode/statefulset.yaml 
#(Levantas el faro de la red).

#Esperas a que el bootnode esté en estado Running.

kubectl apply -f k8s/blockchain/rpc/service.yaml -f k8s/blockchain/rpc/statefulset.yaml 
#(Levantas el RPC).

kubectl apply -f k8s/blockchain/validator/service.yaml -f k8s/blockchain/validator/statefulset.yaml 
#(Levantas el minero).

kubectl get pods -n blockchain

kubectl logs geth-bootnode-0 -n blockchain

kubectl logs geth-rpc-endpoint-0 -n blockchain
kubectl logs geth-miner-0 -n blockchain

#new terminal
kubectl port-forward service/geth-rpc-endpoint 8545:8555 -n blockchain

#current term (review before hardhat.config.js)
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth
```

**apis**
```bash
kubectl create namespace apis

#generate assertions

kubectl create secret generic api-keys \
  --from-literal=OPENROUTER_API_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXX \
  -n apis

kind load docker-image tfm-generate-asertions:latest --name trust-news

# Aplicar todo el contenido de la carpeta
kubectl apply -f k8s/apis/generate-asertions/ -n apis

# Verificar que el pod está corriendo
kubectl get pods -n apis

kubectl logs -f deployment/generate-asertions -n apis --tail=20

#new terminal
kubectl port-forward deployment/generate-asertions 8071:8071 -n apis

#local browser
http://localhost:8071/docs


#ipfs-fastapi

kind load docker-image tfm-ipfs-fastapi:latest --name trust-news

kubectl apply -f k8s/apis/ipfs-fastapi/ -n apis

kubectl get pods -n apis

kubectl logs -f deployment/ipfs-fastapi -n apis

#new terminal
kubectl port-forward deployment/ipfs-fastapi 8060:8060 -n apis

#local browser
http://localhost:8060/docs


#news-chain

kind load docker-image tfm-news-chain:latest --name trust-news

kubectl create secret generic news-chain-secrets \
  --from-literal=PRIVATE_KEY='xxxxxxxxxxxxxxxxxxxxxxxx' \
  -n apis

kubectl create configmap news-chain-contract \
  --from-file=TrustNews.json=./smart-contracts/artifacts/contracts/TrustNews.sol/TrustNews.json \
  -n apis

kubectl apply -f k8s/apis/news-chain/ -n apis

kubectl get pods -n apis

kubectl logs -f deployment/news-chain -n apis

kubectl rollout restart deployment news-chain -n apis


#para ver detalles del pod
kubectl describe pod news-chain-5d7b789cf9-r59sb -n apis

#validators

kind load docker-image tfm-validate-asertions:latest --name trust-news

#Para cada validador
# Para el validador 1
kubectl create secret generic validator-1-secret \
  --from-literal=PRIVATE_KEY=XXXXX \
  --from-literal=ACCOUNT_ADDRESS=0x4504A1... \
  --from-literal=API_KEY=XXXXX \
  -n apis

# Repetir para validador 2, 3... n


kubectl apply -f k8s/apis/validate-asertions/ -n apis

kubectl get pods -n apis

#para ver detalles del pod
kubectl describe pod validate-worker-1-588dcfd9bc-fm9lv -n apis

kubectl logs -f deployment/validate-worker-1 -n apis

#nws-handler

kind load docker-image tfm-news-handler:latest --name trust-news

kubectl create secret generic news-handler-secrets \
  --from-literal=MONGO_URI='mongodb://root:xxxxxxx@mongodb.infra.svc.cluster.local:27017' \
  -n apis

kubectl apply -f k8s/apis/news-handler/ -n apis

kubectl get pods -n apis

kubectl logs -f deployment/news-handler -n apis

  ```

  **frontend**

```bash

kubectl create namespace frontend

kind load docker-image tfm-frontend-web_classic:latest --name trust-news

kubectl create secret tls frontend-tls \
  --cert=./web_classic/certs/fullchain.pem \
  --key=./web_classic/certs/privkey.pem \
  -n frontend

# 2. El ConfigMap del Nginx
kubectl create configmap nginx-config \
  --from-file=default.conf=./web_classic/nginx_k8s.conf \
  -n frontend

kubectl apply -f k8s/frontend/ -n frontend

kubectl get pods -n frontend

kubectl logs -f deployment/frontend -n frontend

#nueva sesion
kubectl port-forward service/frontend-service 30443:443 -n frontend --address 0.0.0.0


#local
https://192.168.56.108:30443/
```