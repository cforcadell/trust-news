# Shared Assermetry Evaluation

## Test data layout

All test inputs and generated outputs live under `tests/data/<type>/`. Evaluation datasets are in `tests/data/evaluation/resources/datasets`; viewer fixtures are in `tests/data/evaluation/resources/viewer-fixtures`; campaigns and viewer-readable order diagnostics are in `tests/data/evaluation/artifacts`. Benchmark, frontend E2E, and historical statistics follow the same `resources` / `artifacts` split. Resources are versioned fixtures; artifacts are local, ignored output retained by run ID and must not be overwritten.

LLM Benchmark answers which validator model or configuration performs best. Pipeline Evaluation answers where Assermetry fails and which recorded observations support that attribution. Both use `tests/evaluation/core` for datasets, execution, evidence bundles, deterministic matching, artifacts, and LIGHT order publishing/polling.

The historical `tests/llm-benchmark/llm-benchmark.py` remains available for OpenRouter profile changes, SQLite history, estimated budgets, authentication, and restoration. Its new repetitions also export `repetition-NN/evaluation/<run_id>.json`. Public functions remain available in that script. Historical export works with the Python standard library only; URL and domain normalization is shared without loading search providers. V1 verdict aliases are normalized to `TRUE` or `FALSE` in evaluation artifacts.

## Runners and flags

Run these commands from the repository root with `PYTHONPATH=tests` (and `:api` when running tests). Both commands use the same flags unless a restriction below says otherwise:

```bash
python -m evaluation.llm_benchmark --dataset synthetic-population-v2 --validate-only
python -m evaluation.pipeline --dataset eu-official-statistics-2025-v1 --mode full --publish --repetitions 3
```

| Flag | Meaning and accepted values |
|---|---|
| `--dataset ID_OR_PATH` | Dataset ID, JSON file, or directory. Repeat it to combine datasets. Required unless `--mode replay` supplies an artifact. Dataset IDs resolve in `tests/data/evaluation/resources/datasets` and benchmark case resources. |
| `--tag FAMILY:VALUE` | Repeatable AND filter. A selected assertion must match every tag across its case and assertion tags. Tags are non-empty `family:value` strings. |
| `--mode VALUE` | Execution mode: `full`, `gold-domains`, `gold-evidence`, or `replay`. Defaults to `gold-evidence` for LLM Benchmark and `full` for Pipeline Evaluation. |
| `--model PROVIDER:MODEL` | Repeatable direct validator configuration. Providers are `openrouter`, `gemini`, `mistral`, or `grok`; model must be non-empty. Required for direct execution, forbidden with `--publish` or `--order`. |
| `--temperature NUMBER` | Finite non-negative LLM temperature; default `0.0`. |
| `--repetitions INTEGER` | Positive runs for each selected assertion/configuration; default `1`. `--order` requires exactly `1`. |
| `--cache VALUE` | `WARM`, `COLD`, or `FROZEN`. Frozen modes require `FROZEN`; live modes accept only `WARM` or `COLD`. Omit it to select `FROZEN` for gold evidence/replay and `WARM` otherwise. |
| `--replay-artifact PATH` | `evaluation-result-v1` artifact used by `--mode replay`. The artifact must pass bundle integrity and dataset/case/expected identity checks. |
| `--order PATH` | Existing order JSON for offline `full` import. It performs no network or LLM calls and cannot be combined with models, cache, publish, counterfactuals, or repetitions other than one. |
| `--publish` | Runs the existing authenticated LIGHT pipeline with deployed validators. It requires `--mode full` and cannot be combined with models, cache, order, or counterfactuals. |
| `--base-url URL` | Backend used only by `--publish`; default `https://localhost:7443/backend`. |
| `--verify-tls` / `--no-verify-tls` | Enable or disable TLS verification for `--publish`; default false for local certificates. |
| `--result-timeout SECONDS` | Positive maximum wait for a published order; default `600`. |
| `--counterfactuals` | With live `--mode full`, also runs `gold-domains` when `acceptable_domains` exists and `gold-evidence` when `reference_evidence` exists. It is forbidden with `--order` and `--publish`. |
| `--router-url URL` | Source Router URL for direct live modes; default `http://localhost:8075`. |
| `--evidence-search-url URL` | Evidence Search URL for direct live modes; default `http://localhost:8074`. |
| `--prompt-file PATH` | Specific RAG prompt template. Only its hash is persisted; replay rejects a different template before an LLM call. |
| `--output PATH` | New artifact directory. It must not already exist. Defaults to a UUID directory below `tests/data/evaluation/artifacts`; with `--analyze`, it selects a new analysis directory. |
| `--analyze CAMPAIGN_DIR` | Analyze saved run and order artifacts offline, without publishing orders or calling services or models. Writes `analysis.json` and `analysis.md` below `CAMPAIGN_DIR/analysis` unless `--output` is supplied. |
| `--validate-only` | Validates datasets and tag selection without calling services or LLMs. |

