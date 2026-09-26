# Use of LLM in Assermetry

> Inventory and recommendation of architecture revised on September 20, 2026.
> Model names change rapidly: they should be considered candidates for a
> reproducible evaluation, not a configuration that should be copied without measuring it.

## Executive summary

The project inferences with LLM in three modules:

1. `generate-asertions`: Extracts and structures verifiable assertions from a news story.
2. `source-router`: sort candidate domains to decide which sources are
appropriate for a path of evidence.
3. `validate-asertions`: issues a verdict `TRUE`, `FALSE` or `UNKNOWN`. Has three
LLM variants: memory, online search of the supplier and RAG with evidence recovered by Assermetry.

The quality priority should be:

1. **RAG Validator**: needs the best evidentiary reasoning and, if incorporated, a
second model specializing in entailment/NLI.
2. **Assertion generator**: needs a strong model in semantic extraction and output
structured, because one of your mistakes spreads to the entire chain.
3. **Validator with online search**: needs a competent model and good engine
search, although its current trace is not auditable by Assermetry.
4. **Source router creator**: you can use a small and fast model, always with
deterministic rules and abstention.
5. **Memory Validator**: a better model reduces errors, but does not correct its lack
The main reason for this is the current and verifiable evidence; it is not appropriate to concentrate expenditure here.

They do not use LLM `evidence-search`, `news-handler`, `news-chain`, `gateway`, IPFS or contracts. `evidence-search` recovers and fragments documents; the LLM interpreting these fragments lives in `validate-asertions`. `admin` also does not inference: consult the OpenRouter catalog and sort models using a local heuristic.

## Flow

```text
noticia
  |
  v
generate-asertions -- LLM de extracción estructurada
  |
  +--> aserciones + taxonomía + contexto + consultas sugeridas
          |
          +--> source-router -- búsqueda de candidatos
          |       |
          |       +--> LLM de clasificación de dominios
          |
          +--> evidence-search -- recuperación/chunking, sin LLM
                  |
                  v
          validate-asertions -- LLM de verificación
                  |
                  +--> comprobaciones deterministas de JSON y grounding
                  |
                  v
             consenso / cadena
```

## Inventory by module

### `api/generate-asertions`

**Use.** It converts the entire text into a configurable maximum of factual, atomic, self-contained and verifiable statements. It also assigns `categoryId`, `topic_code`, `evidence_kind`, entities, places, jurisdiction, temporal context and search trails.

**Contract.** The response is validated against `AssertionBatch` and `common.models` Pydatic models. The Pydantic model automatically generates the JSON Schema in `common/llm`: Direct Gemini receives `responseSchema`, OpenRouter receives strict `response_format=json_schema` and the rest of supported providers receives more local validation. `MAX_ASSERTIONS` is also expressed as `maxItems` and checked when returned.

** Type of model needed.** Multilingual information extraction model with very good obedience to schemes, coverage of facts, resolution of correlations and taxonomic normalization. You do not need to browse the Internet or solve the truth of the news. You should prefer precision to creativity and work at low temperature.

**Main risk.** It is the largest point of propagation: an omitted, composite, poorly contextualized or poorly classified assertion conditions the routing, the recovery of evidence, the validators and the final result.

**Settings found.**The Kubernetes database uses `google/gemini-2.5-flash-lite` via OpenRouter; production overwrites the model with `openai/gpt-5-nano`. The `.env` file for development should not be taken as a description of deployment.

### `api/source-router`

**Use.** The search engine discovers a closed list of candidate domains. The LLM assigns to each type of source, level of authority, jurisdictions, topics, classes of evidence, languages and degree of coincidence with the requested path. It should not search for domains, select sources or decide if the assertion is true.

**Existing guards.** The code rejects domains that are not in the entry, validates the enums and JSON Schema, normalizes redundant jurisdictions and retrys only the omitted or invalid domains. The persistent profile records the model that made the classification.

** Type of model needed.** Small structured classification model, fast and cheap. The desirable specialization is classification of documentary authority and jurisdiction, not general bordering sound.

**Main risk.** Confused a secondary domain or impostor with an official source. LLM should not be the border of trust: allowlists, domain identity, signed metadata and rules by jurisdiction should prevail over its classification.

