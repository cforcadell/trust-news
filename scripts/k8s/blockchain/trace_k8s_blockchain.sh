#!/bin/bash

# 1. Recoger el directorio pasado por parámetro (si no le pasas nada, usa la carpeta actual '.')
DIRECTORIO=${1:-.}

# 2. Archivo de salida
ARCHIVO_SALIDA="./blockchain.trc"

clear

# Vaciamos el archivo si ya existe para empezar de cero
> "$ARCHIVO_SALIDA"

echo "Recolectando estado de los nodos..."

# 3. Volcar peerCount indicando el comando que se ejecuta
echo -e "\n# >>> COMANDO: kubectl exec geth-rpc-endpoint-0 -n blockchain -- geth attach --exec \"net.peerCount\"" >> "$ARCHIVO_SALIDA"
kubectl exec geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount" >> "$ARCHIVO_SALIDA" 2>&1

echo -e "\n# >>> COMANDO: kubectl exec geth-miner-0 -n blockchain -- geth attach --exec \"net.peerCount\"" >> "$ARCHIVO_SALIDA"
kubectl exec geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount" >> "$ARCHIVO_SALIDA" 2>&1

echo "Recolectando logs..."

# 4. Volcar logs indicando el comando que se ejecuta
echo -e "\n# >>> COMANDO: kubectl logs -n blockchain geth-bootnode-0" >> "$ARCHIVO_SALIDA"
kubectl logs -n blockchain geth-bootnode-0 >> "$ARCHIVO_SALIDA" 2>&1

echo -e "\n# >>> COMANDO: kubectl logs -n blockchain geth-rpc-endpoint-0" >> "$ARCHIVO_SALIDA"
kubectl logs -n blockchain geth-rpc-endpoint-0 >> "$ARCHIVO_SALIDA" 2>&1

echo -e "\n# >>> COMANDO: kubectl logs -n blockchain geth-miner-0" >> "$ARCHIVO_SALIDA"
kubectl logs -n blockchain geth-miner-0 >> "$ARCHIVO_SALIDA" 2>&1

echo "Buscando ficheros .yaml y .yml en: $DIRECTORIO"

echo -e "\n# >>> COMANDO: kubectl exec geth-bootnode-0 -n blockchain -- ps aux | grep geth" >> "$ARCHIVO_SALIDA"
kubectl exec geth-bootnode-0 -n blockchain -- ps aux | grep geth >> "$ARCHIVO_SALIDA"
echo -e "\n# >>> COMANDO: kubectl exec geth-rpc-endpoint-0 -n blockchain -- ps aux | grep geth" >> "$ARCHIVO_SALIDA"
kubectl exec geth-rpc-endpoint-0 -n blockchain -- ps aux | grep geth >> "$ARCHIVO_SALIDA"
echo -e "\n# >>> COMANDO: kubectl exec geth-miner-0 -n blockchain -- ps aux | grep geth" >> "$ARCHIVO_SALIDA"
kubectl exec geth-miner-0 -n blockchain -- ps aux | grep geth >> "$ARCHIVO_SALIDA"

# 5. Volcar manifiestos YAML
# find busca recursivamente. sort ordena los resultados alfabéticamente.
# find "$DIRECTORIO" -type f \( -name "*.yaml" -o -name "*.yml" \) | sort | while read -r archivo; do
#     echo "Agregando: $archivo"
    
#     # Escribimos la cabecera en el fichero de salida
#     echo -e "\n# ==========================================" >> "$ARCHIVO_SALIDA"
#     echo "# Archivo: $archivo" >> "$ARCHIVO_SALIDA"
#     echo "# ==========================================" >> "$ARCHIVO_SALIDA"
    
#     # Volcamos el contenido exacto del archivo
#     cat "$archivo" >> "$ARCHIVO_SALIDA"
    
#     # Añadimos un salto de línea y el separador estándar de YAML
#     echo -e "\n---\n" >> "$ARCHIVO_SALIDA"
# done

echo "¡Completado! Tienes toda la traza en $ARCHIVO_SALIDA"

# Imprimir el resultado final en pantalla
cat "$ARCHIVO_SALIDA"