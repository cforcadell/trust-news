# Reproducible regression of the classic frontend

This directory contains two levels of execution:

- `ui-smoke-test.js` runs a single stage using Chrome DevTools
Protocol, without Playwright, Selenium or NPM dependencies;
- `run-regression.js` validates and executes the synthetic cases sequentially
Light and Blockchain, add your results and return error if any check fails.

The runner is designed for the local/Kind environment served in `https://localhost:7443/gui/`. Chrome accepts the self-signed certificate within an isolated time profile.

## Contenido

```text
tests/frontend/e2e/
├── run-regression.js
├── ui-smoke-test.js
├── artifacts/                  # salidas fechadas, ignoradas por Git
└── resources/
    ├── identities.example.json
    └── cases/
        ├── light.json
        ├── light-news.txt
        ├── blockchain.json
        └── blockchain-news.txt
```

The texts are synthetic. The expected results are structural and operational invariants; the text produced by an LLM is not literally compared.

## What is checked

Each scenario:

1. opens the frontend and completes Keycloak login;
2. publish exactly a news story in the right way;
3. requires a valid `order_id` UUID;
4. follows the order to a terminal state;
5. falla ante timeout, `ERROR`, `FAILED`, `QUOTA_EXCEDED`,
`ASSERTIONS_NOT_AVAILABLE`, `NO_VALIDATORS_AVAILABLE` or any state not allowed by the case;
6. checks mode, command fields, assertions, validations, validators
habilitadas/deshabilitadas earrings and tabs;
7. failure to HTTP responses or console errors not expressly included
in the permitted list;
8. capture desktop and mobile views.

The Blockchain case also requires `cid`, `post_id`, `tx_hash` and the enabled IPFS tab. The Light case requires that disabled tab.

## Requirements

- Node.js 22 or later, by native support of `fetch`, `WebSocket` and
  `AbortSignal.timeout`.
- Google Chrome; default `/usr/bin/google-chrome`.
- The `apis-frontend` profile deployed and accessible.
- Two users pseudonyms of Keycloak with sufficient quotas: one associated with
`org-alpha` and another to `org-beta`.
- Validators available for the categories generated.

`resources/identities.example.json` defines aliases and variable names for administrators, users and API clients of the two organizations. It does not contain real users, passwords or secrets.

## Validate package without running application

Validation checks for JSONs, modes, identities, and news files, without opening Chrome or needing credentials:

```bash
node tests/frontend/e2e/run-regression.js --validate
```

`manifest.json` and `summary.json` are written in `tests/frontend/e2e/artifacts/<run-id>/` and the process ends with zero code if the cases are valid.

## Run Light and Blockchain

Passwords are read interactively and are maintained only in runner environment variables:

```bash
export ASSERMETRY_ORG_ALPHA_USERNAME=regression-alpha-user
read -rsp "Password org-alpha: " ASSERMETRY_ORG_ALPHA_PASSWORD
export ASSERMETRY_ORG_ALPHA_PASSWORD
printf '\n'

export ASSERMETRY_ORG_BETA_USERNAME=regression-beta-user
read -rsp "Password org-beta: " ASSERMETRY_ORG_BETA_PASSWORD
export ASSERMETRY_ORG_BETA_PASSWORD
printf '\n'

node tests/frontend/e2e/run-regression.js

unset ASSERMETRY_ORG_ALPHA_PASSWORD ASSERMETRY_ORG_BETA_PASSWORD
```

The orchestrator assigns a new Chrome profile to each scenario and executes the cases sequentially. The credentials of one organization are not delivered to the other’s scenario and Chrome starts with the sensitive variables removed from its environment.

The final line is one of these:

```text
REGRESSION_RESULT PASS
REGRESSION_RESULT FAIL
```

A `PASS` without data cycle configured certifies functional checks, but `summary.json` maintains `managedState: false`. To affirm that execution starts from a reproducible state, the strict mode described below must be used.

## Initialization and cleaning

The public API does not offer a secure operation to delete a complete command and a Blockchain execution leaves effects not reversible in IPFS and the string. The orchestrator does not delete collections, PVC or other data.

Preparation and cleaning are integrated by two operator-controlled executables:

```bash
export ASSERMETRY_SETUP_HOOK=/ruta/segura/setup-regression
export ASSERMETRY_CLEANUP_HOOK=/ruta/segura/cleanup-regression
export ASSERMETRY_REQUIRE_MANAGED_STATE=true

node tests/frontend/e2e/run-regression.js
```

Hooks are executed directly, without `shell`, arguments or interpolation. They receive these variables:

| Variable | Significado |
| --- | --- |
| `ASSERMETRY_RUN_ID` | Unique execution identifier. |
| `ASSERMETRY_ARTIFACTS_DIR` | Directory where to read or write evidence. |
| `ASSERMETRY_CASES` | Comma-separated list of cases executed. |

Recommended contract:

- `setup` creates or re-establishes exclusively quotas and identity data
declared synthetics;
- Both hooks are idepotent;
- `cleanup` reads `report.json`, acts only on the IDs included in
`createdResources` and retains evidence of withdrawal;
- no attempt is made to reverse a Blockchain transaction or remove IPFS content
by its CID;
- any error returns a code other than zero.

With `ASSERMETRY_REQUIRE_MANAGED_STATE=true`, the absence or failure of one of the hooks causes regression to fail. Without this variable, hooks are optional and their status is reflected in the report.

## Repetir tres veces

Once idepotent hooks are configured, three comparable executions can be obtained:

