# 📰 TrustNews

> **Automated news verification platform using AI validators, RAG-assisted evidence search, IPFS and optional Ethereum auditability**  
> Post-TFM evolution of the original academic Proof of Concept.

![status](https://img.shields.io/badge/status-post--TFM--prototype-blue)
![python](https://img.shields.io/badge/python-3.10+-blue)
![kubernetes](https://img.shields.io/badge/kubernetes-skaffold-blue)
![blockchain](https://img.shields.io/badge/blockchain-ethereum-lightgrey)
![license](https://img.shields.io/badge/license-academic-lightgrey)

---

## 🔍 What is TrustNews?

**TrustNews** is a prototype platform for automated news verification.

It decomposes news content into **atomic, objective assertions**, optionally enriches them with **RAG-based evidence search**, validates each assertion using **AI-based validators** or dedicated validators with their own knowledge base, and persists the process according to one of two operating modes:

* **LIGHT mode**, designed for centralized systems where blockchain is not required.
* **BLOCKCHAIN mode**, designed for auditable workflows using IPFS and Ethereum smart contracts.

The post-TFM version extends the original academic Proof of Concept with:

* Secure access through an authenticated API Gateway.
* Frontend authentication using OIDC.
* B2B access using OAuth 2.0 Client Credentials.
* Quota management through the Admin API.
* Dynamic validator configuration.
* Evidence-backed RAG validation.
* Preferred-domain evidence search with MongoDB-backed profiles.
* Tavily-backed evidence retrieval with MongoDB cache.
* Kubernetes/Skaffold local and production overlays.
* Optional blockchain-based auditability through IPFS and Ethereum.

The verification pipeline is designed to run automatically from publication to final validation, while keeping the process traceable and auditable end to end.

---

## ✨ Why does this matter?

Most fact-checking solutions are:

* Manual or semi-automated.
* Centralized.
* Difficult to audit end to end.
* Focused on full-text judgement instead of structured assertion validation.

TrustNews explores a different approach:

* ✅ Assertions instead of full-text validation.
* ✅ Multiple automated validators.
* ✅ Evidence-backed RAG validation.
* ✅ Preferred-domain routing for official and trusted sources.
* ✅ Two operating modes: centralized or blockchain-auditable.
* ✅ Full traceability from order creation to final validation.
* ✅ Optional tamper-resistant validation history through IPFS and Ethereum.

---

## 🧠 Core Ideas

### 1. Atomic Assertions

News is decomposed into small, verifiable statements.

Instead of asking an AI model to judge a complete article directly, TrustNews extracts atomic assertions such as:

```text
"The company reported a 15% revenue increase in 2025."
"The event took place in Madrid."
"The minister announced the measure on Monday."
```

Each assertion can be validated independently.

---

### 2. Unattended Validation

AI validators automatically verify assertions without human intervention.

Validators may use:

* Direct LLM validation.
* Online evidence search.
* RAG evidence context.
* Dedicated internal knowledge bases.
* Category-specific validation logic.

---

### 3. Evidence Search

RAG validators can retrieve and cache supporting sources before validating an assertion.

Evidence search can use:

* Search hints generated upstream by `generate-assertions`.
* Keywords extracted from the assertion.
* Temporal context, entities and locations.
* Preferred domains resolved from MongoDB profiles.
* External provider policies for official-source prioritization.

---

### 4. Dual Operating Mode

TrustNews separates the **validation logic** from the **trust and persistence layer**.

This allows the same validation engine to operate in two ways:

| Mode | Trust Model | Persistence | Complexity | Main Use Case |
|---|---|---|---|---|
| `LIGHT` | Centralized | MongoDB / internal backend | Lower | Corporate or internal validation systems |
| `BLOCKCHAIN` | Auditable / distributed | MongoDB + IPFS + Ethereum | Higher | Traceable and tamper-resistant validation workflows |

---

### 5. Traceability

Depending on the selected operating mode, every step can be recorded in:

* MongoDB.
* Kafka events.
* IPFS documents.
* Ethereum smart contracts.

In `LIGHT` mode, traceability is centralized.

In `BLOCKCHAIN` mode, traceability extends to IPFS and Ethereum.

---

## ⚙️ Two Operating Modes

TrustNews is not only a blockchain project.

It is a flexible validation platform that can operate either as a lightweight centralized validation engine or as a blockchain-auditable verification workflow.

---

## 1. LIGHT Mode — Centralized Validation

**LIGHT mode** is designed to operate outside blockchain in centralized systems.

It is intended for environments where:

* The organization already has a centralized trust model.
* Blockchain infrastructure is not available or not required.
* Fast integration is more important than distributed auditability.
* Lower operational complexity is preferred.
* The validation result must be consumed by an internal platform, CMS, editorial system, back-office application or enterprise workflow.

```mermaid
flowchart TD
    A[User / External System] --> B[API Gateway]
    B --> C[news-handler]
    C --> D[generate-assertions]
    C --> E[evidence-search / RAG provider]
    C --> F[validate-assertions]
    C --> G[(MongoDB / internal persistence)]
    D --> C
    E --> C
    F --> C
    G --> H[Final validation result]
    C --> H
```

In LIGHT mode:

* No smart contract registration is required.
* No blockchain events are required.
* No IPFS persistence is mandatory.
* Validation state is managed centrally.
* Evidence and validation results can be stored in MongoDB.
* Traceability is provided by backend persistence, events and logs.
* Deployment and operation are simpler than in blockchain mode.

---

## 2. BLOCKCHAIN Mode — Auditable Validation Workflow

**BLOCKCHAIN mode** is designed for scenarios where integrity, traceability and independent auditability are key requirements.

In this mode, TrustNews registers the publication and validation lifecycle on a private Ethereum network. Documents and validation results are stored in IPFS, while the blockchain stores immutable references to those documents.

```mermaid
flowchart TD
    A[User / External System] --> B[API Gateway]
    B --> C[news-handler]
    C --> D[generate-assertions]
    C --> E[evidence-search / RAG provider]
    C --> F[ipfs-fastapi]
    F --> I[(IPFS)]
    C --> G[news-chain]
    G --> J[TrustNews.sol Smart Contract]
    J --> K[ValidationRequested events]
    K --> L[validate-assertions]
    L --> I
    L --> M[ValidationSubmitted transaction]
    M --> J
    J --> N[ValidationSubmitted events]
    N --> C
    C --> O[Final validation result]
```

In BLOCKCHAIN mode:

* The generated document is stored in IPFS.
* The post is registered in the smart contract.
* Validators are selected according to assertion categories.
* Validation requests are emitted as blockchain events.
* Validators retrieve the assertion and evidence context.
* Validation documents are uploaded to IPFS.
* Validators submit validation results back to the smart contract.
* The complete lifecycle can be audited through MongoDB, IPFS and Ethereum.

---

## 🏗️ Architecture

<img src="./docs/img/Architecture.png" width="70%"/>

**Key traits**:

* Domain-oriented microservices.
* Asynchronous messaging with Kafka.
* Pluggable AI validators.
* Dedicated RAG evidence-search service.
* MongoDB-backed order, quota, validator and evidence data.
* Optional private Ethereum network.
* Optional IPFS document persistence.
* Kubernetes/Skaffold local and production overlays.

### High-Level Architecture

```mermaid
flowchart TD
    A[Frontend / Client] --> B[API Gateway]
    B --> C[news-handler]

    C --> D[generate-assertions]
    C --> E[evidence-search]
    C --> F[validate-assertions]
    C --> G[(MongoDB)]

    D --> C
    E --> G
    F --> G

    C --> H[ipfs-fastapi]
    H --> I[(IPFS)]

    C --> J[news-chain]
    J --> K[TrustNews.sol]
    K --> L[(Ethereum / PoA)]

    B --> M[Admin API]
    B --> N[Keycloak]
```

Depending on the selected operating mode, the workflow can stop at centralized validation or continue through IPFS and blockchain registration.

---

## 🔒 Security

<img src="./docs/img/security.png" width="70%"/>

**Key points**:

* **IAM**: OIDC authentication for frontend users.
* **B2B Access**: OAuth 2.0 Client Credentials via Nginx/Gateway for B2B partners.
* **Gateway**: Token validation and internal ID generation by merging `sub` and `client_id` claims.
* **Proxy**: Secure request forwarding to the orchestrator with identity injection.
* **Quotas**: Real-time balance verification via Admin API with proactive blocking using HTTP `429`.
* **Events**: Post-processing consumption increment and event dispatching through Kafka.
* **Secrets**: Local overlays use ignored `.env` files; production secrets are created outside the repository.
* **Domain governance**: Evidence search can be constrained or guided by preferred-domain policies.

---

## 🧩 Main Components

| Component | Responsibility |
|---|---|
| `gateway` | Authenticated API entrypoint |
| `admin` | Quotas, clients, model recommendations and evidence-search config CRUD |
| `news-handler` | End-to-end orchestration and Kafka event handling |
| `generate-assertions` | AI-based assertion extraction and search hint generation |
| `validate-assertions` / `validate-asertions` | Automated assertion validation workers |
| `evidence-search` | Tavily-backed evidence retrieval with MongoDB cache and preferred-domain routing |
| `news-chain` | Blockchain access layer and event listener |
| `ipfs-fastapi` | Document storage abstraction |
| `mongodb` | Orders, quotas, validator cache, evidence, profiles and config data |
| `mongo-express` | Local MongoDB inspection UI |
| `keycloak` | Identity provider |
| `TrustNews.sol` | Smart contract for immutable system state |
| `web_classic` | User interaction and monitoring |
| `kafka` | Asynchronous event backbone |
| `k3s` / `kind` | Kubernetes runtime for local/cloud deployment |
| `skaffold` | Build and deployment automation |

---

## 🔄 Validation Lifecycle

The validation lifecycle depends on the selected operating mode.

---

### LIGHT Mode Lifecycle

```mermaid
sequenceDiagram
    participant U as User / External System
    participant G as API Gateway
    participant O as news-handler
    participant A as generate-assertions
    participant E as evidence-search
    participant V as validate-assertions
    participant M as MongoDB

    U->>G: Submit news
    G->>G: Validate token and client identity
    G->>O: Forward request
    O->>A: Extract atomic assertions
    A-->>O: Assertions + search hints
    O->>E: Retrieve evidence
    E-->>O: Evidence context
    O->>V: Validate assertions
    V-->>O: TRUE / FALSE / UNKNOWN
    O->>M: Store order, evidence and result
    O-->>U: Final validation result
```

1. A client submits a news item through the Gateway.
2. The Gateway validates the token, computes the internal `client_id`, checks quotas and forwards the request to the orchestrator.
3. The `generate-assertions` service extracts atomic assertions from the news text.
4. If enabled, `evidence-search` retrieves supporting or contradicting evidence.
5. The validation service evaluates each assertion using the configured validator.
6. The orchestrator stores the validation state, evidence summary and final result in MongoDB.
7. The result is returned to the consuming system or made available through the API/frontend.

---

### BLOCKCHAIN Mode Lifecycle

```mermaid
sequenceDiagram
    participant U as User / External System
    participant G as API Gateway
    participant O as news-handler
    participant A as generate-assertions
    participant E as evidence-search
    participant I as IPFS
    participant N as news-chain
    participant S as TrustNews.sol
    participant V as validate-assertions
    participant M as MongoDB

    U->>G: Submit news
    G->>O: Authenticated request
    O->>A: Extract assertions
    A-->>O: Assertions + search hints
    O->>E: Retrieve evidence
    E-->>O: Evidence context
    O->>I: Store document
    I-->>O: CID
    O->>N: Register post
    N->>S: registerNew
    S-->>N: ValidationRequested events
    N-->>V: Validation request
    V->>I: Store validation document
    I-->>V: Validation CID
    V->>S: addValidation
    S-->>N: ValidationSubmitted event
    N-->>O: Validation completed
    O->>M: Update order status
    O-->>U: Final validation result
```

1. A client submits a news item through the Gateway.
2. The `generate-assertions` service extracts atomic assertions and optional search hints.
3. RAG evidence search retrieves supporting evidence according to `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS`.
4. The generated document is stored in IPFS.
5. The `news-chain` service registers the post in the smart contract.
6. The contract assigns validators based on assertion categories and emits validation request events.
7. Validation agents listen for `ValidationRequested` events.
8. Each validator retrieves the original document, locates the assertion and validates it.
9. The validation result is uploaded to IPFS.
10. The validator registers the validation result and IPFS CID in the smart contract.
11. The orchestrator updates MongoDB and marks the order as validated once all expected validators have responded.

---

## 🔎 Evidence Search Configuration

RAG validators call `evidence-search` through the v2 endpoint:

```http
POST /search/evidence
```

The service resolves preferred domains from MongoDB collection:

```text
newsdb.evidence_domain_profiles
```

Normalization configuration is stored in:

```text
newsdb.evidence_normalization_configs
```

Search responses are cached separately in:

```text
newsdb.evidence_search_cache
```

The cache key includes:

* Normalized assertion text.
* The v2 search policy.
* The preferred-domain mode.
* The domain profile version.
* Search backend settings.
* Full-text enrichment settings.

The cache expires with:

```env
EVIDENCE_SEARCH_CACHE_TTL_SECONDS
```

LOCAL domain scoring uses one complete MongoDB document per profile plus independent normalization documents for subcategories, location scopes and source types.

To validate or refresh the versioned JSON seeds:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --dry-run
python scripts/k8s/apis/init-evidence-search-domains.py --refresh --confirm
```

---

## RAG Query Generation

The evidence-search service builds base queries from the assertion payload.

It first tries to use explicit search suggestions generated upstream:

```json
{
  "search_hints": {
    "suggested_queries": [
      "official statistics youth unemployment Spain 2025"
    ],
    "search_keywords": [
      "youth unemployment",
      "Spain",
      "2025"
    ]
  }
}
```

If no suggested query exists, the service builds a compact fallback query from:

* Assertion text.
* Search keywords.
* Temporal context.
* Entities.
* Locations.

This keeps `generate-assertions` as the preferred source of search intent, while allowing evidence search to operate even when no explicit query was generated.

---

## RAG Preferred Domains Strategy

Evidence search is controlled by:

```env
EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS
```

This setting defines how TrustNews handles `preferred_domains` before calling the configured evidence-search provider.

The effective request policy field is:

```text
use_preferred_domains
```

The supported modes are:

```text
NONE
LOCAL
EXT_OFFICIAL_FIRST
EXT_ONLY_OFFICIAL
```

---

### Strategy Summary

| Mode | Uses generated search suggestions | MongoDB profile enrichment | Provider domain behavior | General fallback | Typical use case |
|---|---:|---:|---|---:|---|
| `NONE` | ✅ | ❌ | No preferred-domain enrichment. Search uses generated suggestions or fallback query. | Depends on policy | Generic evidence search |
| `LOCAL` | ✅ | ✅ | Resolves local preferred domains and passes them as `include_domains`. | When local routing needs fallback | Client/org-specific trusted source routing |
| `EXT_OFFICIAL_FIRST` | ✅ | ❌ | Sends `external_source_policy=official_first` to the provider. | Can be enabled by policy | Prefer official sources without losing recall |
| `EXT_ONLY_OFFICIAL` | ✅ | ❌ | Sends `external_source_policy=only_official` to the provider. | ❌ Disabled by code | Official-source-only validation |

---

### `NONE`

`NONE` disables preferred-domain enrichment.

In this mode:

* No MongoDB domain profile is loaded.
* No local preferred domains are resolved.
* No official-source external provider policy is applied.
* Evidence search uses the query suggested by `generate-assertions`.
* If no suggested query exists, the service builds a fallback query from the assertion text and metadata.

```mermaid
flowchart TD
    A[generate-assertions] --> B[Suggested query / fallback query]
    B --> C[Search provider]
    C --> D[Evidence results]
```

This mode is useful for generic evidence search where no domain policy should be applied.

---

### `LOCAL`

`LOCAL` enables MongoDB-backed domain routing.

In this mode:

* The service loads a domain profile from `newsdb.evidence_domain_profiles`.
* The service loads normalization configs from `newsdb.evidence_normalization_configs`.
* The assertion is normalized.
* Contextual preferred domains are resolved from the local profile.
* Selected domains are passed to the provider as `include_domains`.
* Local domain scoring is enabled.
* The effective policy is marked as `local_scored_domains`.

```mermaid
flowchart TD
    A[generate-assertions] --> B[Suggested query / fallback query]
    B --> C[MongoDB profile lookup]
    C --> D[Domain normalization and scoring]
    D --> E[Selected include_domains]
    E --> F[Search provider]
    F --> G[Evidence results]
```

This mode is useful for:

* Client-specific trusted source profiles.
* Organization-specific source policies.
* Category-based domain routing.
* Enterprise validation environments.
* Centralized LIGHT mode deployments.

---

### `EXT_OFFICIAL_FIRST`

`EXT_OFFICIAL_FIRST` does not use local MongoDB domain scoring.

Instead, the service sends the request to the external search provider with:

```text
external_source_policy=official_first
```

In this mode:

* The generated search query is still used.
* No local domain profile is loaded.
* No `include_domains` list is produced from MongoDB.
* The provider is asked to prioritize official sources when supported.
* Non-official sources may still appear if relevant or if the provider treats the policy as a ranking hint.

```mermaid
flowchart TD
    A[generate-assertions] --> B[Suggested query / fallback query]
    B --> C[external_source_policy = official_first]
    C --> D[External search provider]
    D --> E[Ranked evidence results]
```

This mode is useful when official sources should be preferred but broader recall is still valuable.

---

### `EXT_ONLY_OFFICIAL`

`EXT_ONLY_OFFICIAL` is the strictest external preferred-domain mode.

The service sends the request to the external search provider with:

```text
external_source_policy=only_official
```

In this mode:

* The generated search query is still used.
* No local MongoDB domain profile is loaded.
* No local `include_domains` list is generated.
* The provider is asked to restrict results to official sources when supported.
* General fallback searches are not added by the code.

```mermaid
flowchart TD
    A[generate-assertions] --> B[Suggested query / fallback query]
    B --> C[external_source_policy = only_official]
    C --> D[External search provider]
    D --> E[Official-source evidence results]
```

This mode is useful for:

* High-trust validation.
* Regulatory or institutional assertions.
* Official-source-only validation.
* Cases where source authority is more important than broad recall.

---

## Evidence Search Request Planning

The evidence-search service builds provider-ready search requests.

Each search request may include:

```json
{
  "query": "official statistics youth unemployment Spain 2025",
  "include_domains": ["ine.es", "eurostat.ec.europa.eu"],
  "mode": "preferred_domains",
  "external_source_policy": "none"
}
```

Or, for external official-source modes:

```json
{
  "query": "official statistics youth unemployment Spain 2025",
  "include_domains": null,
  "mode": "external_official_first",
  "external_source_policy": "official_first"
}
```

```json
{
  "query": "official statistics youth unemployment Spain 2025",
  "include_domains": null,
  "mode": "external_only_official",
  "external_source_policy": "only_official"
}
```

Provider responses are merged, ordered and deduplicated by URL.

---

## Evidence Output

A normalized evidence item can include:

```json
{
  "source_id": "source-1",
  "title": "Source title",
  "url": "https://example.org/source",
  "domain": "example.org",
  "source_type": "official",
  "snippet": "Relevant excerpt or summary",
  "rank": 1,
  "trust_score": 0.87,
  "retrieved_at": "2026-01-01T12:00:00Z",
  "why_selected": "Matched contextual search policy",
  "matched_profiles": ["default"]
}
```

When full-text enrichment is enabled, evidence may also include selected contexts:

```json
{
  "contexts": [
    {
      "context_id": "source-1-context-1",
      "selected_chunk_id": "source-1-chunk-3",
      "included_chunk_ids": [
        "source-1-chunk-2",
        "source-1-chunk-3",
        "source-1-chunk-4"
      ],
      "text": "Selected context window used by the validator.",
      "score": 0.91,
      "origin": "full_text",
      "char_length": 850
    }
  ]
}
```

If full-text retrieval is disabled or fails, the service falls back to the provider snippet.

---

## Search Providers

Evidence search is provider-backed.

Current configuration supports a generic provider abstraction through:

```env
SEARCH_PROVIDER
API_KEY_PROVIDER
```

The postTFM README and local overlays refer to Tavily-backed evidence retrieval.

Provider-specific behavior may affect:

* Domain filtering.
* Official-source policies.
* Ranking.
* Raw content availability.
* Highlight or full-text support.
* Maximum result count.

The exact behavior of `EXT_OFFICIAL_FIRST` and `EXT_ONLY_OFFICIAL` depends on the selected provider.

Some providers support hard domain filters, while others treat domain or official-source policies as ranking hints.

---

## AI Providers and Validators

Validators are configurable and can use different AI providers or models.

Supported provider abstraction may include:

* Mistral.
* Gemini.
* OpenRouter.
* Grok/xAI.
* Dedicated validator-specific knowledge bases.

Each validator can be associated with one or more validation categories.

Validator configuration can include:

* Provider.
* Model.
* API endpoint.
* Validator categories.
* Evidence-search behavior.
* Blockchain account, when operating in `BLOCKCHAIN` mode.

When categories change in `BLOCKCHAIN` mode, the validator may need to be re-registered on-chain.

---

## 💳 Quota Management

The post-TFM version introduces client-level quotas managed through the Admin API.

Quota-controlled resources may include, depending on deployment configuration:

| Resource | Meaning |
|---|---|
| `news_generation` | Number of news/assertion generation operations |
| `evidence_search` | Number of evidence-search operations |
| `validation` | Number of centralized validation operations |
| `blockchain_validation` | Number of blockchain-backed validation operations |

Quota checks are applied before heavy operations.

If a quota is exceeded:

* The Gateway or backend service may return HTTP `429`.
* The asynchronous workflow may be stopped before IPFS/blockchain processing.
* The order may be marked with a quota-related status.
* Consumption can be updated during the workflow to reflect real usage.

---

## 🚀 Quick Start

### Prerequisites

* Docker >= 24.
* Kubernetes local cluster.
* Kind, as used in the project documentation.
* Skaffold v4.
* kubectl.
* 8GB RAM recommended.

### Clone

```bash
git clone https://github.com/<your-user>/trustnews.git
cd trustnews
```

---

## Local Environment Files

Create local `.env` files from the examples before running Skaffold.

Real secrets must not be committed.

Important local files:

```text
k8s/infra/mongodb/overlays/local/mongodb.env
k8s/infra/mongo-express/overlays/local/mongo-express.env
k8s/infra/keycloak/overlays/local/keycloak.env
k8s/apis/generate-asertions/overlays/local/generate-asertions.env
k8s/apis/mongodb-app/overlays/local/mongodb-app.env
k8s/apis/news-chain/overlays/local/news-chain.env
k8s/apis/evidence-search/overlays/local/tavily.env
k8s/apis/validate-asertions/overlays/local/worker-*/worker-*.env
```

MongoDB local examples:

```bash
cp k8s/infra/mongodb/overlays/local/mongodb.env.example \
  k8s/infra/mongodb/overlays/local/mongodb.env

cp k8s/apis/mongodb-app/overlays/local/mongodb-app.env.example \
  k8s/apis/mongodb-app/overlays/local/mongodb-app.env

cp k8s/infra/mongo-express/overlays/local/mongo-express.env.example \
  k8s/infra/mongo-express/overlays/local/mongo-express.env
```

`mongodb.env` creates the MongoDB root/admin user and the application user `app_trust_user`.

Runtime services use only `mongodb-app-secret`, whose `MONGO_URI` must authenticate `app_trust_user` against `newsdb` with `readWrite` permissions.

Mongo Express keeps using the admin/root secret for database inspection.

Production overlays expect sensitive secrets to be created outside the repository, usually with:

```bash
kubectl create secret generic <secret-name> --from-env-file=<file>.env -n <namespace>
```

---

## Local Kubernetes Run

The repository is aligned around Skaffold profiles:

```bash
skaffold dev -p setup
skaffold dev -p blockchain
skaffold dev -p infra
skaffold dev -p apis-frontend
```

Main local URLs exposed by Skaffold:

| Service | URL |
|---|---|
| Frontend | https://localhost:7443 |
| Keycloak admin console | https://localhost:7443/auth/admin/master/console/ |
| Admin API | http://localhost:8400/docs |
| Gateway | http://localhost:8500/docs |
| Evidence Search | http://localhost:8074/docs |
| Mongo Express | http://localhost:8081 |
| Kafdrop | http://localhost:9000 |
| Grafana | http://localhost:3000 |

> ⏳ First startup may take a few minutes while Ethereum, Kafka, MongoDB, IPFS and Keycloak stabilize.

For detailed commands, see:

* `docs/k8s/skaffold.md` for the current Kubernetes/Skaffold workflow.
* `docs/k8s/kind.md` for Kind setup notes.
* `docs/docker/installation_blockchain.md` for private Geth PoA setup notes.
* `docs/blockchain/scripts_blockchain.md` for smart contract deploy/test scripts.

---

## Configuration

Typical configuration areas:

* Operating mode: `LIGHT` or `BLOCKCHAIN`.
* Evidence-search preferred-domain mode.
* Kafka connection and security.
* MongoDB connection.
* IPFS API URL.
* Blockchain RPC URL.
* Smart contract address.
* Validator private keys.
* AI provider, model and API key.
* Search provider and API key.
* Gateway/OIDC configuration.
* Admin service URL.
* Quota limits.
* Kubernetes/Skaffold deployment profiles.

Example configuration:

```env
APP_MODE=LIGHT
# APP_MODE=BLOCKCHAIN

VALIDATOR_TYPE=3
EVIDENCE_SEARCH_URL=http://evidence-search.apis.svc.cluster.local:8074
EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=LOCAL
# EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=NONE
# EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=EXT_OFFICIAL_FIRST
# EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=EXT_ONLY_OFFICIAL
EVIDENCE_SEARCH_PREFERRED_PROFILE_ID=default

EVIDENCE_SEARCH_CACHE_TTL_SECONDS=86400

SEARCH_PROVIDER=tavily
API_KEY_PROVIDER=...

EVIDENCE_FETCH_FULL_TEXT=false
EVIDENCE_MAX_CONTEXTS_PER_SOURCE=2
EVIDENCE_MAX_CONTEXTS_TOTAL=8
EVIDENCE_CHUNK_SIZE_CHARS=1200
EVIDENCE_CHUNK_OVERLAP_CHARS=200
EVIDENCE_CONTEXT_WINDOW_BEFORE=1
EVIDENCE_CONTEXT_WINDOW_AFTER=1

AI_PROVIDER=openrouter
MODEL=...
API_KEY=...

MONGO_DBNAME=newsdb
MONGO_URI=mongodb://app_trust_user:***@mongodb:27017/newsdb

KAFKA_BROKER=kafka:9092

ADMIN_URL=http://admin:8000

IPFS_FASTAPI_URL=http://ipfs-fastapi:8060

RPC_URL=http://geth-node:8545
CONTRACT_ADDRESS=...
PRIVATE_KEY=...
ACCOUNT_ADDRESS=...
```

### Validator behavior variables

`VALIDATOR_TYPE` is the source of truth for the validator behavior. `USE_EVIDENCE_SEARCH` and `ONLINE_SEARCH_ENABLED` are no longer configured as environment variables; their effective values are derived from the validator type and may still appear in API/config responses for backward compatibility.

| Variable | Supported values | Activates / controls | Incompatibilities and notes |
|---|---|---|---|
| `VALIDATOR_TYPE` | `1`, `2`, `3`, `4`, `5` | Selects the validation algorithm. | Only `1`, `2` and `3` run automatic validation in `validate-asertions`. |
| `VALIDATOR_TYPE=1` | `LLM_MEMORY_VALIDATION` | LLM memory validation with `LLM_MEMORY_VALIDATION_PROMPT`. | Does not call `evidence-search` and does not enable online model mode. |
| `VALIDATOR_TYPE=2` | `LLM_SEARCH_VALIDATION` | LLM online-search validation with `LLM_SEARCH_VALIDATION_PROMPT`. | In OpenRouter, the worker sends the model as `MODEL:online` automatically. |
| `VALIDATOR_TYPE=3` | `RAG_EVIDENCE_VALIDATION` | RAG validation: always calls `EVIDENCE_SEARCH_URL` and injects returned evidences into `RAG_EVIDENCE_VALIDATION_PROMPT`. | Requires `evidence-search` to be reachable. Preferred-domain variables only matter for this type. |
| `VALIDATOR_TYPE=4` | `DETERMINISTIC_VALIDATION` | Registers/configures a deterministic validator. | No automatic listener/LLM validation is implemented in this worker. |
| `VALIDATOR_TYPE=5` | `HUMAN` | Registers/configures a human/manual validator. | No automatic listener/LLM validation is implemented in this worker. |
| `EVIDENCE_SEARCH_URL` | URL | Evidence-search service endpoint. | Used only by `VALIDATOR_TYPE=3`. |
| `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS` | `NONE`, `LOCAL`, `EXT_OFFICIAL_FIRST`, `EXT_ONLY_OFFICIAL` | Evidence source strategy sent to `evidence-search`. | Used only by `VALIDATOR_TYPE=3`; invalid values fail validation. |
| `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=NONE` | `NONE` | Generic evidence search without local preferred-domain scoring. | Does not use `EVIDENCE_SEARCH_PREFERRED_PROFILE_ID`. |
| `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=LOCAL` | `LOCAL` | Loads MongoDB domain profiles and scores preferred domains locally. | Only valid for RAG/type `3`; uses `EVIDENCE_SEARCH_PREFERRED_PROFILE_ID`. |
| `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=EXT_OFFICIAL_FIRST` | `EXT_OFFICIAL_FIRST` | Asks the external provider to prioritize official sources. | Does not use local profile scoring. |
| `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=EXT_ONLY_OFFICIAL` | `EXT_ONLY_OFFICIAL` | Asks the external provider to restrict results to official sources when supported. | General fallback search is disabled by code for this mode. |
| `EVIDENCE_SEARCH_PREFERRED_PROFILE_ID` | String, default `default` | Selects the local MongoDB domain profile. | Used only with `EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=LOCAL`. |
| `EVIDENCE_SEARCH_MAX_DOMAINS` | Integer, default `8` | Max preferred domains sent in the evidence policy. | Used only by RAG/type `3`. |
| `EVIDENCE_SEARCH_MAX_SOURCES` | Integer, default `5` | Max evidence results requested by the validator. | Used only by RAG/type `3`. |
| `EVIDENCE_SEARCH_MAX_QUERIES_PER_DOMAIN` | Integer, default `2` | Query fan-out limit. | Used only by RAG/type `3`. |
| `AI_PROVIDER` | `mistral`, `gemini`, `openrouter`, `grok` | LLM provider for automatic validators. | Automatic types reject unknown providers and `none`. |
| `MODEL` | Provider-specific model id | LLM model. | With `VALIDATOR_TYPE=2` and OpenRouter, `:online` is appended at request time unless already present. |

Real secrets must never be committed to the repository.

---

## 📂 Project Structure

```text
.
├── api/
│   ├── admin/                  quotas, clients and evidence config
│   ├── common/                 shared models and utilities
│   ├── evidence-search/        RAG evidence search and cache
│   ├── gateway/                API gateway
│   ├── generate-asertions/     assertion generation service
│   ├── ipfs/                   IPFS API abstraction
│   ├── news-chain/             smart contract API abstraction
│   ├── news-handler/           orchestration service
│   ├── tests/                  unit tests
│   └── validate-asertions/     validator workers
├── blockchain/                 Geth PoA network manifests/config
├── docs/                       documentation
├── k8s/                        Kubernetes manifests and Kustomize overlays
├── scripts/                    helper scripts
├── smart-contracts/            Solidity contracts and Hardhat scripts
├── web_classic/                frontend
└── README.md
```

---

## ✅ Integrity Checks

The system includes consistency checks across:

* MongoDB orders.
* MongoDB evidence profiles.
* MongoDB evidence cache.
* IPFS documents.
* Ethereum posts, assertions and validations.
* Kafka validation events.

This helps keep the validation process auditable and tamper-resistant.

In `LIGHT` mode, checks focus on MongoDB, evidence records, event logs and internal validation state.

In `BLOCKCHAIN` mode, checks also cover IPFS CIDs, Ethereum posts, validation documents and blockchain events.

---

## 🧪 Testing

Relevant test areas include:

* Assertion generation.
* Gateway-authenticated flows.
* Quota setup and consumption.
* Evidence search using `NONE`.
* Evidence search using `LOCAL`.
* Evidence search using `EXT_OFFICIAL_FIRST`.
* Evidence search using `EXT_ONLY_OFFICIAL`.
* MongoDB profile loading and normalization.
* Evidence cache behavior.
* Centralized validation in `LIGHT` mode.
* Blockchain registration in `BLOCKCHAIN` mode.
* Validation event processing.
* IPFS document retrieval.
* End-to-end validation workflow.

---

## 🛣️ Roadmap

* [x] Secure and authenticate platform.
* [x] Integrate UI with IDP and custom chains for user.
* [x] Assertion-based news verification.
* [x] AI-based validation engine.
* [x] Evidence-backed RAG validation.
* [x] Preferred-domain evidence search.
* [x] MongoDB-backed evidence domain profiles.
* [x] Evidence search cache.
* [x] LIGHT mode for centralized validation workflows.
* [x] BLOCKCHAIN mode for auditable validation workflows.
* [x] IPFS document storage in blockchain mode.
* [x] Ethereum smart contract registration.
* [x] Migrate validation requests and responses from Kafka-only flow to blockchain events.
* [x] Gateway authentication.
* [x] Admin and quota management.
* [x] Validator configuration API.
* [x] Kubernetes/Skaffold deployment workflow.
* [x] GitHub Actions integration.
* [x] GitLab mirror workflow.
* [ ] Improve evidence ranking and deduplication.
* [ ] Improve provider-specific official-source filtering behavior.
* [ ] Validator reputation system.
* [ ] Full production hardening.
* [ ] Performance and cost analysis.
* [ ] API control.
* [ ] Support Hyperledger Besu or Fabric.

---

## ⚠️ Current Limitations

TrustNews is still a research/prototype platform.

Current limitations include:

* AI validators depend on external LLM providers.
* Evidence quality depends on the selected search provider.
* External official-source modes depend on provider support.
* Some providers may treat official-source policies as ranking hints rather than hard filters.
* Validator reputation is planned but not completed.
* Production hardening is still pending.
* Some operational flows are optimized for controlled academic/prototype environments.
* `BLOCKCHAIN` mode introduces higher operational complexity than `LIGHT` mode.

---

## 🤝 Contributing

This is an academic and research-oriented prototype, but contributions are welcome.

Recommended workflow:

1. Fork the repository.
2. Create a feature branch.
3. Implement and test the change.
4. Update documentation when architecture, configuration or deployment changes.
5. Open a pull request.
6. Merge after review and validation.

---

## 📄 License

Academic / research use only.

---

## 👤 Author

Developed as a **Master Thesis – Proof of Concept**, later extended in the post-TFM phase.

---

## 📌 Summary

TrustNews is not only a blockchain-based verification system.

It is a flexible automated validation platform that can operate in two ways:

* **LIGHT mode**, for centralized systems that need fast and simple AI-based validation.
* **BLOCKCHAIN mode**, for systems that require stronger auditability, integrity and traceability.

It also supports RAG-assisted evidence search when `VALIDATOR_TYPE=3`. Source strategy is controlled by:

```env
EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS
```

Supported preferred-domain modes:

* **`NONE`**: use only the search suggested by `generate-assertions` or the fallback assertion query.
* **`LOCAL`**: enrich preferred domains using MongoDB-stored profiles and pass them as `include_domains`.
* **`EXT_OFFICIAL_FIRST`**: ask the provider to prioritize official sources.
* **`EXT_ONLY_OFFICIAL`**: ask the provider to restrict results to official sources when supported.

This makes TrustNews suitable both for lightweight integration into existing centralized platforms and for advanced scenarios where validation results must be independently auditable.