**Settings found.** The base uses `google/gemini-2.5-flash-lite` via OpenRouter.

### `api/validate-asertions`

The same module executes three epistemologically distinct tasks. They should not be compared as if they were just changing prompt.

#### Tipo 1: `LLM_MEMORY_VALIDATION`

You decide with parametric and logical knowledge, without recovered corpus. The server marks the base of the result as `MODEL_KNOWLEDGE`. It needs comprehensive general knowledge, good calibration and willingness to respond `UNKNOWN`.

A border model can improve reasoning, but does not provide traceability or guarantee currentity. That is why the default consensus weight is `0.25` and it is not recommended to spend the most expensive model here.

#### Tipo 2: `LLM_SEARCH_VALIDATION`

It is only implemented for OpenRouter. The code adds `:online` to the model identifier and the search remains within the provider. OpenRouter documents that `:online` activates its web plugin and returns standardized dating annotations, but the current Assermetry adapter retains only `message.content`; it does not capture `message.annotations`.

Therefore, declared sources cannot be verified against a controlled corpus and the result is marked `PROVIDER_SEARCH_UNVERIFIED`. It requires a competent model in search, source synthesis and calibration, but its signal must continue to weigh less than RAG. The current default weight is `0.5`.

#### Tipo 3: `RAG_EVIDENCE_VALIDATION`

`source-router` and `evidence-search` obtain the corpus. The prompt requires exclusively to use the delivered fragments and cite their `context_id`. After inference, the server reconstructs the citations from the corpus and converts a `TRUE` or `FALSE` without verifiable support in `UNKNOWN`.

**Type of model needed.** Model of reasoning on evidence with excellent detail: must distinguish direct support, contradiction, insufficient context, partial coincidences and changes of entity, date, magnitude or jurisdiction. It must also resist hostile instructions contained within recovered documents.

This is the only use where the strongest generalist model is systematically justified. The most user-friendly should be a second multilingual NLI/fact-trained sorter verification that scores each pair `aserción-fragmento`. It should not replace the LLM that is the expansion: it should function as an independent check and cause `UNKNOWN` when both disagree.

**Settings found.** The three local and prod workers are RAG and use, via OpenRouter, `meta-llama/llama-3.1-8b-instruct`, `qwen/qwen3-30b-a3b-instruct-2507` and `mistralai/mistral-small-24b-instruct-2501`. Each worker also changes the evidence strategy (`EXT_ONLY_OFFICIAL`, `EXT_OFFICIAL_FIRST` and `LOCAL`).The diversity of families is positive to avoid correlated errors, but `mistral-small-2501` is already listed as removed in the current Mistral catalog and must migrate.

Type 4 (`DETERMINISTIC_VALIDATION`) and type 5 (`HUMAN`) do not execute automatic LLM inference.

### Shared infrastructure and administration

`api/common/llm` abstracts `mistral`, `gemini`, `openrouter` and `grok`, with synchronous and asynchronous calls, retrying, token counting and JSON validation. It is not a fourth case of use: it is the transport layer of the above.

OpenRouter receives `response_format=json_schema`, `strict=true` and `provider.require_parameters=true` when the caller provides a Pydantic model or a schema. The common layer normalizes the Pydantic schema to the strict subset accepted by OpenAI/OpenRouter and omits `temperature` in structured requests not to exclude models that do not support that parameter. This prevents deliberately routing to endpoints that ignore the parameter, although the provider documentation warns that exact compliance may vary by endpoint.

`generate-asertions`, `source-router` and `validate-asertions` use this same structured path. The router retains a local deliberation exception: it validates each rating separately to retrieve valid rows, then the provider receives the full schema. RAG validators use a specific contract that requires verdict, trust and reference `context_id`; they also maintain the surrounding deterministic check. Each candidate must first pass a real payload compatibility test, not only in the catalog.

`api/admin` terms `/api/v1/models` without calling a LLM. It maintains a general ranking of calidad/precio for compatibility, but the main administrative view uses profiles cured by load: extraction, routing, RAG per strategy, search and memory. It combines the effective configuration of each service with the current price of the catalog and calculates the current cost, recommended and its differential over a sample of tokens visible. The GUI allows sensing `max_news_cost_usd`: a global budget for a news of five years old, including the premium.

