#!/bin/bash

CONTRATO=$1
CUENTA=$2
PASS=$3

if [ -z "$CONTRATO" ] || [ -z "$CUENTA" ] || [ -z "$PASS" ]; then
    echo "Uso: $0 <archivo.sol> <cuenta> <password>"
    exit 1
fi

echo "Compilando contrato..."
solc --combined-json abi,bin $CONTRATO -o /tmp --overwrite
ABI=$(cat /tmp/combined.json | jq -r '.contracts[] .abi')
BIN=$(cat /tmp/combined.json | jq -r '.contracts[] .bin')

echo "Desbloqueando cuenta..."
curl -s -X POST -H "Content-Type: application/json" \
  --data "{\"jsonrpc\":\"2.0\",\"method\":\"personal_unlockAccount\",\"params\":[\"$CUENTA\",\"$PASS\",30],\"id\":1}" \
  http://localhost:8555 > /dev/null

echo "Enviando transacción de despliegue..."
TX=$(curl -s -X POST -H "Content-Type: application/json" \
  --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_sendTransaction\",\"params\":[{\"from\":\"$CUENTA\",\"data\":\"0x$BIN\"}],\"id\":1}" \
  http://localhost:8555 | jq -r '.result')

echo "TX Hash: $TX"
echo "Esperando receipt..."

sleep 8

RECEIPT=$(curl -s -X POST -H "Content-Type: application/json" \
  --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getTransactionReceipt\",\"params\":[\"$TX\"],\"id\":1}" \
  http://localhost:8555)

echo "Receipt:"
echo "$RECEIPT"
