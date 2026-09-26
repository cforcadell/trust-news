# Test strategy and catalog

This document orders currently checks from those that travel through more layers of the system to the most local ones. A test above provides more integration coverage, but is usually slow, more variable and dependent on the environment. Local tests better isolate a cause and must be executed before regression is deployed.

## Organization

All test sources, their resources and outputs live under `tests/`:

```text
tests/
├── api/                         # suite Python y requisitos
├── frontend/
│   ├── unit/                    # node:test
│   └── e2e/
│       ├── resources/           # casos e identidades
│       └── artifacts/           # informes y capturas de E2E
├── llm-benchmark/
│   ├── resources/               # caso y perfiles versionados
│   └── artifacts/               # SQLite, planes e informes
├── contracts/
│   ├── mocha/                   # pruebas cargadas por Hardhat
│   └── manual/                  # comprobaciones ejecutables con hardhat run
├── operations/                  # sondas operativas de prueba
├── resources/historical-stats/  # muestras históricas de métricas
└── artifacts/                   # caché de pytest y salidas de métricas
```

Artifact directories are ignored in Git. Each executor uses its default subfolder; `ASSERMETRY_ARTIFACTS_DIR` allows explicitly replacing it for the E2E.

## Test matrix

| Nivel | Suite | Current scope | Dependencias | Main entrance | Implementation |
| --- | --- | --- | --- | --- | --- |
| 1 | GUI LIGHT + BLOCKCHAIN regression | Chrome, Keycloak, frontend, Gateway, APIs, Kafka, MongoDB, validators and, in BLOCKCHAIN, IPFS/Ethereum | Full local/Kind deployment, Chrome and two identities | Multi-affirming synthetic news about Sweden, Germany, Italy and Spain | `node tests/frontend/e2e/run-regression.js` |
| 2 | Order backend flow | News Handler and Units deployed to `VALIDATED` | Keycloak, fees and full backend | Synthetic news of the population of Catalonia | `PYTHONPATH=api pytest tests/api/test_news-handler.py` |
| 3 | HTTP integrations per service | Real generation APIs, quotas, IPFS, news-chain and validator | Selected services deployed | Specific synthetic Payloads | See “Integrations HTTP” |
| 4 | Integration in progress | Several Python layers connected by ASGI, repositories or simulated dependencies | No deployment; Python units | Fixtures controladas | `pytest` local suite |
| 5 | Contracts and units backend | Models, routing, evidence, consensus, security, LLM, URLs and logging | Python process only | Fixtures and simulated suppliers | `pytest` local suite |
| 6 | Unidades frontend | Presentation and navigation functions extracted from `app.js` | Node.js | Objetos JavaScript controlados | `node --test tests/frontend/unit/*.test.js` |
| 7 | Static consistency | Backend catalog versus Blockchain seeds and shared layer usage | Repository only | Archivos versionados | Included in the local suite |
| Operation | Loki Persistence | Ingest, consult and persist after restarting Loki | Kubernetes local configurado | Sonda HTTP identificable | `tests/operations/verify-loki-persistence.sh --execute` |

The E2E suite checks the route and operational invariants. It does not use a stable factual oracle: getting to `VALIDATED` means that the prosecution is over, not that the verdict of the news is correct.

## Benchmark historical configurations OpenRouter

The [llm-benchmark.md](llm-benchmark.md) batch compares complete generation, routing and validation profiles using a synthetic news with factual oracle. It runs exclusively in LIGHT mode, retains JSON results and inexual quality, cost and duration in SQLite. It is validated locally with:

    python3 tests/llm-benchmark/llm-benchmark.py validate-profiles

Unlike the E2E regression, this batch does score the extraction quality and verdicts. It requires an exclusive environment because it temporarily changes the effective LLM configuration and restores it when finished.

## 1. E2E regression from GUI

[`tests/frontend/e2e/run-regression.js`](../../tests/frontend/e2e/run-regression.js) executes two scenarios sequentially through Chrome DevTools Protocol:

- [`light.json`](../../tests/frontend/e2e/resources/cases/light.json): Requires a LIGHT command
terminal, assertions, validations and the disabled IPFS tab.
- [`blockchain.json`](../../tests/frontend/e2e/resources/cases/blockchain.json): requires a
BLOCKCHAIN terminal command, `cid`, `post_id`, `tx_hash` and IPFS tab.

