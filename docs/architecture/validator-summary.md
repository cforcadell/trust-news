# Validators Assermetry: workers, types and behavior

## Objective

This document describes how the validation workers of Assermetry work, which types of validators exist, which algorithm executes each and which modules intervene in the flow.

In the current implementation a worker is an instance of the microservice `api/validate-asertions`. Each worker is identified by its `ACCOUNT_ADDRESS`, is registered as a blockchain validator, publishes its configuration in IPFS and Kafka, and, if its type is automatic, listens to validation requests to execute a factual decision.

## General vision of the worker

Each `validate-asertions` pod fulfils four responsibilities:

1. **Identity and registration**
   - Usa `ACCOUNT_ADDRESS` y `PRIVATE_KEY` como identidad del validador.
   - Build a `ValidatorConfig` with `name`, `type`, `provider`, `model`, dates and `status`.
   - Upload that configuration to IPFS.
   - Record or update the validator in the smart contract with its categories (`VALIDATOR_CATEGORIES`) and the configuration CID.
   - Publish a `new_validator_config` event so that `news-handler` updates its operating cache.

2. **API administrativa**
   - It displays endpoints such as `/registrar_validador`, `/desregistrar_validador`, `/admin/config` and `/verificar`.
   - Allows changing provider, model or categories from the endpoint admin.

3. **Automatic validation worker**
   - Only active if `VALIDATOR_TYPE` belongs to the automatic types: `1`, `2` or `3`.
   - Raise a blockchain listener for `ValidationRequested` events.
   - Raise a Kafka consumer for `LIGHT` requests in `TOPIC_LIGHT_VALIDATION_REQUESTS`.
   - Convert each request to `assertion-validation-payload-v2`, execute the algorithm of the configured type and devuelve/verifica the result.

4. **Persistence of the outcome**
   - In `BLOCKCHAIN` mode, it generates a validation document, uploads it to IPFS and calls `addValidation` in the smart contract.
   - In `LIGHT` mode, it does not touch blockchain or IPFS for the result; it responds by Kafka with `light_validation_completed`.

## Modulos principales

| Modulo | Responsabilidad |
|---|---|
| `api/validate-asertions/main.py` | Worker/API validation. Select algorithm by `VALIDATOR_TYPE`, call LLM, call `evidence-search` when it applies, listen to Kafka/blockchain and record results. |
| `api/common/models/async_models.py` | Define `ValidatorType`, `ValidatorConfig`, weights by type, Kafka models and normalization of results. |
| `api/common/models/protocol_models.py` | Define `assertions-document-v2` and `assertion-validation-payload-v2`, used both in LIGHT and BLOCKCHAIN. |
| `api/common/utils/validator_registry.py` | Filter active, automatic and compatible validators with a category. |
| `api/common/utils/scoring.py` | Calculates weights by validator and results weighted by assertion. |
| `api/source-router` | Discover, rank, and cache domain profiles and routes only for the RAG `LOCAL` strategy. |
| `api/evidence-search/main.py` | Run the RAG plan, retrieve documents with Exa/Tavily, cache and return standardized evidence. |
| `api/news-handler/main.py` | Orchestra commands, generates LIGHT requests, consumes responses and calculates weighted results. |
| `api/news-chain/main.py` | Listen to on-chain events, retrieve IPFS documents and forward solicitudes/resultados to backend via Kafka. |

## Types of validators

The types are defined in `ValidatorType`:

| ID | Tipo | Automatico | Peso | Comportamiento |
|---:|---|---|---:|---|
| 1 | `LLM_MEMORY_VALIDATION` | Si | 0.25 | Validate with internal knowledge of the model and reasoning. |
| 2 | `LLM_SEARCH_VALIDATION` | Si | 0.50 | Validate with LLM and search online when proveedor/modelo supports it. |
| 3 | `RAG_EVIDENCE_VALIDATION` | Si | 1.00 | Validated with LLM, but using evidence recovered by `evidence-search`. |
| 4 | `DETERMINISTIC_VALIDATION` | No | 1.00 | Reserved for non-LLM validators with deterministic rules. In the current worker, it does not run automatic listeners. |
| 5 | `HUMAN` | No | 0.10 | Represents humana/manual. Validation In the current worker only registra/configura is not automatically validated. |

`1`, `2` and `3` are the only types that run `validate_payload_v2()`. `4` and `5` types can exist as a validator configuration, but `validate-asertions` does not create LLM client or boot Kafka/blockchain listeners for them.

## Common automatic validation algorithm

For any automatic type the base flow is:

