# Ejemplo: optimizar configuraciones LLM con un máximo de 0,05 USD

Este procedimiento genera y ejecuta perfiles LLM bajo un coste máximo estimado
de 0,05 USD por noticia usando el benchmark histórico.

No ejecutar contra producción. El runner modifica temporalmente la configuración
LLM, consume cuota y restaura la configuración al finalizar.

## 1. Variables de entorno

Desde la raíz del repositorio:

    cd /home/adminu/blockchain/tfm

Configura el Gateway local y el cliente de servicio de Keycloak:

    export ASSERMETRY_API_URL='https://localhost:7443/backend'
    export ASSERMETRY_TLS_VERIFY=false
    export ASSERMETRY_KEYCLOAK_REALM='TrustNews'
    export ASSERMETRY_KEYCLOAK_CLIENT_ID='TrustNewsApi'

Introduce el secreto sin escribirlo en el historial del shell:

    read -rsp 'TrustNewsApi client secret: ' ASSERMETRY_KEYCLOAK_CLIENT_SECRET
    export ASSERMETRY_KEYCLOAK_CLIENT_SECRET
    echo

Para forzar el flujo `client_credentials`, no definas un token estático ni
credenciales de usuario:

    unset ASSERMETRY_ACCESS_TOKEN
    unset ASSERMETRY_USERNAME
    unset ASSERMETRY_PASSWORD

El script solicita el token en el endpoint OpenID Connect con:

    grant_type=client_credentials
    client_id=TrustNewsApi

El secreto no se guarda en los artefactos del benchmark.

## 2. Generar perfiles bajo presupuesto

Genera un plan con un máximo solicitado de 0,05 USD y un margen del 5 %:

    python3 tests/llm-benchmark/llm-benchmark.py generate-profiles \
      --max-news-cost-usd 0.05 \
      --budget-headroom-percent 5 \
      --output-root tests/llm-benchmark/artifacts/generated

El máximo efectivo será 0,0475 USD. El comando imprime una ruta como:

    LLM_PROFILE_PLAN tests/llm-benchmark/artifacts/generated/openrouter-plan-.../plan.json

Guarda esa ruta en una variable:

    export PLAN_PATH='tests/llm-benchmark/artifacts/generated/openrouter-plan-.../plan.json'
    export PLAN_DIR="$(dirname "$PLAN_PATH")"

Revisa los perfiles aceptados y descartados:

    sed -n '1,260p' "$PLAN_PATH"

El plan conserva la configuración efectiva, el snapshot de precios, los hashes
y los motivos por los que un nivel fue descartado.

## 3. Validar caso y perfiles

La validación no modifica configuración ni crea órdenes:

    for profile in "$PLAN_DIR"/profiles/*.json; do
      python3 tests/llm-benchmark/llm-benchmark.py validate-profiles \
        --case tests/llm-benchmark/resources/cases/eu-news-2025-v1.json \
        --profile "$profile"
    done

## 4. Ejecutar cinco repeticiones

Para comparar calidad, conserva la caché de Evidence Search durante esta
primera ejecución:

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile-plan "$PLAN_PATH" \
      --repetitions 5 \
      --require-costs \
      --artifacts-root tests/llm-benchmark/artifacts \
      --database tests/llm-benchmark/artifacts/history.sqlite

El runner captura la configuración, aplica cada perfil, comprueba el coste,
ejecuta las órdenes en modo `LIGHT` y restaura la configuración inicial.

## 5. Ejecución opcional en frío

Para medir el comportamiento sin respuestas cacheadas, indica la URL directa de
Evidence Search y limpia la caché antes de cada repetición:

    export ASSERMETRY_EVIDENCE_SEARCH_URL='http://localhost:8074'

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile-plan "$PLAN_PATH" \
      --repetitions 5 \
      --require-costs \
      --clear-evidence-cache

Esta opción solo limpia `evidence_search_cache_v2`. No elimina los perfiles de
dominio ni modifica `source_routes_v2`.

## 6. Analizar resultados

Lista las ejecuciones guardadas:

    python3 tests/llm-benchmark/llm-benchmark.py list-runs \
      --database tests/llm-benchmark/artifacts/history.sqlite \
      --limit 30

Los informes se guardan en:

    tests/llm-benchmark/artifacts/<batch-id>/report.md
    tests/llm-benchmark/artifacts/<batch-id>/summary.json

Compara dos ejecuciones concretas:

    python3 tests/llm-benchmark/llm-benchmark.py compare \
      --database tests/llm-benchmark/artifacts/history.sqlite \
      --baseline <run-id-base> \
      --candidate <run-id-candidato>

La configuración ganadora debe cumplir estas condiciones:

1. Todas sus repeticiones relevantes terminan en `PASS`.
2. El coste normalizado a cinco aserciones no supera 0,05 USD.
3. Tiene la mayor calidad media y buena exactitud de veredictos.
4. Mantiene validaciones completadas y evidencia suficientes.
5. Si la calidad es prácticamente igual, se elige la más barata.

El generador actual compara los niveles globales `premium-safe`, `balanced-safe`
y `budget-safe`. No enumera todavía todas las combinaciones híbridas posibles
entre módulos; si solo aparece un perfil bajo 0,05 USD, el benchmark confirma
su viabilidad, pero no prueba que sea la mejor combinación híbrida posible.
