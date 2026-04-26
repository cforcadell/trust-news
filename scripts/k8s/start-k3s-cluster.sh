#!/bin/bash
# Script para levantar y verificar el cluster K3s

echo "--- [Iniciando el Cluster K3s] ---"

# 1. Arrancar el servicio
sudo systemctl start k3s

# 2. Esperar a que el API Server esté listo
echo "=> Esperando a que el API Server responda..."
until sudo kubectl get nodes &> /dev/null; do
  printf "."
  sleep 2
done
echo " ¡Listo!"

# 3. Volver a habilitar el nodo para recibir Pods
echo "=> Rehabilitando nodo (uncordon)..."
sudo kubectl uncordon $(hostname)

# 4. Verificación de servicios críticos
echo "=> Verificando estado de namespaces..."
echo "--------------------------------------------------------"
printf "%-20s %-10s %-10s\n" "NAMESPACE" "TOTAL" "READY"
for ns in infra blockchain apis frontend; do
    total=$(kubectl get pods -n $ns --no-headers 2>/dev/null | wc -l)
    ready=$(kubectl get pods -n $ns --no-headers 2>/dev/null | grep "Running" | wc -l)
    printf "%-20s %-10s %-10s\n" "$ns" "$total" "$ready"
done
echo "--------------------------------------------------------"

echo "--- [Cluster operativo] ---"

