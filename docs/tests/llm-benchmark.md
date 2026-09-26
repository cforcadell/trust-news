# Benchmark LLM configurations historical

tests/llm-benchmark/llm-benchmark.py compares complete configurations of LLM modules using OpenRouter exclusively. It executes LIGHT commands, retains immutable JSON artifacts and indesulates metrics in SQLite to compare them with time.

It should not be run against production. The runner temporarily changes the effective configuration and consumes generation and validation quota.

## Scope

The initial case tests/llm-benchmark/resources/cases/eu-news-2025-v1.json contains the synthetic news about Sweden, Germany, Italy and Spain and four expected results. The runner measures separately:

- extraction and correspondence of assertions;
- category;
- veredicto agregado;
- a validator verdict;
- evidence used by RAG validators;
- completed responses and latency of validators;
- cost estimated per module and global.

The sample has four assertions. Two costs are saved:

- sample_total_usd: estimation for the actually generated assertions;
- normalized_5_assertions_total_usd: estimate standardized to five assertions,
compatible with the administrative hearing of recommendations.

The current cost is an estimate based on the prices of the OpenRouter catalog and token samples configured in api/admin. Although the LLM adapter reads use from the supplier, the orders still do not persist these tokens; therefore the report does not present the cost as actual billing.

## Requirements

- Python 3.11 or later. sqlite3 is part of Python and does not require installation
  SQLite ni paquetes adicionales.
- Local deployment accessible, default in https://localhost:7443/backend.
- User with sufficient administrative role and quotas.
- All LLM components and validators included must use OpenRouter.
- No other person or automation should change settings during
The batch.

Password is never written in artifacts.

`TrustNewsApi` service client recommends `client_credentials`:

    export ASSERMETRY_KEYCLOAK_CLIENT_ID='TrustNewsApi'
    read -rsp 'TrustNewsApi client secret: ' ASSERMETRY_KEYCLOAK_CLIENT_SECRET
    export ASSERMETRY_KEYCLOAK_CLIENT_SECRET

El script obtiene y renueva el token cuando sea necesario. El secreto nunca se
escribe en los artefactos.

    export ASSERMETRY_ACCESS_TOKEN='...'

or, if the Keycloak client allows Direct Access Grants:

    export ASSERMETRY_USERNAME='benchmark-admin'
    read -rsp 'Password: ' ASSERMETRY_PASSWORD
    export ASSERMETRY_PASSWORD

The local environment normally uses a self-signed certificate. The TLS verification is disabled by default for this local runner. For a trust certificate:

    export ASSERMETRY_TLS_VERIFY=true

## Networkless validation

This command validates the case and profile schema and checks that everyone declares OpenRouter:

    python3 tests/llm-benchmark/llm-benchmark.py validate-profiles \
      --profile tests/llm-benchmark/resources/profiles/current-openrouter.json \
      --profile tests/llm-benchmark/resources/profiles/example-balanced-openrouter.json

It does not modify settings, does not use credentials, and does not create commands.

## Generation of profiles by budget

`generate-profiles` consults the effective configuration and OpenRouter catalog, but does not change models or create commands. This example requests a maximum of USD 0.25 for a news of five average assertions:

    python3 tests/llm-benchmark/llm-benchmark.py generate-profiles \
      --max-news-cost-usd 0.25

By default, it reserves a margin of 5%. Therefore, with a maximum requested of 0.25 USD, it only generates configurations whose estimated cost does not exceed 0.2375 USD. The margin can be changed explicitly:

    python3 tests/llm-benchmark/llm-benchmark.py generate-profiles \
      --max-news-cost-usd 0.25 \
      --budget-headroom-percent 10

The output is saved in `tests/llm-benchmark/artifacts/generated/<plan-id>/` and includes:

    plan.json
    effective-configuration.json
    pricing-snapshot.json
    profiles/premium-safe.json
    profiles/balanced-safe.json
    profiles/budget-safe.json

Only the profiles that the endpoint can verify under the maximum effective level appear. The levels with the same configuration are deduplicated and recorded in `plan.json` as discarded. Each validator uses an exact ID selector so that the plan does not change meaning if later validators of the same type are added. The plan retains date, budget, margin, prices, hash of the effective configuration and hash of each profile.

The generation fails safely if the price of any component or LLM validation is missing, if any does not use OpenRouter or if the configuration changes between capture and recommendation. Prices may change after generating the plan; therefore the execution always checks the cost.

To execute all the profiles of a plan:

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile-plan tests/llm-benchmark/artifacts/generated/<plan-id>/plan.json \
      --repetitions 5 \
      --require-costs

`run --profile-plan` checks the hashes, inherits the maximum effective plan and does not allow you to relax using `--max-news-cost-usd`. A lower maximum can be indicated. `--profile` and `--profile-plan` are mutually exclusive.