Technical errors return exit code 1. A completed run with incorrect verdicts returns 0; use the report’s quality criteria rather than the process exit code as promotion evidence.

## Progress logs

Both evaluation runners emit line-oriented, secret-free progress records prefixed with `EVALUATION_TRACE`, mirroring the historical benchmark’s trace style. Each record starts with `phase=...` and may include only identifiers, execution mode, cache mode, counts, durations, statuses, verdicts, and exception types. It never includes prompts, evidence text, credentials, provider request bodies, or exception bodies.

Direct execution emits `campaign.prepared`, `run.start`, Router/Retrieval stage start and completion (or injected/skipped state), `validator_input.prepared`, validation and grounding phases, `run.persisted`, metrics, root-cause, report, and `campaign.complete`. `--publish` additionally emits repetition, order publishing, polling, terminal-order, and order-import phases. Failures emit `run.failed`, `repetition.failed`, or `campaign.failed` with a stage and exception type.

## Direct evaluation examples

```bash
python -m evaluation.llm_benchmark \
  --dataset synthetic-population-v2 --mode gold-evidence \
  --model openrouter:MODEL_A --model mistral:MODEL_B \
  --repetitions 3 --tag lang:es

python -m evaluation.llm_benchmark --mode replay \
  --replay-artifact tests/data/evaluation/artifacts/BATCH/RUN_ID.json \
  --model gemini:MODEL_C

python -m evaluation.pipeline --dataset /path/to/case-v2.json \
  --mode full --model openrouter:MODEL --counterfactuals --cache WARM

python -m evaluation.pipeline --dataset /path/to/case-v2.json \
  --mode gold-domains --model openrouter:MODEL --cache COLD
```

The synthetic fixture checks arithmetic and abstention only. Its URLs are not factual sources and it must not be used to certify factual quality. `--publish` uses the existing `ASSERMETRY_*` credentials and quota handling. It evaluates deployed validators with their actual reputation; use the historical CLI to compare complete configuration profiles.

A RAG evidence validator is not sent to its LLM provider when Evidence Search completes without a citable context. It returns a deterministic `UNKNOWN` with `NO_CITABLE_EVIDENCE`; the viewer records the LLM stage as skipped, while preserving the retrieval response for diagnosis. In `LOCAL` mode Router is a required predecessor: if it returns no eligible domains, neither Evidence Search nor the LLM is called; the abstention is recorded as `ROUTER_NO_SOURCE`.

A direct pipeline case may include `pipeline_assertion`, which must validate as the existing `EnrichedAssertion` model, commonly copied from an order. Extraction is then `NOT_EVALUATED`. With several directly selected Pipeline validators, the existing consensus algorithm uses explicit reputation `1` and current RAG weights; artifacts identify it as `evaluation_models_equal_reputation`.

## Dataset v1 and v2

The compatible container is `id`, `news`, and `assertions`. V1 retains its fields and historical verdict aliases. V2 accepts `TRUE`, `FALSE`, or `UNKNOWN` and optional per-assertion references:

