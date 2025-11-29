#!/bin/bash

RPC_URL="http://localhost:8555"
COUNTER=0

echo "==============================================="
echo "          BALANCES DE TODAS LAS CUENTAS        "
echo "==============================================="
echo

# Extraer cuentas de los keystores
ACCOUNTS=$(find ./volumes -type f -name "UTC--*" | awk -F'--' '{print $3}' )

for ACC in $ACCOUNTS; do
    echo "Cuenta: 0x$ACC"
    BAL=$(curl -s -X POST -H "Content-Type: application/json" \
      --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getBalance\",\"params\":[\"0x$ACC\",\"latest\"],\"id\":1}" \
      $RPC_URL | jq -r '.result')

    if [ "$BAL" == "null" ]; then
        echo "  ❌ Sin balance (cuenta no reconocida en blockchain)"
    else
        ETH=$(printf "%d\n" $((16#${BAL:2})) )
        echo "  Balance: $ETH wei"
    fi

    echo
done