1. Receive a `assertion-validation-payload-v2` request.
2. Check that the worker is automatic and has initialized AI client.
3. If the type is RAG (`VALIDATOR_TYPE=3`), request evidence from `evidence-search`.
4. Build the prompt with specific prompt of the type, serialized news context, evidence only in RAG and assertion text.
5. Send the prompt to the configured provider (`mistral`, `gemini`, `openrouter` or `grok`).
6. JSON model pairing with `resultado`, `descripcion` and optionally `confidence`, `sources` and `evidence_used`.
7. Para RAG, comprobar las referencias contra el corpus recuperado y convertir a `UNKNOWN` cualquier `TRUE`/`FALSE` sin soporte comprobable.
8. For delegated online search, keep voting as a non-documentary signal and move your optional links to `sources_declared` with `PROVIDER_SEARCH_UNVERIFIED` base.
9. For memory, identify the base as `MODEL_KNOWLEDGE` and do not publish quotes as evidence used.
10. Return by Kafka in LIGHT or register in IPFS/blockchain in BLOCKCHAIN.

## Classification by behavior

### 1. Memory LLM (`LLM_MEMORY_VALIDATION`)

**Algorithm:** direct inference with LLM.

The worker uses the prompt `LLM_MEMORY_VALIDATION_PROMPT`. The model reasons about assertion with its internal knowledge and context included in the payload. It does not call `evidence-search` and does not activate online search.

**Variables clave:** `VALIDATOR_TYPE=1`, `LLM_MEMORY_VALIDATION_PROMPT`.

**Expected use:** Validator fast and cheap, useful as initial signal. Its weight is low (`0.25`) because it does not provide external sources nor evidence recovered during validation time.

### 2. LLM with online search (`LLM_SEARCH_VALIDATION`)

**Algorithm:** LLM inference and online supplier capacity.

The worker uses `LLM_SEARCH_VALIDATION_PROMPT` and delegates the search capability to proveedor/modelo.. He does not call the `evidence-search` microservice and therefore does not require sources or present optional links from the provider as provided evidence. The current implementation requires OpenRouter; other providers are reserved until explicit integration of their web tools is available.

In OpenRouter, when `VALIDATOR_TYPE=2`, the model automatically transforms with `:online` suffix. For example, `openai/gpt-5-mini` passes to `openai/gpt-5-mini:online`.

**Variables clave:** `VALIDATOR_TYPE=2`, `LLM_SEARCH_VALIDATION_PROMPT`.

**Expected use:** non-documentary signal with more time context than type 1, but without control or verification of the corpus consulted. Its optional sources remain as `sources_declared` and its base is `PROVIDER_SEARCH_UNVERIFIED`. Its weight is medium (`0.50`).

### 3. RAG with evidence (`RAG_EVIDENCE_VALIDATION`)

**Algorithm:**Recovery of evidence + strict validation with LLM.

The RAG worker orchestrates a mandatory strategy. With `LOCAL` he calls `source-router` first, receives `preferred_sources[]` with standardized metadata and sends them to Evidence Search. With `EXT_OFFICIAL_FIRST` or `EXT_ONLY_OFFICIAL` he calls Evidence Search directly without local domains. Finally he injects the evidence recovered in `RAG_EVIDENCE_VALIDATION_PROMPT`.

The RAG prompt requires validation only with the evidence provided. If there is insufficient evidence, the expected behavior is `UNKNOWN` or equivalent insufficiency.

**Key variables:**`VALIDATOR_TYPE=3`, `SOURCE_ROUTER_URL`, `EVIDENCE_SEARCH_URL`, `EVIDENCE_SEARCH_STRATEGY` and `RAG_EVIDENCE_VALIDATION_PROMPT`.

**Subcomportamientos RAG:**

| Variante | Configuration | Comportamiento |
|---|---|---|
| RAG LOCAL | `EVIDENCE_SEARCH_STRATEGY=LOCAL` | Source Router discovers and classifies domains; Evidence Search is restricted to eligible domains. |
| RAG oficial preferente | `EVIDENCE_SEARCH_STRATEGY=EXT_OFFICIAL_FIRST` | The provider priorities official sources and then allows for a general search. |
| Official RAG only | `EVIDENCE_SEARCH_STRATEGY=EXT_ONLY_OFFICIAL` | The provider searches for official sources and Evidence Search discards unofficial results. |
| RAG without search credentials | Empty `API_KEY_PROVIDER` | It fails explicitly; it does not create placeholders or static domains. |
| RAG with Exa/Tavily | `API_KEY_PROVIDER` configurado | Run real queries, merge results, deduplicate URLs and limit results. |

**Expected use:** Validator of greater operational confidence because the decision is linked to evidence explicitly recovered. Its weight is high (`1.00`).

### 4. Deterministico (`DETERMINISTIC_VALIDATION`)

**Algorithm:**exact rules or programmatic checks.

This type is defined for validations that do not depend on LLM: for example, validations against official databases, format rules, cryptographic checks or deterministic APIs.

In the current worker there is no automatic implementation for this type. If `VALIDATOR_TYPE=4`, the service is registered as a validator, but does not create AI client or listen to automatic requests.