```json
{
  "schema_version": 2,
  "id": "my-resource-v2",
  "news": "Dataset-author-reviewed news text",
  "tags": ["lang:es", "topic:statistics"],
  "assertions": [{
    "id": "MY_CASE",
    "text": "Reviewed assertion",
    "expected_verdict": "TRUE",
    "required_terms": ["discriminating term"],
    "approximate_values": [{"value": 24.5, "tolerance": 0.5, "aliases": ["a quarter"]}],
    "acceptable_domains": ["ine.es", "ec.europa.eu"],
    "reference_facts": ["Reviewed reference fact"],
    "reference_sources": [{"id": "report", "url": "https://example.org/report", "relation": "SUPPORTS"}],
    "reference_evidence": [{"text": "Reviewed excerpt", "source": "report", "relation": "SUPPORTS"}]
  }]
}
```

This is a schema example, not a factual case. `reference_evidence.source` is an HTTP(S) URL or a `reference_sources` ID. Relations are `SUPPORTS`, `CONTRADICTS`, and `NEUTRAL`; neither relations nor gold verdicts are sent to a model. An explicit empty `reference_evidence: []` supplies zero evidence, while an absent field makes GOLD_EVIDENCE unavailable. Dataset authors review reference material; appearing in gold data does not imply official authority.

`approximate_values` declares reviewed numeric equivalences used by deterministic diagnostics. A generated assertion matches an annotation when it contains a number within `tolerance` or one of its `aliases`; no unannotated semantic equivalence is inferred.

`acceptable_domains` measures routing. Exact domains and their DNS subdomains match; another URL on the same domain can be valid. Domain recall measures coverage and does not require every acceptable domain for routing to pass.

## Tags

Tags are extensible `family:value` strings rather than closed enums. Suggested families are:

| Family | Example values |
|---|---|
| `lang:` | `es`, `ca`, `en` |
| `jurisdiction:` | `ES`, `EU`, `CAT`, `GLOBAL` |
| `topic:` | `politics`, `economy`, `statistics`, `health`, `science`, `technology` |
| `difficulty:` | `easy`, `medium`, `hard` |
| `temporal:` | `current`, `historical`, `time-sensitive` |
| `evidence:` | `official`, `multiple-source`, `conflicting`, `insufficient` |
| `expected:` | `decisive`, `unknown`, `abstention` |

When assertion filtering is used, the original news stays intact and only selected assertions are diagnosed.

## Modes and cache behavior

| Mode | Router | Retrieval | Validator |
|---|---|---|---|
| `FULL_PIPELINE` / `full` | Live service | Live service | Selected configuration, or deployment with `--publish` |
| `GOLD_DOMAINS` / `gold-domains` | Injected from acceptable domains | Live LOCAL strategy | Selected configuration |
| `GOLD_EVIDENCE` / `gold-evidence` | Skipped | Injected from references | Same bundle for every model |
| `VALIDATOR_REPLAY` / `replay` | Skipped | Injected from artifact | Selected model |

GOLD_DOMAINS injects `UNKNOWN` source type and authority: an acceptable domain is not assumed official. A single counterfactual repetition is controlled evidence, not a variability study.

`WARM` uses normal caches. `COLD` bypasses stored routes, forces discovery/classification, and bypasses Evidence Search cache reads. Set `EVALUATION_ALLOW_COLD=true` in both local services or they return HTTP 403. COLD does not delete global collections; newly computed results follow the ordinary write path. It does not use domain profiles as failed-classification fallback or reuse a stale route. In WARM, a reused stale route is recorded as a cache hit rather than a recomputation.

`FROZEN` requires gold evidence or replay and makes no Router/Search calls. Cache state records `router_cache_hit`, `evidence_cache_hit`, `route_recomputed`, and `evidence_recomputed`; `null` means unknown. The historical `--clear-evidence-cache` only clears Evidence Search and is not COLD.

## Evidence hashes and replay

`evidence-bundle-v1` computes SHA-256 over canonical JSON in original source/context order: source ID, URL, relation to origin, context ID, actual text hash, and citation eligibility. It normalizes Unicode NFC, line endings, outer whitespace, and scheme/host case while preserving internal whitespace and ordering. It computes text hashes from delivered text and never trusts an incoming `text_sha256`.

