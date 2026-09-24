# Benchmark histórico de configuraciones LLM

scripts/llm-benchmark.py compara configuraciones completas de los módulos LLM
usando exclusivamente OpenRouter. Ejecuta órdenes LIGHT, conserva artefactos
JSON inmutables e indexa las métricas en SQLite para compararlas con el tiempo.

No debe ejecutarse contra producción. El runner cambia temporalmente la
configuración efectiva y consume cuota de generación y validación.

## Alcance

El caso inicial benchmarks/llm/cases/eu-news-2025-v1.json contiene la noticia
sintética sobre Suecia, Alemania, Italia y España y cuatro resultados esperados.
El runner mide por separado:

- extracción y correspondencia de aserciones;
- categoría;
- veredicto agregado;
- veredicto por validador;
- evidencia usada por validadores RAG;
- respuestas completadas y latencia de validadores;
- coste estimado por módulo y global.

La muestra tiene cuatro aserciones. Se guardan dos costes:

- sample_total_usd: estimación para las aserciones realmente generadas;
- normalized_5_assertions_total_usd: estimación normalizada a cinco aserciones,
  compatible con la vista administrativa de recomendaciones.

El coste actual es una estimación basada en los precios del catálogo OpenRouter
y las muestras de tokens configuradas en api/admin. Aunque el adaptador LLM lee
usage del proveedor, las órdenes todavía no persisten esos tokens; por ello el
informe no presenta el coste como facturación real.

## Requisitos

- Python 3.11 o posterior. sqlite3 forma parte de Python y no requiere instalar
  SQLite ni paquetes adicionales.
- Despliegue local accesible, por defecto en https://localhost:7443/backend.
- Usuario con rol administrativo y cuotas suficientes.
- Todos los componentes y validadores LLM incluidos deben usar OpenRouter.
- Ninguna otra persona o automatización debe cambiar la configuración durante
  el batch.

La contraseña nunca se escribe en los artefactos. Se admite:

    export ASSERMETRY_ACCESS_TOKEN='...'

o, si el cliente de Keycloak permite Direct Access Grants:

    export ASSERMETRY_USERNAME='benchmark-admin'
    read -rsp 'Password: ' ASSERMETRY_PASSWORD
    export ASSERMETRY_PASSWORD

El entorno local usa normalmente un certificado autofirmado. La verificación
TLS está desactivada por defecto para este runner local. Para un certificado de
confianza:

    export ASSERMETRY_TLS_VERIFY=true

## Validación sin red

Este comando valida el esquema del caso y de los perfiles y comprueba que todos
declaran OpenRouter:

    python3 scripts/llm-benchmark.py validate-profiles \
      --profile benchmarks/llm/profiles/current-openrouter.json \
      --profile benchmarks/llm/profiles/example-balanced-openrouter.json

No modifica configuración, no usa credenciales y no crea órdenes.

## Generación de perfiles por presupuesto

`generate-profiles` consulta la configuración efectiva y el catálogo de
OpenRouter, pero no cambia modelos ni crea órdenes. Este ejemplo solicita un
máximo de 0,25 USD para una noticia de cinco aserciones medias:

    python3 scripts/llm-benchmark.py generate-profiles \
      --max-news-cost-usd 0.25

Por defecto reserva un margen del 5 %. Por tanto, con un máximo solicitado de
0,25 USD solo genera configuraciones cuyo coste estimado no supera 0,2375 USD.
Se puede cambiar el margen explícitamente:

    python3 scripts/llm-benchmark.py generate-profiles \
      --max-news-cost-usd 0.25 \
      --budget-headroom-percent 10

La salida se guarda en
`artifacts/llm-benchmark/generated/<plan-id>/` e incluye:

    plan.json
    effective-configuration.json
    pricing-snapshot.json
    profiles/premium-safe.json
    profiles/balanced-safe.json
    profiles/budget-safe.json

Solo aparecen los perfiles que el endpoint puede verificar bajo el máximo
efectivo. Los niveles con la misma configuración se deduplican y quedan
registrados en `plan.json` como descartados. Cada validador usa un selector por
ID exacto para que el plan no cambie de significado si más adelante se añaden
validadores del mismo tipo. El plan conserva fecha, presupuesto, margen,
precios, hash de la configuración efectiva y hash de cada perfil.

La generación falla de forma segura si falta el precio de cualquier componente
o validador LLM, si alguno no usa OpenRouter o si la configuración cambia entre
la captura y la recomendación. Los precios pueden cambiar después de generar el
plan; por eso la ejecución siempre vuelve a comprobar el coste.

Para ejecutar todos los perfiles de un plan:

    python3 scripts/llm-benchmark.py run \
      --profile-plan artifacts/llm-benchmark/generated/<plan-id>/plan.json \
      --repetitions 5 \
      --require-costs

`run --profile-plan` verifica los hashes, hereda el máximo efectivo del plan y
no permite relajarlo mediante `--max-news-cost-usd`. Sí se puede indicar un
máximo menor. `--profile` y `--profile-plan` son mutuamente excluyentes.