**Expected use:** maximizes confidence when the domain allows for objective testing. That's why its weight is `1.00`.

### 5. Humano (`HUMAN`)

**Algorithm:** manual decision external to the automatic worker.

This type represents a human validator or an organization that issues validations outside of the automatic flow of `validate-asertions`.

In the current worker there is no automatic list for `HUMAN`. It is used as classification and configuration, not as LLM agent.

**Expected use:** auxiliary or audit signal. Its default weight is `0.10`, low because the system does not yet model a formal flow of human revision with SLA, evidence or consensus.

## Execution modes

### Modo LIGHT

`news-handler` selects validators from your cache with `light_validators_for_category()`. The filter requires active validator, automatic type (`1`, `2` or `3`) and support of the category of the assertion.

For each assertion and validator, it publishes a `light_validation_request` in Kafka. The worker who matches `validator_id == ACCOUNT_ADDRESS` processes the message and responds with `light_validation_completed`.

LIGHT does not publish the document in IPFS or record the validation in blockchain. It saves results in Mongo with sources, evidence, confidence, error and response time.

### Modo BLOCKCHAIN

The assertion document is uploaded to IPFS and registered on-chain. When the contract issues `ValidationRequested`, the corresponding automated worker retrieves and validates the `AssertionsDocumentV2` from IPFS, locates the assertion by `assertion_index`, builds `assertion-validation-payload-v2`, executes the algorithm, uploads the validation document to IPFS and records the result with `addValidation`. Any previous form of the document is rejected.

`news-chain` also listens to contract events and forwards trazas/resultados to Kafka to keep the backend synchronized.

## Setup by worker

The current classification of each worker is decided by environment variables:

| Variable | Funcion |
|---|---|
| `VALIDATOR_NAME` | Public name of the validator in its IPFS config. |
| `VALIDATOR_TYPE` | algoritmo/comportamiento. Type |
| `VALIDATOR_CATEGORIES` | Categories the validator accepts. |
| `AI_PROVIDER` | LLM supplier: `mistral`, `gemini`, `openrouter`, `grok` or `none`. |
| `MODEL` | Model used by the supplier. |
| `API_URL` | Endpoint of the supplier. |
| `TEMPERATURE` | LLM temperature. |
| `EVIDENCE_SEARCH_URL` | Internal micro-service evidence URL. |
| `EVIDENCE_SEARCH_STRATEGY` | Mandatory RAG strategy: `LOCAL`, `EXT_OFFICIAL_FIRST` or `EXT_ONLY_OFFICIAL`. Not defined for other types. |

In Kubernetes, `k8s/apis/validate-asertions/base/configmap-common.yaml` defines defaults and prompts. Local overlays specialize each worker. In the current local configuration:

| Worker | Tipo | Provider/modelo | Comportamiento |
|---|---:|---|---|
| `worker-1` | 3 | OpenRouter + `meta-llama/llama-3.1-8b-instruct` | RAG `EXT_ONLY_OFFICIAL`. |
| `worker-2` | 3 | OpenRouter + `qwen/qwen3-30b-a3b-instruct-2507` | RAG `EXT_OFFICIAL_FIRST`. |
| `worker-3` | 3 | OpenRouter + `mistralai/mistral-small-24b-instruct-2501` | RAG `LOCAL`. |

## Scoring and weighted result

The backend does not decide only by counting votes. Each validation is transformed into a weighted detail:

```text
effective_weight = validator_type_weight * reputation
score_result = suma(effective_weight para ese resultado) / numero_de_validadores
```

Weights per type are:

| Tipo | Peso |
|---|---:|
| `LLM_MEMORY_VALIDATION` | 0.25 |
| `LLM_SEARCH_VALIDATION` | 0.50 |
| `RAG_EVIDENCE_VALIDATION` | 1.00 |
| `DETERMINISTIC_VALIDATION` | 1.00 |
| `HUMAN` | 0.10 |

`reputation` lives in the backend operating cache, not in the JSON IPFS of the validator. If there is no explicit reputation, `1.0` is used.

The winner by assertion is the result with the highest score between `TRUE`, `FALSE` and `UNKNOWN`. Details include type of validator, weight, reputation, effective weight, description, fonts and evidence used.

## Classification summary

| Clase | Tipos | Source of truth | Automatizacion | Confianza operacional |
|---|---|---|---|---|
| LLM puro | `LLM_MEMORY_VALIDATION` | Knowledge of the model + context | Alta | Baja-media |
| LLM online | `LLM_SEARCH_VALIDATION` | LLM Provider with Search | Alta | Media |
| RAG | `RAG_EVIDENCE_VALIDATION` | Evidence recovered and cached | Alta | Alta |
| Programatico | `DETERMINISTIC_VALIDATION` | Reglas/APIs exactas | Not implemented in current worker | Very high if implemented by domain |
| Manual | `HUMAN` | Revision humana | Not implemented in current worker | Depends on the external process |
