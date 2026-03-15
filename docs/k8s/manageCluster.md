  **stop cluster**

```bash

# Para la blockchain
kubectl scale statefulset --all --replicas=0 -n blockchain
# Para la infraestructura (Kafka, Mongo, etc.)
kubectl scale statefulset --all --replicas=0 -n infra

# Detener los nodos de Kind (Docker)
docker stop trust-news-control-plane trust-news-worker trust-news-worker2

```
```bash
# 1. Arrancar nodos
kubectl get nodes
# si falla
docker start trust-news-control-plane trust-news-worker trust-news-worker2

# 2. Relanzar Skaffold (él detectará los PVCs existentes y los reusará)
./skaffold dev -p blockchain
./skaffold dev -p infra

# Combinado para ver si hay peers y si el bloque sube
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "console.log('Peers:', net.peerCount); console.log('Bloque:', eth.blockNumber)"
```