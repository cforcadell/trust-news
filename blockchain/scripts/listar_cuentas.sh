#!/bin/bash

NODES=("geth-bootnode-container" "geth-rpc-container" "geth-miner-container")

echo "==============================================="
echo "   LISTADO DE CUENTAS DE LA RED PRIVADA GETH   "
echo "==============================================="
echo

for NODE in "${NODES[@]}"; do
    echo "➡️  Nodo: $NODE"

    # Verificar si está corriendo
    if ! docker ps --format '{{.Names}}' | grep -q "^${NODE}$"; then
        echo "   ⚠️  El nodo no está en ejecución."
        echo
        continue
    fi

    # Obtener listado de archivos del keystore
    FILES=$(docker exec "$NODE" sh -c "ls /root/.ethereum/keystore 2>/dev/null")

    if [ -z "$FILES" ]; then
        echo "   ❌ No hay cuentas en este nodo"
        echo
        continue
    fi

    # Procesar cada archivo del keystore
    echo "$FILES" | while IFS= read -r file; do
        ADDR=$(echo "$file" | sed -E 's/.*--([0-9a-fA-F]{40})/\1/')
        echo "   ✔ Cuenta: $ADDR"
    done

    # Detectar si es minero
    if docker exec "$NODE" ps aux | grep -q "\-\-mine"; then
        echo "   ⭐ Este nodo es un MINER / VALIDADOR"
    fi

    echo
done

echo "==============================================="
echo "     FIN DEL LISTADO DE CUENTAS DE LA RED      "
echo "==============================================="
