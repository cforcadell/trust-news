**Just one shot execution**
```bash infra inside server 
scripts/create-namespaces.sh

secrets/create-secrets.sh

touch worker-1.env worker-2.env worker-3.env generate-asertions.env news-chain.env news-handler.env mongodb.env
chmod 600 *.env

kubectl create secret generic validator-secret-1 --from-env-file=worker-1.env -n apis
kubectl create secret generic validator-secret-2 --from-env-file=worker-2.env -n apis
kubectl create secret generic validator-secret-3 --from-env-file=worker-3.env -n apis

kubectl create secret generic api-keys --from-env-file=generate-asertions.env -n apis

kubectl create secret generic news-chain-secrets --from-env-file=news-chain.env -n apis

kubectl create secret generic news-handler-secrets --from-env-file=news-handler.env -n apis

kubectl create secret generic gate-config --from-env-file=gateway.env -n apis


kubectl create secret generic mongodb-secret --from-env-file=mongodb.env -n infra

kubectl create secret generic keycloak-admin-secret --from-env-file=keycloak.env -n infra

kubectl create secret generic ethereum-secrets  --from-env-file=ethereum.env -n blockchain



#kubectl create secret tls frontend-tls \
#  --cert=./web_classic/certs/fullchain.pem \
#  --key=./web_classic/certs/privkey.pem \
#  -n frontend

```
**Deploy blockchain resources**
#use apipeline with PROFILE=blockchain-prod and check peers

kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"

**Deploy contract using ssh tunnel**


```bash blockchain ~/blockchain/hetzner/keys-github
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 8565:localhost:8555 sysadmin@135.181.80.57 -t "kubectl port-forward pod/geth-rpc-endpoint-0 -n blockchain 8555:8555"


```

Add hardhat.config.js entry for cloud blockchain

    cloudGeth: {
      url: "http://localhost:8565", 
      accounts: [
        "0x*********************************"
      ],
      gas: 25_000_000,
      chainId: 1214
    }

```bash blockchain from hardhat
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network cloudGeth

#get contract address and configure apis
```

```bash blockchain inside server

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555

eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "0xa28885a13a7b4d3561a7af64ea1ba0f82ed9f06b",
  value: web3.toWei(10, "ether")
})


eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "4504a1d4047583164919ae40c37c4f4c5b854bbb",
  value: web3.toWei(10, "ether")
})


eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "edbef53fc17dde65bf303b3d4983afb7028eb6eb",
  value: web3.toWei(10, "ether")
})


eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "be794abf86d173ddcfe937c6d8d739bdc4e94165",
  value: web3.toWei(10, "ether")
})


eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "42d488d0393fd1d6b72bb424db28dd7eb5e06737",
  value: web3.toWei(10, "ether")
})

```


```bash infra

#use actions deploy workflow


kubectl get pods -n infra


kubectl logs -n infra -f kafka-0


#si al parar los pods a replicas=0 o eliminar los statefuls quedan pvcs
kubectl get pvc -n infra
kubectl delete pvc ipfs-storage-ipfs-0 -n infra
kubectl delete pvc kafka-data-kafka-0 -n infra
kubectl delete pvc mongodb-storage-mongodb-0 -n infra

```



```bash tunnel apis ~/blockchain/hetzner/keys-github
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 9443:127.0.0.1:10443 sysadmin@135.181.80.57 "kubectl port-forward pod/frontend-web-75b7d945cb-bg2bh -n frontend 10443:443 --address 0.0.0.0"

https://localhost:9443/
```

kubectl get pods -n infra
**start/stop pods**
```bash 

kubectl scale statefulset --all --replicas=0 -n infra blockchain 
kubectl scale statefulset --all --replicas=1 -n infra blockchain 

```
```bash tunnel grafana ~/blockchain/hetzner/keys-github
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 3300:127.0.0.1:3300 sysadmin@135.181.80.57 "kubectl port-forward pod/grafana-7964997b9b-skqjw -n infra 3000:3000 --address 0.0.0.0"

http://localhost:3300/

#Add datasource in grafana: http://loki.infra.svc.cluster.local:3100

Explore + Run query

#change inside hetzner. ex: bootnode
kubectl edit statefulset geth-bootnode -n blockchain
```
```bash gitlab secrets create-secrets-gitlab.sh
kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username= \
  --docker-password= \
  --docker-email= \
  --namespace=apis

kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username= \
  --docker-password= \
  --docker-email= \
  --namespace=infra
kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username= \
  --docker-password= \
  --docker-email= \
  --namespace=blockchain
kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username= \
  --docker-password= \
  --docker-email= \
  --namespace=frontend


kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=apis

kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=infra

kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=blockchain

kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=frontend
```


```bash problemas de connection refused en descargar imágenes (Ej: python:3.11-slim )
docker pull mirror.gcr.io/library/python:3.11-slim

docker tag mirror.gcr.io/library/python:3.11-slim python:3.11-slim
```