Evidence Search returns `evidence_bundle_hash` even on cache hits. The validator records `validator_input_evidence_bundle_hash` before prompt rendering. Evaluation compares both boundaries deterministically; old orders without an upstream hash remain `NOT_EVALUATED`, rather than reconstructing an assumed upstream value. The RAG renderer includes only citation-eligible contexts.

Replay verifies the bundle, rerenders the original context, verifies prompt and response-contract hashes, and rejects a different dataset, expected assertion, or prompt template before an LLM call. It never stores a complete prompt. Gold evidence supports an attribution in replay only when its bundle equals the bundle delivered to the validator.

## Metrics, root cause, and reports

Extraction uses the historical `required_terms` and category matching when available. Routing reports `acceptable_domain_found`, `domain_recall_at_k`, and `first_acceptable_domain_rank`. Retrieval reports results, fetch outcomes, citable contexts, reference-domain presence, and lexical fact coverage. Lexical coverage is an approximation, not semantic equivalence, and no LLM acts as judge.

Validation compares the effective verdict with `TRUE`, `FALSE`, or `UNKNOWN`. `UNNECESSARY_ABSTENTION` requires decisive annotated support or contradiction. Production `evaluate_evidence_grounding()` validates citation identity and eligibility, not semantic entailment.

Root cause is deterministic and conservative: differing boundary hashes produce `HANDOFF_EVIDENCE_MISMATCH`; extraction failure produces `EXTRACTION_ERROR`; invalid responses, citation failures, grounding failures, and technical failures use their corresponding codes. When an assertion and its delivered citable evidence both match an explicit `approximate_values` annotation but the validator returns `FALSE`, evaluation reports `VERDICT_EVIDENCE_CONTRADICTION`. A correct validator with an incorrect aggregate yields `CONSENSUS_ERROR`. Same-assertion, same-configuration, same-template counterfactuals can establish router or retrieval causes; sufficient frozen gold evidence can establish `LLM_WRONG_VERDICT` or `LLM_UNNECESSARY_ABSTENTION`. Otherwise the result is `UNDETERMINED`. Frozen evidence failures are never attributed to the router. Counterfactuals never cross datasets or repetitions.

Each assertion/validator run has its own UUID and an `evaluation-result-v1` envelope with assertion, expected result, stages, cache state, timings, errors, metrics, and public provenance. Historical CLI exports also contain calculated metrics and root cause, including `NOT_EVALUATED` handoffs for old orders. Direct service experiments send and log `X-Evaluation-Run-ID`.

A campaign directory contains `manifest.json`, one `<run_id>.json` per completed call, `report.json`, and `report.md`; `--publish` also writes its order. JSON writes are atomic. Interrupted campaigns retain completed runs and a `RUNNING` manifest. Existing campaign directories are never overwritten. Artifact writing filters credential-like keys and never persists provider exception bodies or raw metadata.

LLM reports group by configuration and mode, including accuracy, verdict distribution, grounding, citations, abstention, invalid responses, errors, latency, and provider-reported tokens. Direct-call cost is `null`; historical estimates remain in the historical benchmark. Pipeline reports count assertion/repetition units rather than validators or counterfactuals. Generated assertions without a gold match are retained as `OBSERVATION_ONLY`: their validations and technical errors remain visible, while they are excluded from accuracy and end-to-end denominators. A GOLD-only campaign has no end-to-end pass count, and root-cause counts need not sum to case totals.

## Offline per-validation analysis

Analyze an existing campaign, including a campaign left `RUNNING` by a reporting failure:

```bash
PYTHONPATH=tests python3 -m evaluation.pipeline \
  --analyze tests/data/evaluation/artifacts/CAMPAIGN_ID
```

This creates `analysis/analysis.json` and `analysis/analysis.md` without changing the original manifest, run artifacts, orders, or reports. The analysis directory must be new; use `--output PATH` to select another new directory. The same flag is available from `evaluation.llm_benchmark`. It reads only recorded observations, so it needs no credentials, services, provider access, or `pydantic`.

