#!/bin/bash

if [ -z "$1" ]; then
    echo "Uso: $0 <clave_privada_hex>"
    exit 1
fi

KEY=$1

echo "Introduce una contraseña para proteger la clave:"
read -s PASS

docker exec -i geth-rpc-container geth --datadir /root/.ethereum account import << EOF
$KEY
$PASS
$PASS
EOF
