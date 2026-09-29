# Historical LLM Configuration Benchmark

`tests/llm-benchmark/llm-benchmark.py` compares complete OpenRouter LLM configurations through the existing LIGHT order flow. It temporarily applies a profile, publishes a news item, stores immutable JSON artifacts, indexes results in SQLite, and restores the initial configuration. Do not run it against production: it changes the effective local configuration and consumes generation and validation quota.

The default case is `tests/llm-benchmark/resources/cases/eu-news-2025-v1.json`. It measures assertion extraction and matching, category accuracy, aggregate and per-validator verdicts, RAG evidence use, completed responses, latency, and estimated module and total cost. The sample has four assertions; it is useful for regression checks, not for statistical conclusions. Run at least three repetitions, preferably five, and version a case rather than changing historical expectations.

## Requirements and authentication

Python 3.11 or newer is required; SQLite is part of Python. The default endpoint is `https://localhost:7443/backend`. All selected components and validators must use OpenRouter, and no other administrator or automation should change configuration during a batch.

Use the `TrustNewsApi` service client where possible:

```bash
export ASSERMETRY_KEYCLOAK_CLIENT_ID='TrustNewsApi'
read -rsp 'TrustNewsApi client secret: ' ASSERMETRY_KEYCLOAK_CLIENT_SECRET
export ASSERMETRY_KEYCLOAK_CLIENT_SECRET
```

The runner obtains and refreshes its token. `ASSERMETRY_ACCESS_TOKEN` is also supported, as are `ASSERMETRY_USERNAME` and `ASSERMETRY_PASSWORD` when Direct Access Grants are enabled. Credentials, tokens, and provider keys are never written to profiles, SQLite, or artifacts. Local TLS verification is disabled by default because the local deployment commonly uses a self-signed certificate; set `ASSERMETRY_TLS_VERIFY=true` or pass `--verify-tls` for a trusted certificate.

## Commands

### `validate-profiles`

Validates the case and profile schemas without network access, credentials, configuration changes, or orders:

```bash
python3 tests/llm-benchmark/llm-benchmark.py validate-profiles \
  --profile tests/llm-benchmark/resources/profiles/current-openrouter.json \
  --profile tests/llm-benchmark/resources/profiles/example-balanced-openrouter.json
```

| Flag | Meaning and accepted values |
|---|---|
| `--case PATH` | Case JSON to validate. Defaults to the EU news v1 case. |
| `--profile PATH` | Profile JSON to validate. Repeat it to validate several profiles. If omitted, the current OpenRouter profile is used. |

### `generate-profiles`

Reads the effective configuration and OpenRouter prices to generate complete profiles below a news-level cost cap. It does not change configuration or publish orders. It fails if a needed price is missing, a component is not OpenRouter, or configuration changes during planning.

```bash
python3 tests/llm-benchmark/llm-benchmark.py generate-profiles \
  --max-news-cost-usd 0.25 --budget-headroom-percent 10
```

The default 5% headroom means a `0.25` cap accepts estimates up to `0.2375`. Plans are written below `tests/llm-benchmark/artifacts/generated/<plan-id>/` and include pricing, effective configuration, hashes, and deduplicated profiles.

| Flag | Meaning and accepted values |
|---|---|
| `--max-news-cost-usd NUMBER` | Required positive USD cap for one news item. |
| `--budget-headroom-percent NUMBER` | Non-negative percentage reserved below the cap; default `5.0`. |
| `--output-root PATH` | Parent directory for generated plans; default is the benchmark generated-plans directory. |
| `--plan-id STRING` | Optional stable plan directory name. If omitted, the runner creates one. |
| `--base-url URL` | Admin/API base URL; default `ASSERMETRY_API_URL` or the local backend URL. |
| `--http-timeout SECONDS` | Positive HTTP request timeout; default `30`. |
| `--verify-tls` / `--no-verify-tls` | Enable or disable TLS certificate verification. The default follows `ASSERMETRY_TLS_VERIFY`, otherwise false. |

### `run`

Runs one or more profiles sequentially in LIGHT mode. It locks the local host, captures and verifies configuration, estimates cost, runs every repetition, writes artifacts even when a repetition fails, and restores configuration in a `finally` block. `SIGKILL`, host loss, or network loss during restoration can still leave configuration changed.

```bash
python3 tests/llm-benchmark/llm-benchmark.py run \
  --profile tests/llm-benchmark/resources/profiles/current-openrouter.json \
  --profile tests/llm-benchmark/resources/profiles/example-balanced-openrouter.json \
  --repetitions 5 --max-news-cost-usd 0.25 --require-costs
```

`--profile-plan` validates plan hashes and inherits its effective cost cap. It cannot be combined with `--profile`; a stricter `--max-news-cost-usd` is allowed, but a looser cap is not.

