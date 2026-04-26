
#!/bin/bash
# Script para detener el cluster K3s de forma limpia

echo "--- [Iniciando detención del Cluster K3s] ---"

# 1. Avisar a los Pods que deben cerrarse (Graceful shutdown)
# Esto da tiempo a MongoDB/Kafka para vaciar el buffer a disco
echo "=> Vaciando carga del nodo (drain)..."
sudo kubectl drain $(hostname) --ignore-daemonsets --delete-emptydir-data --force --timeout=60s

# 2. Detener el servicio principal
echo "=> Deteniendo servicio k3s..."
sudo systemctl stop k3s

# 3. Limpieza profunda
# Esto desmonta volúmenes y limpia interfaces de red virtuales
if [ -f /usr/local/bin/k3s-killall.sh ]; then
    echo "=> Ejecutando k3s-killall (limpieza de contenedores y redes)..."
    sudo /usr/local/bin/k3s-killall.sh
else
    echo "=> Error: k3s-killall.sh no encontrado."
fi

echo "--- [Cluster detenido correctamente] ---"