The two scenarios currently use the same synthetic multi-affirmation text ([`light-news.txt`](../../tests/frontend/e2e/resources/cases/light-news.txt) and [`blockchain-news.txt`](../../tests/frontend/e2e/resources/cases/blockchain-news.txt)). It is a news story with four independent statements, concerning vaccination in Sweden, energy transition in Germany, tourism access in Italy and teaching foreign languages in Spain. These files are the source of truth of the entry; the currently documented text is:

```text
En 2025, Suecia reforzó sus programas públicos de vacunación infantil tras una
recomendación de su autoridad sanitaria. Alemania mantuvo su compromiso de
reducir las emisiones industriales mediante nuevas medidas de transición
energética. Italia prohibió por completo el acceso de turistas a todos sus
centros históricos para proteger el patrimonio cultural. España eliminó la
enseñanza obligatoria de lenguas extranjeras en la educación secundaria.
```

The E2E does not set the number of assertions extracted or the verdict of each: both depend on the components deployed. It only requires the minimum and output metadata defined by each case (`LIGHT` or `BLOCKCHAIN`).

The runner checks login, command creation and tracking, terminal status, response structure, tabs, HTTP/consola errors and desktop and mobile views. Preparation, cleaning, identities, variables and artifacts are documented in [`tests/frontend/e2e/README.md`](../../tests/frontend/e2e/README.md).

Validate only case definitions, without opening Chrome:

```bash
node tests/frontend/e2e/run-regression.js --validate
```

Run the E2E, once the credentials described in your README are configured:

```bash
node tests/frontend/e2e/run-regression.js
```

[`ui-smoke-test.js`](../../tests/frontend/e2e/ui-smoke-test.js) can also run a single case. Without `ASSERMETRY_CASE_FILE`, use all [`docs/fake_news/news.txt`](../fake_news/news.txt); that mode is exploratory and does not replace the regression versioned.

## 2. E2E backend flow

[`test_news-handler.py`](../../tests/api/test_news-handler.py) calls the deployed News Handler, creations or reset quotes, published news and want the order until `VALIDATED`. As it does not send `validation_mode`, it uses the default `BLOCKCHAIN` value of the current contract.

Entrada:

```text
Catalunya tiene una población de más de 7 millones de habitantes de los que
2 millones son niños en edad escolar.
```

Requires Keycloak, Admin, News Handler, Kafka, generation, validators, MongoDB, IPFS and Blockchain available. It has a short timeout and shares the `order_id` between functions, so it must be executed as a complete file and in order:

```bash
PYTHONPATH=api pytest tests/api/test_news-handler.py -q
```

## 3. HTTP integrations with deployed services

These tests carry out real traffic. They must not be mixed with the local suite or run against production.

| Fichero | Services | What does it check? | Entrada |
| --- | --- | --- | --- |
| `test_extraer_integration.py` | Keycloak, Admin and Generation Assertions | Quotas, `/extraer`, generation and errors 429/cliente missing | Text of population and area of Catalonia |
| `test_quotas.py` | Keycloak, Admin and Gateway | Publication within quota and rejection when exhausted | Text of the population of Catalonia |
| `test_ipfs_integration.py` | IPFS FastAPI e IPFS | Upgrading, recovery by CID and invalid CID | JSON `Documento de prueba` |
| `test_news-chain_integration.py` | news-chain and Ethereum | Publication/direct consultation with synthetic multi-hashes | He doesn't use news; I used test hashes. |
| `test_validator_api.py` | validation-assertions and, by type, LLM/Blockchain | `/verificar` and validator log | `El sol sale por el este` |

Individual execution:

```bash
PYTHONPATH=api pytest tests/api/test_extraer_integration.py -q
PYTHONPATH=api pytest tests/api/test_quotas.py -q
PYTHONPATH=api pytest tests/api/test_ipfs_integration.py -q
PYTHONPATH=api pytest tests/api/test_news-chain_integration.py -q
PYTHONPATH=api pytest tests/api/test_validator_api.py -q
```

`test_extraer_integration.py`, `test_ipfs_integration.py`, `test_news-chain_integration.py` and `test_validator_api.py` carry the `integration` marker. `test_news-handler.py` and `test_quotas.py` are also external integrations, then they are currently not marked. Therefore, `pytest -m "not integration"` is not enough to obtain an isolated suite.

Some historical `test_news-chain_integration.py` checks accept HTTP 500 when the string is unavailable. They are compatibility probes, not an E2E accreditation or a strong health criterion.