## Implementation

Current baseline, three repetitions:

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile tests/llm-benchmark/resources/profiles/current-openrouter.json \
      --repetitions 3

Compare two profiles and require a maximum standard of 0.25 USD per news:

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile tests/llm-benchmark/resources/profiles/current-openrouter.json \
      --profile tests/llm-benchmark/resources/profiles/example-balanced-openrouter.json \
      --repetitions 5 \
      --max-news-cost-usd 0.25 \
      --require-costs

### Evidence Search Cache

By default, the runner retains `evidence_search_cache_v2`. This is the right option to compare models with evidence already recovered, although for a reproducible quality comparison a frozen corpus is recommended.

To measure each cold repeat, you can empty the Evidence Search response cache immediately before publishing the order:

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile tests/llm-benchmark/resources/profiles/current-openrouter.json \
      --repetitions 3 \
      --clear-evidence-cache

The local display publishes Evidence Search in `http://localhost:8074`. If it is not accessible at that address, you can indicate your direct URL:

    export ASSERMETRY_EVIDENCE_SEARCH_URL='http://localhost:8074'

or use `--evidence-search-url`. Cleaning is recorded in `manifest.json` and in each `run.json`, including the collection and number of deleted documents. If cleaning fails, that repetition fails without publishing the command.

The flag does not remove `domain_profiles_v1` or modify `source_routes_v2`. Domain profiles are stable data, not a cache. Furthermore, a `FRESH` path can prevent the execution of `source-router` LLM; therefore, this flag alone is not enough to compare Cold Source Router models.

The example-balanced-openrouter profile is a template. You need to review the availability and price of your models before using it.

The runner:

1. adquiere /tmp/assermetry-llm-benchmark.lock;
2. captures the complete effective configuration;
3. resolves $current and applies the profile;
4. confirms the effective configuration;
5. capture recommendations and prices;
6. rejects the configuration if it fails to comply with the requested budget;
7. executes repetitions in LIGHT mode;
8. keeps order, score and costs even when a repeat fails;
9. restores the initial configuration in a finally block;
10. returns code other than zero for faults or incomplete restoration.

The lock prevents two simultaneous runners in the same host. It is not a block distributed between machines.

## Perfiles

A profile has schema_version 1, a stable id, components and rules for validators. Concept example:

{ "schema_version": 1, "id": "candidate-a", "components": { "generate-assertions": { "provider": "openrouter", "model": "modelo/generador", "temperature": 0 }, "source-router": { "provider": "openrouter", "model": "modelo/router", "temperature": 0 } }, "validators": [{ "selector": {types": ["RAG_EVIDENCE_VALIDATION"], "strategies": ["LOCAL"] }, "provider": "openrouter", "model": "modelo/rag", "temperature": 0 }}}}

Selectors support id, types and strategies. Rules are processed in order; if several match, the latter prevails. Each discovered LLM validator must be covered. $current retains the effective model, but continues to require its provider to be OpenRouter.

To attribute causes it is recommended to change a module each time. Full profiles should be reserved for already filtered candidates.

## Score

The quality score is from 0 to 100:

| Area | Peso |
|---|---:|
| Extraction, coverage, accuracy, quantity and category | 25 % |
| Added Verdict versus Expected | 45 % |
| Evidence used by RAG validators | 20 % |
| Validaciones completadas | 10 % |

If a metric does not apply, its weights are normalized between the remaining ones. The pairing of assertions is deterministic and uses the required_terms of the case. Each change of case or criterion must create a new version, not alter historical results.

Four assertions are not enough for strong statistical conclusions. At least three repetitions and preferably five are recommended. A frozen corpus must also be used to evaluate RAG; external searches are current, not reproducibility.

## Artefactos

By default they are created:

    tests/llm-benchmark/artifacts/
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

JSONs are canonical evidence. SQLite is a historical index append-only with batches, executions, costs per module, results by assertion and metrics. Artifacts are excluded from Git.

## History and comparison

List the latest executions:

    python3 tests/llm-benchmark/llm-benchmark.py list-runs --limit 20

Comparar dos run_id:

    python3 tests/llm-benchmark/llm-benchmark.py compare \
      --baseline <run-id-base> \
      --candidate <run-id-candidato>

The comparison shows differences in quality, accuracy, sample cost, standard cost and duration. A lower cost produces a negative delta.

## Recovery

If the process receives a normal exception, try to restore the configuration. SIGKILL, machine loss or network failure during restoration may prevent it. Before running it saves initial-configuring.json. If restare.json indicates FAIL, it is necessary to restore those values from the LLM administration and verify the effective configuration before starting another batch.

Passwords, tokens, and provider keys are never included in profiles, SQLite, or artifacts.