## Weighting the need for quality

The score weighs impact on the result (30 %), difficulty of reasoning and grounding (25 %), spread of error (20 %), structured output requirement (15 %) and need for actualidad/busqueda (10 %). The investment column shares the evaluation and optimization effort; **is not the voting weight in the consensus nor an exact cost share per tokens**.

| Uso | Score | Guidance investment | Nivel recomendado | Specialization |
|---|---:|---:|---|---|
| RAG validation | 4.45/5 | 35 % | High-end or border | Yes: entailment/NLI and grounding |
| Generation of assertions | 4.05/5 | 30 % | Gama media-alta | Yes: strict extraction and schema |
| Validation with online search | 3.75/5 | 15 % | Medium-high range with search | Yes: search and synthesis with quotations |
| Source classification | 3.40/5 | 15 % | Small/fast | Yes: classification; many rules can be deterministic |
| Memory Validation | 2.55/5 | 5 % | Gama media | No; prioritize calibration and `UNKNOWN` |

Conclusion: if only one model can be improved, it must be RAG. If two can be improved, the second is `generate-asertions`. The router must not compete for the same inference budget as those two uses.

## Candidatos a evaluar

The list is based on official catalogues consulted at the revision date. It does not state that a model is better for this project without running the Assermetry benchmark. OpenRouter allows using its own slugs; Gemini and Mistral can also be used by its direct adapters. In production a specific version must be set after the evaluation, instead of relying on alias `latest`.

| Familia/candidato | Papel candidato | Reason for including | Caution |
|---|---|---|---|
| `openai/gpt-6-astra` | Premium RAG and judge of reference | Maximum capacity model for difficult cases | Coste/latencia high; try Schema by OpenRouter |
| `openai/gpt-5.6-sol` | RAG premium | Strong alternative to the maximum model | Oversized for router |
| `openai/gpt-5.6-terra` | Generation, balanced RAG and online search | Official balance between capacity and cost | Measure factual calibration, not infer it from commercial positioning |
| `openai/gpt-5.6-luna` | Router and high volume generation | Orientado a cargas sensibles a coste | Do not adopt it for RAG without exceeding retailing and dating |
| `google/gemini-3.1-pro-preview` | Premium RAG and judge of reference | Pro Family for Complex Reasoning | It's preview; not fix it as the only critical provider |
| `google/gemini-3.8-flash` | Generation, router and balanced RAG | Current Flash, Great Context and Documented Structured Output | Verify current schema compatibility in the chosen endpoint |
| `google/gemini-3.5-flash-lite` | High Volume Router | Small variant for cheap sorting | Do not assume that it fixes the problem observed with 2.5 Flash-Lite |
| `anthropic/claude-sonnet-5` | Premium RAG and diversity of ensemble | Second family of reasoning available in OpenRouter | Only via OpenRouter with current code |
| `mistralai/mistral-medium-3-5` | Balanced generation/ADR and European option | Chat Supplements and Structured Outputs Official | Evaluate Spanish and retail with your own corpus |
| `mistral-small-2603` | Router, memory and economic generation | Current replacement of the old Small line; structured exit | Do not use savings as a substitute for the RAG benchmark |

Reasonable initial settings for the benchmark:

- **RAG:** GPT-6 Astra, GPT-5.6 Sol, Gemini 3.1 Pro Preview, Claude Sonnet 5 and
  Mistral Medium 3.5.
- **Generation:** GPT-5.6 Terra, Gemini 3.8 Flash and Mistral Medium 3.5; add Moon or
Mistral Small 4 as an economic baseline.
- **Router:** GPT-5.6 Luna, Gemini 3.5 Flash-Lite and Mistral Small 4.
- **Online:** the `:online` variants of GPT-5.6 Terra, Gemini 3.8 Flash and Claude Sonnet 5,
after implementing the capture and persistence of citation annotations.
- **Memory:** one of the previous balanced models, never as the main source of
for recent events.

It is not appropriate to use the same model in all validators: the diversity of provider and family reduces correlated failures. Nor should a change of model and a change of corpus/estrategia search be mixed in the same comparison, because one would not know which explains the result.

