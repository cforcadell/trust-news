#!/bin/bash

NAMESPACE="infra"
# Lista de servicios en el namespace infra
SERVICIOS=("ipfs" "kafka" "mongodb" "zookeeper")

ACTION=$1

case "$ACTION" in
    "start")
        echo "🚀 Levantando infraestructura de soporte ($NAMESPACE)..."
        for svc in "${SERVICIOS[@]}"; do
            echo "   -> Iniciando $svc..."
            kubectl scale statefulset "$svc" --replicas=1 -n $NAMESPACE
        done
        echo "✅ Comandos enviados. Revisa el progreso con: ./manage_infra.sh status"
        ;;
    "stop")
        echo "🛑 Apagando infraestructura ($NAMESPACE)..."
        for svc in "${SERVICIOS[@]}"; do
            echo "   -> Deteniendo $svc..."
            kubectl scale statefulset "$svc" --replicas=0 -n $NAMESPACE
        done
        echo "💤 Infraestructura detenida."
        ;;
    "status")
        echo "📊 Estado de los pods en '$NAMESPACE':"
        kubectl get pods -n $NAMESPACE -o wide
        ;;
    *)
        echo "Uso: ./manage_infra.sh [start|stop|status]"
        exit 1
        ;;
esac