Each validation reports extraction, selected domains, retrieved URLs and fetch outcomes, citable contexts, recorded evidence handoff hashes, cited source/context IDs, verdict, production grounding audit, consensus, and sanitized provider HTTP status when available in a saved order. The JSON includes stage statuses and findings; Markdown includes a campaign table and one section per validation. Missing `acceptable_domains` means routing correctness is `NOT_EVALUATED`, although selected domains remain visible. Missing reference sources/facts means source relevance is `NOT_EVALUATED`; citation identity and eligibility do not establish semantic support. Missing evidence boundary hashes leave handoff `NOT_EVALUATED`.

## Tests without real providers

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api python -m pytest \
  tests/evaluation tests/llm-benchmark/test_llm_benchmark.py \
  tests/api/test_source_router.py tests/api/test_evidence_search_units.py \
  tests/api/test_validator_source_orchestration.py \
  tests/api/test_evidence_grounding.py tests/api/test_validation_scoring.py \
  tests/api/test_common_search.py tests/api/test_protocol_v2_models.py \
  tests/api/test_common_llm.py tests/api/test_llm_runtime_configuration.py -q
```

The tests use mocked providers, HTTP, and repositories. They require no API keys, Kafka, MongoDB, blockchain, or external evaluation framework.

## Visor local de órdenes guardadas

El visor independiente de `web_classic` lee campañas nuevas con archivos `<parent_run_id>-viewer.json`, `<parent_run_id>-order.json` y `<run_id>.json`. No realiza búsquedas ni llamadas al LLM. Se inicia desde la raíz del repositorio:

```bash
PYTHONPATH=tests:api .venv/bin/python -m evaluation.viewer.server \
  --artifacts-root tests/data/evaluation/artifacts --host 127.0.0.1 --port 8765
```

Abrir `http://127.0.0.1:8765/`. Para crear el diagnóstico desde una orden guardada, usar `--order RUTA_A_LA_ORDEN --mode full --dataset ID_DEL_DATASET --output CARPETA_NUEVA` con `evaluation.pipeline`; `--publish` también emite el diagnóstico al guardar una orden nueva. Los artefactos anteriores no se migran. El contrato, rutas y límites están en [benchmark-viewer-contract.md](benchmark-viewer-contract.md); el avance por fases está en [benchmark-viewer-plan.md](benchmark-viewer-plan.md).

Para capturar modelo, intentos y reparación de Generate Assertions en órdenes publicadas, configurar `EVALUATION_CAPTURE_GENERATION=true` en `generate-asertions`. Para Router, Evidence Search y citas originales, configurar `EVALUATION_CAPTURE_PIPELINE=true` en `validate-asertions`. Para obligar a recalcular Router y Evidence Search durante esa captura, añadir `EVALUATION_CAPTURE_COLD=true` en el validador y `EVALUATION_ALLOW_COLD=true` en **ambos** servicios. La captura fría es necesaria para ver los chunks descartados cuando la respuesta ya existía en caché. El texto completo de todos los chunks extraídos se guarda en el artefacto de evaluación; no se añade a la caché compartida. Las páginas cuya descarga falla no producen chunks.

La corrección semántica de una afirmación, el apoyo real de una evidencia y la idoneidad de un dominio sin anotación revisada siguen siendo juicios humanos. El visor distingue esos huecos como `NOT_EVALUATED`; una cita con ID válido solo acredita identidad y elegibilidad. La tabla de consenso resume votos, pesos y motivos que ya constan en la orden. No modifica ni anota los artefactos originales.

En Router, la traza de evaluación diferencia consultas previstas y ejecutadas, URLs devueltas, deduplicación, rechazo por elegibilidad y ranking por candidato. Una ruta `FRESH` reutilizada no contiene búsqueda nueva: el visor muestra las listas históricas como tales y deja sin reconstruir URLs o motivos individuales que no se guardaron en el documento de ruta. La captura detallada de Router se activa con el mismo `EVALUATION_CAPTURE_PIPELINE=true` del validador LIGHT; las peticiones normales mantienen su respuesta sin `evaluation_trace`.
