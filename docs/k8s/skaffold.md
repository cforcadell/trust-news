
**Skaffold**

```bash blockchain
./skaffold dev -p setup 
```

```bash blockchain

./skaffold dev -p blockchain --namespace blockchain 
# ./skaffold dev -p blockchain --namespace blockchain --cleanup=false


kubectl get pods -n blockchain

#see logs
kubectl logs -n blockchain -f geth-bootnode-0
kubectl logs -n blockchain -f geth-rpc-endpoint-0
kubectl logs -n blockchain -f geth-miner-0

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

>kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"


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

```

```bash infra

./skaffold dev -p apis-frontend


kubectl get pods -n apis

kubectl logs -n apis -f 


https://192.168.56.108:8443/

```