```bash
for repetition in 1 2 3; do
  ASSERMETRY_RUN_ID="regression-${repetition}" \
    ASSERMETRY_ARTIFACTS_DIR="tests/frontend/e2e/artifacts/regression-${repetition}" \
    node tests/frontend/e2e/run-regression.js || break
done
```

Each repeat must end in `PASS`, start from the same cuotas/datos and keep the same invariants. IDs, timestamps, durations and LLM texts may vary.

## Kubernetes baseline

The orchestrator can capture a photo of nodes, pods, restarts, CPU/memoria consumption and PVC by reading-only operations:

```bash
ASSERMETRY_CAPTURE_K8S_BASELINE=true \
  node tests/frontend/e2e/run-regression.js
```

This creates `kubernetes-baseline.json`. If capture is mandatory:

```bash
ASSERMETRY_REQUIRE_K8S_BASELINE=true \
  node tests/frontend/e2e/run-regression.js
```

In the second case, any `kubectl` failure fails execution.

## Run a single case

The individual runner maintains a compatible interactive mode:

```bash
export ASSERMETRY_USERNAME=regression-alpha-user
read -rsp "Password: " ASSERMETRY_PASSWORD
export ASSERMETRY_PASSWORD

ASSERMETRY_CASE_FILE=tests/frontend/e2e/resources/cases/light.json \
  node tests/frontend/e2e/ui-smoke-test.js

unset ASSERMETRY_PASSWORD
```

Without `ASSERMETRY_CASE_FILE`, it uses `docs/fake_news/news.txt` and Light mode, but that execution is a manual smoke and does not replace the complete synthetic package.

## Settings

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `ASSERMETRY_URL` | `https://localhost:7443/gui/` | Frontend URL. |
| `ASSERMETRY_CASES` | Light and Blockchain cases included | JSON list separated by commas. |
| `ASSERMETRY_CASE_FILE` | Empty | Case used by the individual runner. |
| `ASSERMETRY_RUN_ID` | Date and time | Execution identifier. |
| `ASSERMETRY_ARTIFACTS_DIR` | `tests/frontend/e2e/artifacts/<run-id>` | Aggregate evidence. |
| `ASSERMETRY_ORG_ALPHA_USERNAME` | Obligatoria | User name of Light case. |
| `ASSERMETRY_ORG_ALPHA_PASSWORD` | Obligatoria | Light case password; never reported. |
| `ASSERMETRY_ORG_BETA_USERNAME` | Obligatoria | Pseudonymous user of Blockchain case. |
| `ASSERMETRY_ORG_BETA_PASSWORD` | Obligatoria | Blockchain case password; never reported. |
| `ASSERMETRY_RESULT_TIMEOUT_MS` | Case value | Monitoring limit. |
| `ASSERMETRY_CDP_TIMEOUT_MS` | `15000` | Timeout of each CDP operation. |
| `ASSERMETRY_DEBUG_PORT` | `9223` | First CDP port; increases by case. |
| `ASSERMETRY_MOBILE_WIDTH` | `390` | Mobile width. |
| `ASSERMETRY_MOBILE_HEIGHT` | `844` | High cell phone. |
| `CHROME_BIN` | `/usr/bin/google-chrome` | Executable from Chrome. |
| `ASSERMETRY_STOP_ON_FAILURE` | `false` | Do not start any more cases after the first failed. |
| `ASSERMETRY_SETUP_HOOK` | Empty | Impotent preparation executable. |
| `ASSERMETRY_CLEANUP_HOOK` | Empty | Executable for confined cleaning. |
| `ASSERMETRY_REQUIRE_MANAGED_STATE` | `false` | Require preparation and cleaning. |
| `ASSERMETRY_CAPTURE_K8S_BASELINE` | `false` | Capture resources from Kubernetes. |
| `ASSERMETRY_REQUIRE_K8S_BASELINE` | `false` | Demand a full catch. |
| `ASSERMETRY_PROVIDER` | Empty | Non-secret metadata from the supplier. |
| `ASSERMETRY_MODEL` | Empty | Non-secret metadata of the model. |
| `ASSERMETRY_HTTP_TIMEOUT_SECONDS` | Empty | LLM timeout metadata. |

`ASSERMETRY_NEWS`, `ASSERMETRY_NEWS_FILE` and `ASSERMETRY_VALIDATION_MODE` remain available for individual smoke. The orchestrator removes them from each child process so that they do not overwrite the cases versioned.

The artifact directory must be new or empty. The runner never mixes or overwrites evidence of a previous execution.

## Artefactos

```text
assermetry-regression-<run-id>/
├── manifest.json
├── summary.json
├── kubernetes-baseline.json       # opcional
├── synthetic-light-01/
│   ├── report.json
│   └── 01-...06-*.png
└── synthetic-blockchain-01/
    ├── report.json
    └── 01-...06-*.png
```

`manifest.json` records commit, limpio/sucio status of the repository, Node/Chrome versions, non-secret cases and metadata. `summary.json` adds duration, created commands, HTTP checks and bugs.

Reports do not keep passwords, tokens, query strings, prompts, full LLM responses, full news text, command or tabs. Texts are represented by size and SHA-256. Captures do contain visible data of pseudonima identities and should be kept with the same protection as the rest of the evidence of evidence.

## Result and output code

The code is zero only when:

- all cases requested are executed;
- all checks end in `PASS`;
- no terminal states, HTTP errors or unexpected console errors;
- the mandatory hooks end correctly;
- the mandatory baseline is fully captured.

A bug still generates `report.json` and `summary.json` whenever it has been possible to initialize your directories, facilitating the diagnosis without turning the error into a false positive.
