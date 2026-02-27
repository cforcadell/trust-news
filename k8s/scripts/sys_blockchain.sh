#!/bin/bash

NAMESPACE="blockchain"
ACTION=$1

if [ "$ACTION" == "start" ]; then
    echo "🚀 Iniciando red Blockchain..."
    kubectl scale statefulset geth-bootnode --replicas=1 -n $NAMESPACE
    kubectl scale statefulset geth-rpc-endpoint --replicas=1 -n $NAMESPACE
    kubectl scale statefulset geth-miner --replicas=1 -n $NAMESPACE
    echo "✅ Red escalada a 1. Comprueba el estado con: kubectl get pods -n $NAMESPACE"

elif [ "$ACTION" == "stop" ]; then
    echo "🛑 Deteniendo red Blockchain (Escalando a 0)..."
    kubectl scale statefulset geth-bootnode --replicas=0 -n $NAMESPACE
    kubectl scale statefulset geth-rpc-endpoint --replicas=0 -n $NAMESPACE
    kubectl scale statefulset geth-miner --replicas=0 -n $NAMESPACE
    echo "💤 Red detenida. Los datos persistirán si usas PVC."

elif [ "$ACTION" == "status" ]; then
    kubectl get pods -n $NAMESPACE
    echo "---"
    kubectl get svc -n $NAMESPACE

else
    echo "Uso: ./manage_network.sh [start|stop|status]"
fi