| Flag | Meaning and accepted values |
|---|---|
| `--case PATH` | Case JSON to publish; defaults to the EU news v1 case. |
| `--profile PATH` | Profile JSON. Repeat for multiple profiles. Mutually exclusive with `--profile-plan`. Defaults to the current OpenRouter profile when neither selector is supplied. |
| `--profile-plan PATH` | `plan.json` produced by `generate-profiles`; mutually exclusive with `--profile`. |
| `--repetitions INTEGER` | Positive number of runs per profile; default `3`. |
| `--base-url URL` | Backend URL; default `ASSERMETRY_API_URL` or `https://localhost:7443/backend`. |
| `--artifacts-root PATH` | Parent directory for JSON artifacts and SQLite history. |
| `--database PATH` | SQLite history file; defaults to `history.sqlite` under the artifacts root. |
| `--batch-id STRING` | Optional stable batch identifier. It must not overwrite an existing batch directory. |
| `--result-timeout SECONDS` | Positive maximum wait for a terminal order; default `600`. |
| `--poll-interval SECONDS` | Non-negative delay between order polls; default `2`. |
| `--http-timeout SECONDS` | Positive HTTP request timeout; default `30`. |
| `--max-news-cost-usd NUMBER` | Optional positive per-news USD cap. With a plan it can only make the plan cap stricter. |
| `--require-costs` | Fail a run when cost inputs or estimates are unavailable. |
| `--stop-on-failure` | Stop remaining repetitions/profiles after the first failed repetition. |
| `--lock-file PATH` | Local-host lock path; default `/tmp/assermetry-llm-benchmark.lock`. It is not a distributed lock. |
| `--clear-evidence-cache` | Deletes `evidence_search_cache_v2` before each repetition. It does not delete domain profiles or routes, so it is not equivalent to a fully cold Source Router run. |
| `--evidence-search-url URL` | Direct Evidence Search URL used only with `--clear-evidence-cache`; default `ASSERMETRY_EVIDENCE_SEARCH_URL` or `http://localhost:8074`. |
| `--verify-tls` / `--no-verify-tls` | Enable or disable certificate verification as described above. |

### `list-runs` and `compare`

```bash
python3 tests/llm-benchmark/llm-benchmark.py list-runs --limit 20
python3 tests/llm-benchmark/llm-benchmark.py compare \
  --baseline <baseline-run-id> --candidate <candidate-run-id>
```

| Command | Flag | Meaning and accepted values |
|---|---|---|
| `list-runs` | `--database PATH` | SQLite history file to read. |
| `list-runs` | `--limit INTEGER` | Maximum number of latest records to print; default `20`. |
| `compare` | `--database PATH` | SQLite history file to read. |
| `compare` | `--baseline RUN_ID` | Required historical run identifier used as the comparison baseline. |
| `compare` | `--candidate RUN_ID` | Required historical run identifier compared with the baseline. |

A comparison reports deltas for quality, accuracy, sample cost, standardized cost, and duration. Lower cost is represented by a negative delta.

## Evidence cache and reproducibility

The runner normally preserves `evidence_search_cache_v2`, which is useful when comparing configurations against already recovered evidence. `--clear-evidence-cache` measures fresh Evidence Search responses but does not force Source Router discovery/classification. For identical, frozen evidence across validators, use the shared evaluation runners described below.

## Profiles, scoring, and artifacts

A profile has `schema_version: 1`, a stable `id`, component settings, and validator rules. Every discovered LLM validator must be covered. Selectors may use `id`, `types`, and `strategies`; matching rules are evaluated in order and the last match wins. `$current` retains the currently effective model but still requires an OpenRouter provider. Change one module at a time for causal comparison; reserve full profiles for already filtered candidates.

The 0–100 quality score weights extraction (25%), aggregate verdict (45%), RAG evidence use (20%), and completed validations (10%). Inapplicable metrics redistribute their weight. Costs are estimates based on the OpenRouter catalog and configured token samples, not invoice amounts, because orders do not persist provider token usage.

Artifacts are immutable JSON evidence. Each batch contains its manifest, starting configuration, summary, Markdown report, resolved profile, configuration changes, pricing snapshot, preflight costs, restoration result, and one `order.json`, `score.json`, `costs.json`, and `run.json` per repetition. SQLite is an append-only historical index. Artifacts are ignored by Git.

If `restore.json` reports failure, restore the saved initial values through LLM administration and confirm the effective configuration before another batch.

## Shared evaluation and frozen evidence

The historical CLI and SQLite reports remain supported. New historical repetitions additionally write `repetition-NN/evaluation/<run_id>.json` in the common evaluation-result schema. Dataset loading, artifact writing, assertion matching, and LIGHT publish/poll execution are shared with `tests/evaluation`.

Use `PYTHONPATH=tests python -m evaluation.llm_benchmark --mode gold-evidence` to compare validators on identical evidence, `--mode replay` to rerun a saved validator input, and `PYTHONPATH=tests python -m evaluation.pipeline` for stage diagnostics and controlled counterfactuals. Analyze a saved campaign from either runner without network calls or credentials:

```bash
PYTHONPATH=tests python3 -m evaluation.pipeline --analyze tests/evaluation/artifacts/CAMPAIGN_ID
```

The command writes `analysis/analysis.json` and `analysis/analysis.md` in the campaign directory. It reports observations for each validation, including selected and retrieved sources, citation IDs, evidence handoff, verdicts, and technical errors. It marks routing or source relevance as `NOT_EVALUATED` when the dataset has no acceptable domain or reference annotations. See [Shared evaluation](evaluation.md) for output details, flags, v2 datasets, cache modes, hashes, and root-cause rules.
