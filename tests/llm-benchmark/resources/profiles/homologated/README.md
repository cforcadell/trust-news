# Perfiles LLM homologados

This folder contains snapshots dated from LLM configurations accepted as operating baseline. An approved profile retains models and temperatures; it does not mean that it is the optimal combination of cost or quality.

The runner does not automatically discover or execute these files. To use them, you have to indicate their path explicitly using `--profile`. An alias `latest` is not maintained, so that an execution always identifies a specific version.

## Versions

| Date | Perfil | Procedencia |
|---|---|---|
| 2026-09-24 | `prod-openrouter-2026-09-24.json` | Models declared by production overheads |

Before running a version:

    python3 tests/llm-benchmark/llm-benchmark.py validate-profiles \
      --profile tests/llm-benchmark/resources/profiles/homologated/prod-openrouter-2026-09-24.json

To use it in the local benchmark:

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile tests/llm-benchmark/resources/profiles/homologated/prod-openrouter-2026-09-24.json \
      --repetitions 3 \
      --require-costs

## Comparison of allays at 2026-09-24

| Module | Local/kind | Production | Approved result |
|---|---|---|---|
| `generate-asertions` | `google/gemini-2.5-flash-lite` | `openai/gpt-5-nano` | Production |
| `source-router` | `google/gemini-2.5-flash-lite` | `google/gemini-2.5-flash-lite` | Coinciden |
| RAG `EXT_ONLY_OFFICIAL` | `meta-llama/llama-3.1-8b-instruct` | igual | Coinciden |
| RAG `EXT_OFFICIAL_FIRST` | `qwen/qwen3-30b-a3b-instruct-2507` | igual | Coinciden |
| RAG `LOCAL` | `mistralai/mistral-small-24b-instruct-2501` | igual | Coinciden |

Temperatures are set to make the reproducible snapshot: `0.1` for `generate-asertions` and `0.0` for `source-router` and the validators. In `source-router`, `0.0` is the default value of the service because the ConfigMap does not declare `LLM_TEMPERATURE`.

Declarative sources:

- `k8s/apis/generate-asertions/configmap.yaml`
- `k8s/apis/generate-asertions/overlays/prod/kustomization.yaml`
- `k8s/apis/source-router/base/configmap.yaml`
- `k8s/apis/validate-asertions/base/configmap-common.yaml`
- `k8s/apis/validate-asertions/overlays/{local,prod}/worker-*`

## Versing policy

- Create a new ISO-dated file (`AAAA-MM-DD`) for each approval.
- Do not edit a version used in historical results; a correction generates
another version dated.
- Do not use `$current`: an approved profile must be deterministic.
- Use type and strategy selectors, not validator addresses, so that
the profile is portable between kind and production.
- Homolog as a stable profile only after validating the schema and completing
the agreed benchmark campaign.