## Minimum evaluation before changing models

Build a versioned set in Spanish and other supported languages, with true, false and genuinely undetermined cases. It must include denials, close numbers, dates, homonyms, change of jurisdiction, conflicting sources, irrelevant fragments and prompt injection within the evidence.

Measure by task:

- **Generation:** schema validity, precision and recall of central assertions, atomism,
text fidelity, contexto/taxonom accuracy and subsequent recovery success.
- **Router:** `authority_level` accuracy, jurisdiction and source type; recall of
official sources; accepted impostors rate; abstentions and omitted domains.
- **RAG:** `TRUE/FALSE/UNKNOWN` macro-F1, calibration, citation accuracy, coverage of
decisive evidence and rate of decisive verdicts degraded to `UNKNOWN` by grounding.
- **Online:** accuracy, current affairs, domain quality and percentage of recoverable appointments.
- **Memory:** calibration and correct use of `UNKNOWN`, separated by age from the event.
- **Operation:** p50/p95 of latency, errors, retry, invalid JSON and cost per news
Complete, not just by call.

The promotion criterion should impose thresholds, not a single average. For RAG, for example, a model should not approve if it improves F1 but increases false quotes or unsupported decisive verdicts.

## Recommended architecture changes

1. Add an explicit `task` to the configuration (`ASSERTION_EXTRACTION`,
`SOURCE_CLASSIFICATION`, `RAG_VERDICT`, etc.) and maintain model selection by task.
2. Make the three RAG validators use different families and existing models;
different evidence strategies, but evaluate them separately.
3. Add a multilingual NLI verifier as the second signal of the RAG.
LLM or insufficient evidence, produce `UNKNOWN`, do not force majority.
4. Capture `message.annotations` and search metadata in `LLMResponse.raw_metadata`;
validate and persist online mode quotes before increasing your weight.
5. Recover Structured Outputs for `generate-asertions` via OpenRouter with endpoints only
support it and always maintain local Pydatic validation.
6. Replace `admin` quality heuristics with capacity filters
(`structured_outputs`, required parameters, context, version/withdrawn) more metrics of your own benchmark.
7. Register on each provider run, exacto/versionado slug, prompt versioned,
temperature, tokens, latency, evidence strategy and corpus hashes. Without this there is no reproducible comparison or complete audit.

## Repository references

- [`api/generate-asertions/main.py`](../../api/generate-asertions/main.py)
- [`api/source-router/app/classifier.py`](../../api/source-router/app/classifier.py)
- [`api/validate-asertions/main.py`](../../api/validate-asertions/main.py)
- [`api/common/llm`](../../api/common/llm)
- [`api/admin/main.py`](../../api/admin/main.py)
- [`k8s/apis/generate-asertions/configmap.yaml`](../../k8s/apis/generate-asertions/configmap.yaml)
- [`k8s/apis/source-router/base/configmap.yaml`](../../k8s/apis/source-router/base/configmap.yaml)
- [`k8s/apis/validate-asertions`](../../k8s/apis/validate-asertions)

## External sources

- [Catálogo oficial de modelos de OpenAI](https://developers.openai.com/api/docs/models)
- [Catálogo oficial de Gemini](https://ai.google.dev/gemini-api/docs/models)
- [Structured Outputs de Gemini](https://ai.google.dev/gemini-api/docs/structured-output)
- [Catálogo oficial de Mistral](https://docs.mistral.ai/models)
- [Structured Outputs de OpenRouter](https://openrouter.ai/docs/guides/features/structured-outputs)
- [Búsqueda web de OpenRouter](https://openrouter.ai/docs/guides/features/plugins/web-search)
- [Catálogo API de OpenRouter](https://openrouter.ai/api/v1/models)


## Benchmark Historical Profiles

[tests/llm-benchmark/llm-benchmark.py](../../tests/llm-benchmark/llm-benchmark.py) allows you to compare complete OpenRouter configurations exclusively on a versioned case. The runner captures the effective configuration, applies each profile, executes LIGHT commands, calculates estimated quality and costs, persists JSON and SQLite and restores the initial configuration. The procedure, profile scheme, score and recovery guarantees are described in [docs/tests/llm-benchmark.md](../tests/llm-benchmark.md).
