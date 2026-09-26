# Perfiles LLM homologados

Esta carpeta contiene snapshots fechados de configuraciones LLM aceptadas como
línea base operativa. Un perfil homologado conserva modelos y temperaturas; no
significa que sea la combinación óptima de coste o calidad.

El runner no descubre ni ejecuta automáticamente estos archivos. Para usarlos
hay que indicar su ruta explícitamente mediante `--profile`. No se mantiene un
alias `latest`, para que una ejecución siempre identifique una versión concreta.

## Versiones

| Fecha | Perfil | Procedencia |
|---|---|---|
| 2026-09-24 | `prod-openrouter-2026-09-24.json` | Modelos declarados por los overlays de producción |

Antes de ejecutar una versión:

    python3 tests/llm-benchmark/llm-benchmark.py validate-profiles \
      --profile tests/llm-benchmark/resources/profiles/homologated/prod-openrouter-2026-09-24.json

Para usarla en el benchmark local:

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile tests/llm-benchmark/resources/profiles/homologated/prod-openrouter-2026-09-24.json \
      --repetitions 3 \
      --require-costs

## Comparación de overlays a 2026-09-24

| Módulo | Local/kind | Producción | Resultado homologado |
|---|---|---|---|
| `generate-asertions` | `google/gemini-2.5-flash-lite` | `openai/gpt-5-nano` | Producción |
| `source-router` | `google/gemini-2.5-flash-lite` | `google/gemini-2.5-flash-lite` | Coinciden |
| RAG `EXT_ONLY_OFFICIAL` | `meta-llama/llama-3.1-8b-instruct` | igual | Coinciden |
| RAG `EXT_OFFICIAL_FIRST` | `qwen/qwen3-30b-a3b-instruct-2507` | igual | Coinciden |
| RAG `LOCAL` | `mistralai/mistral-small-24b-instruct-2501` | igual | Coinciden |

Las temperaturas se fijan para hacer el snapshot reproducible: `0.1` para
`generate-asertions` y `0.0` para `source-router` y los validadores. En
`source-router`, `0.0` es el valor por defecto del servicio porque el ConfigMap
no declara `LLM_TEMPERATURE`.

Fuentes declarativas:

- `k8s/apis/generate-asertions/configmap.yaml`
- `k8s/apis/generate-asertions/overlays/prod/kustomization.yaml`
- `k8s/apis/source-router/base/configmap.yaml`
- `k8s/apis/validate-asertions/base/configmap-common.yaml`
- `k8s/apis/validate-asertions/overlays/{local,prod}/worker-*`

## Política de versionado

- Crear un archivo nuevo con fecha ISO (`AAAA-MM-DD`) para cada homologación.
- No editar una versión usada en resultados históricos; una corrección genera
  otra versión fechada.
- No usar `$current`: un perfil homologado debe ser determinista.
- Usar selectores de tipo y estrategia, no direcciones de validadores, para que
  el perfil sea portable entre kind y producción.
- Homologar como perfil estable solo después de validar el esquema y completar
  la campaña de benchmark acordada.