## 4. Local integration in progress

These tests connect real components in the same process and replace the external limits with double controlled:

- `test_validator_validation_isolation.py`: Gateway → News Handler via
transport ASGI, with simulated Mongo collections; checks insulation by owner.
- `test_news_handler_document_shape.py`: canonical document, LIGHT flow and
persistence of frozen weights.
- `test_validator_source_orchestration.py`: validation decisions between
Source Router, Evidence Search and external strategies.
- `test_source_router.py`: repository, simulated discovery, sorting,
eligibility, profiles, cache, degradation and ranking.
- `test_evidence_search_units.py`: search endpoint with simulated provider,
strategies, metadata, cache and filter from official sources.

These tests do not credit network, DNS, credentials, Kafka, MongoDB, real search engines or LLM.

## 5. Local backend testing

The rest of `tests/api` is distributed as follows:

| Area | Ficheros |
| --- | --- |
| LLM and extraction | `test_common_llm.py`, `test_llm_json.py`, `test_generate_assertions_units.py` |
| Evidence | `test_evidence_grounding.py`, `test_evidence_urls.py`, `test_common_search.py` |
| Protocol and models | `test_protocol_v2_models.py`, `test_validation_mode_models.py`, `test_news_handler_document_shape.py` |
| Routing and orchestration | `test_source_router.py`, `test_evidence_search_units.py`, `test_validator_source_orchestration.py` |
| Consensus and Validators | `test_validation_scoring.py`, `test_validator_types_and_scores.py` |
| Safety and isolation | `test_gateway_jwt_claims.py`, `test_gateway_security.py`, `test_validator_validation_isolation.py` |
| Operation and consistency | `test_single_line_logging.py`, `test_category_catalog_sync.py` |

From the root of the repository, this selection excludes all files that make calls to deployed services:

```bash
PYTHONPATH=api pytest tests/api -q \
  --ignore=tests/api/test_extraer_integration.py \
  --ignore=tests/api/test_ipfs_integration.py \
  --ignore=tests/api/test_news-chain_integration.py \
  --ignore=tests/api/test_validator_api.py \
  --ignore=tests/api/test_news-handler.py \
  --ignore=tests/api/test_quotas.py
```

`tests/api/requirements.txt` dependencies cover both pytest and Kafka, but the collection imports code from various services. The testing environment should also include the dependencies of the affected services. Simply running `pytest tests/api` also implies having the previous external integrations.

## 6. Unitary frontend tests

`node:test` tests do not open browsers or call APIs:

| Fichero | Responsabilidad |
| --- | --- |
| `assertion-dedup.test.js` | Deduplication of assertions in projection IU |
| `assertion-status.test.js` | Visual status of TRUE/FALSE/UNKNOWN |
| `consensus-ui.test.js` | Messages of consensus, majority and non-conclusion in ES/EN |
| `evidence-links.test.js` | Secure links and separation between recuperada/usada/declarada evidence |
| `model-opinion.test.js` | Presentation and escape of unverified documentary opinions |
| `pending-navigation.test.js` | Pending States, Polling and Conservation of Navigation |

Implementation:

```bash
node --test tests/frontend/unit/*.test.js
```

## 7. Smart contracts and operational checks

`npx hardhat compile`, desde `smart-contracts`, comprueba que
`TrustNews.sol` compila. No existe actualmente una suite funcional vigente del
contrato TrustNews. `tests/contracts/mocha/Token.js` es el ejemplo inicial de
Hardhat y referencia un contrato `Token` que ya no existe; no debe usarse como
prueba del sistema ni incluirse en una regresión.

The persistence of Loki has a separate operating probe:

```bash
tests/operations/verify-loki-persistence.sh --execute
```

The probe generates a request, confirms its ingestion, restarts Loki and verifies that the event remains. Restart is deliberate and the script requires `--execute`; it is not part of the usual local suite.

## Orden recomendado

For a normal modification:

1. Run frontend drives if you touch `web_classic`.
2. Run the local backend suite excluding external integrations.
3. Run HTTP integrations of affected services.
4. Validate E2E definitions with `run-regression.js --validate`.
5. Run the GUI LIGHT + BLOCKCHAIN regression on deployment.
6. Use operating probes only when the corresponding infrastructure changes.

A result should always indicate which level was executed. “Green Tests” without the suite and the environment does not distinguish local units from an E2E validation.
