# Example: Optimizing LLM configurations with a maximum of 0.05 USD

This procedure generates and executes LLM profiles at an estimated maximum cost of 0.05 USD per news item using the historical benchmark.

Do not run against production. The runner temporarily modifies LLM configuration, consumes quota and restores configuration at completion.

## 1. Environment variables

From the root of the repository:

    cd /home/adminu/blockchain/tfm

Set up the local Gateway and Keycloak service client:

    export ASSERMETRY_API_URL='https://localhost:7443/backend'
    export ASSERMETRY_TLS_VERIFY=false
    export ASSERMETRY_KEYCLOAK_REALM='TrustNews'
    export ASSERMETRY_KEYCLOAK_CLIENT_ID='TrustNewsApi'

Enter the secret without writing it in the shell history:

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

The secret is not kept in the artifacts of the benchmark.

## 2. Generate profiles under budget

It generates a plan with a maximum requested of 0.05 USD and a margin of 5%:

    python3 tests/llm-benchmark/llm-benchmark.py generate-profiles \
      --max-news-cost-usd 0.05 \
      --budget-headroom-percent 5 \
      --output-root tests/llm-benchmark/artifacts/generated

The maximum effective amount will be $0.0475. The command prints a path as:

    LLM_PROFILE_PLAN tests/llm-benchmark/artifacts/generated/openrouter-plan-.../plan.json

Save that path to a variable:

    export PLAN_PATH='tests/llm-benchmark/artifacts/generated/openrouter-plan-.../plan.json'
    export PLAN_DIR="$(dirname "$PLAN_PATH")"

Check the accepted and discarded profiles:

    sed -n '1,260p' "$PLAN_PATH"

The plan retains the effective configuration, price snapshots, hashes and reasons why a level was discarded.

## 3. Validate case and profiles

Validation does not modify configuration or create commands:

    for profile in "$PLAN_DIR"/profiles/*.json; do
      python3 tests/llm-benchmark/llm-benchmark.py validate-profiles \
        --case tests/llm-benchmark/resources/cases/eu-news-2025-v1.json \
        --profile "$profile"
    done

## 4. Execute five repetitions

To compare quality, keep the Evidence Search cache during this first run:

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile-plan "$PLAN_PATH" \
      --repetitions 5 \
      --require-costs \
      --artifacts-root tests/llm-benchmark/artifacts \
      --database tests/llm-benchmark/artifacts/history.sqlite

The runner captures the configuration, applies each profile, checks the cost, executes commands in `LIGHT` mode and restores the initial configuration.

## 5. Optional cold execution

To measure behavior without any cached responses, indicate the direct URL of Evidence Search and clear the cache before each repeat:

    export ASSERMETRY_EVIDENCE_SEARCH_URL='http://localhost:8074'

    python3 tests/llm-benchmark/llm-benchmark.py run \
      --profile-plan "$PLAN_PATH" \
      --repetitions 5 \
      --require-costs \
      --clear-evidence-cache

This option only cleans `evidence_search_cache_v2`. It does not remove domain profiles or modify `source_routes_v2`.

## 6. Analizar resultados

List of saved executions:

    python3 tests/llm-benchmark/llm-benchmark.py list-runs \
      --database tests/llm-benchmark/artifacts/history.sqlite \
      --limit 30

The reports are kept in:

    tests/llm-benchmark/artifacts/<batch-id>/report.md
    tests/llm-benchmark/artifacts/<batch-id>/summary.json

Compara dos ejecuciones concretas:

    python3 tests/llm-benchmark/llm-benchmark.py compare \
      --database tests/llm-benchmark/artifacts/history.sqlite \
      --baseline <run-id-base> \
      --candidate <run-id-candidato>

The winning configuration must meet these conditions:

1. All relevant repetitions end in `PASS`.
2. The standard cost of five assertions does not exceed USD 0.05.
3. It has the highest medium quality and good accuracy of verdicts.
4. It maintains complete validations and sufficient evidence.
5. If quality is practically the same, the cheapest is chosen.

The current generator compares the global levels `premium-safe`, `balanced-safe` and `budget-safe`. It does not yet list all possible hybrid combinations between modules; if only one profile under USD 0.05 appears, the benchmark confirms its viability, but does not prove that it is the best hybrid combination possible.