## Ejecución

Línea base actual, tres repeticiones:

    python3 scripts/llm-benchmark.py run \
      --profile benchmarks/llm/profiles/current-openrouter.json \
      --repetitions 3

Comparar dos perfiles y exigir un máximo normalizado de 0,25 USD por noticia:

    python3 scripts/llm-benchmark.py run \
      --profile benchmarks/llm/profiles/current-openrouter.json \
      --profile benchmarks/llm/profiles/example-balanced-openrouter.json \
      --repetitions 5 \
      --max-news-cost-usd 0.25 \
      --require-costs

El perfil example-balanced-openrouter es una plantilla. Hay que revisar la
disponibilidad y el precio de sus modelos antes de usarlo.

El runner:

1. adquiere /tmp/assermetry-llm-benchmark.lock;
2. captura la configuración efectiva completa;
3. resuelve $current y aplica el perfil;
4. confirma la configuración efectiva;
5. captura recomendaciones y precios;
6. rechaza la configuración si incumple el presupuesto solicitado;
7. ejecuta las repeticiones en modo LIGHT;
8. guarda orden, puntuación y costes aun cuando una repetición falla;
9. restaura la configuración inicial en un bloque finally;
10. devuelve código distinto de cero ante fallos o restauración incompleta.

El bloqueo evita dos runners simultáneos en el mismo host. No es un bloqueo
distribuido entre máquinas.

## Perfiles

Un perfil tiene schema_version 1, un id estable, componentes y reglas para
validadores. Ejemplo conceptual:

    {
      "schema_version": 1,
      "id": "candidate-a",
      "components": {
        "generate-asertions": {
          "provider": "openrouter",
          "model": "modelo/generador",
          "temperature": 0
        },
        "source-router": {
          "provider": "openrouter",
          "model": "modelo/router",
          "temperature": 0
        }
      },
      "validators": [
        {
          "selector": {
            "types": ["RAG_EVIDENCE_VALIDATION"],
            "strategies": ["LOCAL"]
          },
          "provider": "openrouter",
          "model": "modelo/rag",
          "temperature": 0
        }
      ]
    }

Los selectores admiten id, types y strategies. Las reglas se procesan en orden;
si varias coinciden, prevalece la última. Cada validador LLM descubierto debe
quedar cubierto. $current conserva el modelo efectivo, pero sigue exigiendo que
su proveedor sea OpenRouter.

Para atribuir causas se recomienda cambiar un módulo cada vez. Los perfiles
completos deben reservarse para candidatos ya filtrados.

## Puntuación

La puntuación de calidad es de 0 a 100:

| Área | Peso |
|---|---:|
| Extracción, cobertura, precisión, cantidad y categoría | 25 % |
| Veredicto agregado frente al esperado | 45 % |
| Evidencia usada por validadores RAG | 20 % |
| Validaciones completadas | 10 % |

Si una métrica no aplica, sus pesos se normalizan entre las restantes. El
emparejamiento de aserciones es determinista y usa required_terms del caso.
Cada cambio del caso o del criterio debe crear una nueva versión, no alterar
resultados históricos.

Cuatro aserciones no bastan para conclusiones estadísticas fuertes. Se
recomiendan al menos tres repeticiones y preferiblemente cinco. Para evaluar
RAG de forma reproducible debe usarse además un corpus congelado; las búsquedas
externas vivas miden actualidad, no reproducibilidad.

## Artefactos

Por defecto se crean:

    artifacts/llm-benchmark/
    ├── history.sqlite
    └── <batch-id>/
        ├── manifest.json
        ├── initial-configuration.json
        ├── summary.json
        ├── report.md
        └── <profile-id>/
            ├── resolved-profile.json
            ├── configuration-changes.json
            ├── pricing-snapshot.json
            ├── preflight-costs.json
            ├── restore.json
            └── repetition-01/
                ├── order.json
                ├── score.json
                ├── costs.json
                └── run.json

Los JSON son la evidencia canónica. SQLite es un índice histórico append-only
con batches, ejecuciones, costes por módulo, resultados por aserción y métricas.
Los artefactos se excluyen de Git.

## Histórico y comparación

Listar las últimas ejecuciones:

    python3 scripts/llm-benchmark.py list-runs --limit 20

Comparar dos run_id:

    python3 scripts/llm-benchmark.py compare \
      --baseline <run-id-base> \
      --candidate <run-id-candidato>

La comparación muestra diferencias de calidad, exactitud, coste de la muestra,
coste normalizado y duración. Un coste menor produce un delta negativo.

## Recuperación

Si el proceso recibe una excepción normal, intenta restaurar la configuración.
SIGKILL, pérdida de máquina o un fallo de red durante la restauración pueden
impedirlo. Antes de ejecutar se guarda initial-configuration.json. Si
restore.json indica FAIL, hay que restaurar esos valores desde la administración
LLM y verificar la configuración efectiva antes de iniciar otro batch.

Las contraseñas, tokens y claves de proveedor nunca se incluyen en perfiles,
SQLite ni artefactos.
