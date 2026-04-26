#!/bin/bash

# 1. Validar que se pasa el número de réplicas
if [ -z "$1" ]; then
  echo "❌ Error: Falta indicar el número de réplicas."
  echo "💡 Uso: $0 <numero_de_replicas> [namespace1 namespace2 ...]"
  echo ""
  echo "Ejemplos:"
  echo "  Apagar todo:               $0 0"
  echo "  Encender todo (1 réplica): $0 1"
  echo "  Apagar solo apis y frontend: $0 0 apis frontend"
  exit 1
fi

REPLICAS=$1
shift # Desplaza los argumentos para quedarnos solo con los namespaces (si los hay)

# 2. Configurar los namespaces (los tuyos por defecto o los indicados por consola)
if [ $# -eq 0 ]; then
  NAMESPACES=("apis" "blockchain" "frontend" "infra")
else
  NAMESPACES=("$@")
fi

# 3. Ejecutar el escalado
echo "⚙️  Escalando Deployments y StatefulSets a $REPLICAS réplica(s)..."

for ns in "${NAMESPACES[@]}"; do
  echo "----------------------------------------"
  echo "📦 Namespace: $ns"

  # Escalar Deployments
  echo "   -> Ajustando Deployments..."
  kubectl scale deployment --all --replicas="$REPLICAS" -n "$ns" 2>/dev/null || echo "      (No hay Deployments aquí)"

  # Escalar StatefulSets
  echo "   -> Ajustando StatefulSets..."
  kubectl scale statefulset --all --replicas="$REPLICAS" -n "$ns" 2>/dev/null || echo "      (No hay StatefulSets aquí)"
done

echo "----------------------------------------"
echo "✅ ¡Orden enviada! Todos los servicios en los namespaces indicados se están ajustando a $REPLICAS réplicas."
