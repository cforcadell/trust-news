#!/bin/bash

echo "Introduce una contraseña para la nueva cuenta:"
read -s PASS

docker exec -i geth-rpc-container geth --datadir /root/.ethereum account new << EOF
$PASS
$PASS
EOF
echo "Cuenta creada en el nodo geth-rpc-container"