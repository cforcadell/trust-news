
**Skaffold**

```bash blockchain
#./skaffold dev -p setup 
```

```bash blockchain

./skaffold dev -p blockchain --namespace blockchain 
# ./skaffold dev -p blockchain --namespace blockchain --cleanup=false


kubectl get pods -n blockchain

#see logs
kubectl logs -n blockchain -f geth-bootnode-0
kubectl logs -n blockchain -f geth-rpc-endpoint-0
kubectl logs -n blockchain -f geth-miner-0

#see geth processes

kubectl exec geth-bootnode-0 -n blockchain -- ps aux | grep geth
kubectl exec geth-rpc-endpoint-0 -n blockchain -- ps aux | grep geth
kubectl exec geth-miner-0 -n blockchain -- ps aux | grep geth

#analyze if node have been initialized or not

 kubectl describe pod geth-bootnode-0 -n blockchain
 kubectl describe pod geth-rpc-endpoint-0 -n blockchain
 kubectl describe pod geth-miner-0 -n blockchain

#connect rpc node 
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555

> admin.peers
> net.peerCount
> eth.blockNumber

#alernativa
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "admin.peers"
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "eth.blockNumber"

#connect boot node 
kubectl exec -it geth-bootnode-0 -n blockchain -- ps aux
#get enode
kubectl exec -it geth-bootnode-0 -n blockchain -- geth --exec "admin.nodeInfo.enode" attach ipc:/root/.ethereum/geth.ipc

#connect miner node 
kubectl exec -it geth-miner-0 -n blockchain -- geth attach
> admin.peers
> net.peerCount
> eth.blockNumber

kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "admin.peers"
kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "eth.blockNumber"

# check that net.peerCount ==1 in rpc & miner node and check that eth.blockNumber in both nodes are equal
#connect manually two nodes

>kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'admin.addPeer("enode://af28ee328bbab1085d8f3e6eef110001a4075da8513871091bb25c7111f57e4261270b26791b5d71d6fd9707c1efd4ca17db2010b73fcd7ff1c7cd3a6877531c@10.244.2.13:30304")'4")'

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"


#restart blockchain keepong stateful and volumes
kubectl scale statefulset geth-bootnode --replicas=0 -n blockchain
kubectl scale statefulset geth-miner --replicas=0 -n blockchain
kubectl scale statefulset geth-rpc-endpoint --replicas=0 -n blockchain

kubectl scale statefulset --all --replicas=0 -n blockchain
kubectl scale statefulset --all --replicas=1 -n blockchain

kubectl get pods -n blockchain

kubectl get pv  -n blockchain

```



```bash deploy contract
#to allow access through localhost
kubectl port-forward svc/geth-rpc-endpoint 8555:8555 -n blockchain

cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth

#fund

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



eth.pendingTransactions

eth.getBalance("0xa28885a13a7b4d3561a7af64ea1ba0f82ed9f06b")

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getCode("0x9eA62eb7944349C407B307025644E47bF22F8bCc")'

```


```bash infra

./skaffold dev -p infra

kubectl scale statefulset --all --replicas=0 -n infra
kubectl scale statefulset --all --replicas=1 -n infra

kubectl get pods -n infra


kubectl logs -n infra -f kafka-0


#si al parar los pods a replicas=0 o eliminar los statefuls quedan pvcs
kubectl get pvc -n infra
kubectl delete pvc ipfs-storage-ipfs-0 -n infra
kubectl delete pvc kafka-data-kafka-0 -n infra
kubectl delete pvc mongodb-storage-mongodb-0 -n infra


```

```bash keycloak
keycloak (sin ir por nginx):

#si no lo abre skaffold
kubectl port-forward svc/keycloak --address 0.0.0.0 -n infra 7443:8443

curl -v -k https://localhost:7443/auth/admin/master/console

https://localhost:7443/auth/admin/master/console/


```

Crea el Realm: * Haz clic en el desplegable de arriba a la izquierda (Master) y dale a Create Realm.

Nombre: TrustNews.

Crea el Cliente para la Web (Frontend):

Clients -> Create client.

ClientID: TrustNewsWeb.

Root URL: https://localhost:7443 (o la URL de tu frontend).
Valid redirect: https://localhost:7443/*

Web Origins: * (para evitar problemas de CORS en desarrollo).

Crea el Cliente para los Backends Públicos (Lo que pediste al inicio):

Clients -> Create client.

ClientID: TrustNewsApi.

Client Authentication: Ponlo en ON.

Authorization: Ponlo en OFF.

Authentication Flow: Marca solo Service accounts roles (desmarca el resto). 

Una vez guardado, ve a la pestaña Credentials y ahí verás el Client Secret que necesitarán los backends externos para llamarte.

En realm settings (TrustNews)
Frontend URL: https://localhost:7443/auth/

Craer usuario p federetad identity

```bash apis + frontend

./skaffold dev -p apis-frontend  --cache-artifacts=false --cleanup=false


kubectl get pods -n apis
kubectl get pods -n frontend

kubectl logs -n apis -f 

Frontend:
#si no se levanta el port forward
kubectl port-forward svc/frontend-service -n frontend 7443:443
#verify nginx config
kubectl exec -it -n frontend frontend-web-5769696f49-dljlk -- cat /etc/nginx/conf.d/default.conf
#realm console
https://localhost:7443/auth/admin/master/console/


#https://192.168.56.108:7443/
#con mapeo de host a vm
https://localhost:7443/

grafana:
http://localhost:3000/

https://localhost:7443/backend/docs


keycloak realm master 
https://localhost:7443/auth/admin/master/console/

#get token 
curl -k -X POST https://localhost:7443/auth/realms/TrustNews/protocol/openid-connect/token -H "Content-Type: application/x-www-form-urlencoded" -d "grant_type=client_credentials" -d "client_id=TrustNewsApi" -d "client_secret=xxxxx"

| Service | URL |
|--------|-----|
| Frontend | http://127.0.0.1:8000 |
| Admin | http://127.0.0.1:8400 |
| IPFS API | http://127.0.0.1:8060/docs |
| News Handler | http://127.0.0.1:8072/docs |
| Assertion Generator | http://127.0.0.1:8071/docs |
| News Chain | http://127.0.0.1:8073/docs |
| Validator Worker 1 | http://127.0.0.1:8070/docs |
| Validator Worker 2 | http://127.0.0.1:8069/docs |

---



get svc -n infra

#Add datasource in grafana: http://loki.infra.svc.cluster.local:3100

Explore + Run query

```
```bash  get secret details 

kubectl get secrets -n infra
kubectl get mongodb-secret -n infra -o jsonpath='{.data}'


kubectl get secrets -n apis
kubectl get secret news-handler-secrets -n apis -o jsonpath='{.data}'
echo "x" | base64 --decode

kubectl exec -it mongodb-0 -n infra -- mongo -u root -p cforcadellm --authenticationDatabase admin

```