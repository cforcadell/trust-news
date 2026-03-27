#!/bin/bash

# 1. Recoger el directorio pasado por parámetro (si no le pasas nada, usa la carpeta actual '.')
DIRECTORIO=${1:-.}

# 2. Archivo de salida
ARCHIVO_SALIDA="./infra.trc"

clear

# Vaciamos el archivo si ya existe para empezar de cero
> "$ARCHIVO_SALIDA"



# 5. Volcar manifiestos YAML
find busca recursivamente. sort ordena los resultados alfabéticamente.
find "$DIRECTORIO" -type f \( -name "*.yaml" -o -name "*.yml" \) | sort | while read -r archivo; do
    echo "Agregando: $archivo"
    
    # Escribimos la cabecera en el fichero de salida
    echo -e "\n# ==========================================" >> "$ARCHIVO_SALIDA"
    echo "# Archivo: $archivo" >> "$ARCHIVO_SALIDA"
    echo "# ==========================================" >> "$ARCHIVO_SALIDA"
    
    # Volcamos el contenido exacto del archivo
    cat "$archivo" >> "$ARCHIVO_SALIDA"
    
    # Añadimos un salto de línea y el separador estándar de YAML
    echo -e "\n---\n" >> "$ARCHIVO_SALIDA"
done

echo "¡Completado! Tienes toda la traza en $ARCHIVO_SALIDA"

# Imprimir el resultado final en pantalla
cat "$ARCHIVO_SALIDA"