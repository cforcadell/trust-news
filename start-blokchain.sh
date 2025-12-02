#!/bin/bash
set -e

VOLUME_DIR="./volumes/geth"
PASSWORD=${ACCOUNT_PASSWORD:-5uper53cr3t}  # Por defecto si no está en .env

# Crear el volume si no existe
mkdir -p "$VOLUME_DIR"

# Comprobar si existe alguna cuenta en el keystore
if [ -z "$(ls -A $VOLUME_DIR/keystore 2>/dev/null)" ]; then
    echo "No se encontraron cuentas. Creando una nueva cuenta Ethereum..."
    
    # Crear archivo temporal con la contraseña
    PASS_FILE="$VOLUME_DIR/pass.txt"
    echo "$PASSWORD" > "$PASS_FILE"
    
    # Ejecutar geth dentro de un contenedor temporal
    docker run --rm -v "$(pwd)/volumes/geth:/root/.ethereum" ethereum/client-go:v1.10.1 \
        account new --password /root/.ethereum/pass.txt
    
    # Borrar archivo de contraseña
    rm "$PASS_FILE"
    echo "Cuenta creada correctamente."
else
    echo "Cuenta Ethereum ya existente en $VOLUME_DIR/keystore"
fi

# Levantar los contenedores
docker compose -f docker-compose.blockchain.yml up -d

