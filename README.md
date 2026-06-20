# 📰 TrustNews

> **Automated news verification platform using AI validators, RAG-assisted evidence search and optional blockchain auditability.**  
> Post-TFM evolution of an academic Proof of Concept.

![status](https://img.shields.io/badge/status-post--TFM--prototype-blue)
![python](https://img.shields.io/badge/python-3.10+-blue)
![kubernetes](https://img.shields.io/badge/kubernetes-skaffold-blue)
![blockchain](https://img.shields.io/badge/blockchain-ethereum-lightgrey)
![license](https://img.shields.io/badge/license-academic-lightgrey)

---

## 🔍 Overview

**TrustNews** is a prototype platform for automated news verification.

It decomposes news into **atomic assertions**, enriches them with optional **RAG-based evidence search**, validates each assertion with **AI-based validators**, and provides traceability through centralized persistence or blockchain-based auditability.

TrustNews can operate in two modes:

* **LIGHT mode**: centralized validation without blockchain.
* **BLOCKCHAIN mode**: auditable validation using IPFS and Ethereum smart contracts.

The project was originally developed as a Master Thesis Proof of Concept and later extended in the post-TFM phase.

---

## ✨ Key Features

* Atomic assertion extraction from news content.
* AI-based unattended validation.
* RAG-assisted evidence search.
* Preferred-domain search strategies.
* MongoDB-backed evidence profiles and cache.
* Secure API Gateway.
* OIDC frontend authentication.
* OAuth 2.0 Client Credentials for B2B access.
* Client quotas managed through Admin API.
* Kafka-based asynchronous processing.
* Optional IPFS persistence.
* Optional Ethereum smart contract auditability.
* Kubernetes/Skaffold deployment workflow.

---

## ⚙️ Operating Modes

TrustNews separates the **validation engine** from the **trust and persistence layer**.

| Mode | Description | Main Use Case |
|---|---|---|
| `LIGHT` | Centralized validation using backend services and MongoDB persistence | Internal platforms, CMS integrations, corporate systems |
| `BLOCKCHAIN` | Auditable validation using IPFS, Ethereum and blockchain events | Traceable, tamper-resistant validation workflows |

---

### LIGHT Mode

`LIGHT` mode is designed for centralized systems where blockchain is not required.

```mermaid
flowchart TD
    A[User / External System] --> B[API Gateway]
    B --> C[news-handler]
    C --> D[generate-assertions]
    C --> E[evidence-search]
    C --> F[validate-assertions]
    C --> G[(MongoDB / internal persistence)]
    F --> H[Final validation result]
    G --> H
```

In this mode:

* No smart contract is required.
* No blockchain events are required.
* IPFS persistence is optional.
* Validation state is stored centrally.
* Deployment and operation are simpler.

---

### BLOCKCHAIN Mode

`BLOCKCHAIN` mode is designed for scenarios requiring stronger auditability and integrity.

```mermaid
flowchart TD
    A[User / External System] --> B[API Gateway]
    B --> C[news-handler]
    C --> D[generate-assertions]
    C --> E[evidence-search]
    C --> F[ipfs-fastapi]
    C --> G[news-chain]
    F --> I[(IPFS)]
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

In this mode:

* Documents are stored in IPFS.
* Posts are registered in Ethereum.
* Validation requests are emitted as blockchain events.
* Validators submit results back to the smart contract.
* Validation documents are linked through IPFS CIDs.

---

## 🔎 Evidence Search

TrustNews includes a dedicated `evidence-search` service used by RAG validators.

RAG evidence search retrieves supporting or contradicting sources before validating an assertion.

The service exposes:

```http
POST /search/evidence
```

It uses MongoDB for:

```text
newsdb.evidence_domain_profiles
newsdb.evidence_normalization_configs
newsdb.evidence_search_cache
```

Search results are cached using a key based on:

* Normalized assertion.
* Search policy.
* Preferred-domain mode.
* Domain profile version.
* Search backend settings.

---

## Preferred-Domain Strategy

Evidence search is controlled by:

```env
EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS
```

Supported modes:

| Mode | Meaning |
|---|---|
| `NONE` | Use only the search suggested by `generate-assertions` or the fallback assertion query |
| `LOCAL` | Enrich preferred domains using MongoDB-stored profiles and pass them as `include_domains` |
| `EXT_OFFICIAL_FIRST` | Ask the external provider to prioritize official sources |
| `EXT_ONLY_OFFICIAL` | Ask the external provider to restrict results to official sources when supported |

External modes depend on the capabilities of the configured search provider.

---

## 🧩 Main Components

| Component | Responsibility |
|---|---|
| `gateway` | Authenticated API entrypoint |
| `admin` | Clients, quotas and evidence-search configuration |
| `news-handler` | Main orchestration service |
| `generate-assertions` | AI-based assertion extraction |
| `evidence-search` | RAG evidence retrieval, domain routing and cache |
| `validate-assertions` / `validate-asertions` | Automated validation workers |
| `news-chain` | Blockchain access layer |
| `ipfs-fastapi` | IPFS document storage abstraction |
| `mongodb` | Orders, quotas, evidence, profiles and cache |
| `keycloak` | Identity provider |
| `TrustNews.sol` | Smart contract for blockchain mode |
| `web_classic` | Frontend |
| `kafka` | Asynchronous event backbone |

---

## 🏗️ Architecture

<img src="./docs/img/Architecture.png" width="70%"/>

Main architectural traits:

* Domain-oriented microservices.
* Kafka-based asynchronous communication.
* Pluggable AI providers and validators.
* MongoDB-backed operational state.
* Dedicated evidence-search service.
* Optional IPFS and Ethereum auditability.
* Kubernetes/Skaffold deployment profiles.

```mermaid
flowchart TD
    A[Frontend / Client] --> B[API Gateway]
    B --> C[news-handler]

    C --> D[generate-assertions]
    C --> E[evidence-search]
    C --> F[validate-assertions]
    C --> G[(MongoDB)]

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

---

## 🔒 Security

<img src="./docs/img/security.png" width="70%"/>

Security capabilities include:

* OIDC authentication for frontend users.
* OAuth 2.0 Client Credentials for B2B partners.
* Gateway token validation.
* Internal client identity generation.
* Admin API quota control.
* Secure forwarding to internal services.
* Environment-based secret management.
* Production secrets created outside the repository.

---

## 🚀 Quick Start

### Prerequisites

* Docker >= 24
* Kubernetes local cluster
* Kind
* Skaffold v4
* kubectl
* 8GB RAM recommended

### Clone

```bash
git clone https://github.com/<your-user>/trustnews.git
cd trustnews
```

### Local Environment Files

Create local `.env` files from the provided examples before running Skaffold.

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

Example:

```bash
cp k8s/infra/mongodb/overlays/local/mongodb.env.example \
  k8s/infra/mongodb/overlays/local/mongodb.env

cp k8s/apis/mongodb-app/overlays/local/mongodb-app.env.example \
  k8s/apis/mongodb-app/overlays/local/mongodb-app.env
```

Real secrets must never be committed.

---

## Local Kubernetes Run

The repository is organized around Skaffold profiles:

```bash
skaffold dev -p setup
skaffold dev -p blockchain
skaffold dev -p infra
skaffold dev -p apis-frontend
```

Main local URLs:

| Service | URL |
|---|---|
| Frontend | https://localhost:7443 |
| Keycloak Admin | https://localhost:7443/auth/admin/master/console/ |
| Admin API | http://localhost:8400/docs |
| Gateway | http://localhost:8500/docs |
| Evidence Search | http://localhost:8074/docs |
| Mongo Express | http://localhost:8081 |
| Kafdrop | http://localhost:9000 |
| Grafana | http://localhost:3000 |

---

## Configuration Example

```env
APP_MODE=LIGHT
# APP_MODE=BLOCKCHAIN

EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=LOCAL
# EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=NONE
# EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=EXT_OFFICIAL_FIRST
# EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=EXT_ONLY_OFFICIAL

EVIDENCE_SEARCH_CACHE_TTL_SECONDS=86400

SEARCH_PROVIDER=tavily
API_KEY_PROVIDER=...

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

## 📚 Additional Documentation

A more detailed architecture and evidence-search document.

* `docs/k8s/TrustNews_detailed.md`

Recommended detailed documents:

* `docs/k8s/skaffold.md`
* `docs/k8s/kind.md`
* `docs/docker/installation_blockchain.md`
* `docs/blockchain/scripts_blockchain.md`



---

## 🛣️ Roadmap

* [x] Secure and authenticate platform.
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
* [x] Blockchain event-based validation.
* [x] Gateway authentication.
* [x] Admin and quota management.
* [x] Kubernetes/Skaffold deployment workflow.
* [ ] Improve evidence ranking and deduplication.
* [ ] Improve provider-specific official-source filtering behavior.
* [ ] Validator reputation system.
* [ ] Full production hardening.
* [ ] Performance and cost analysis.
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
* `BLOCKCHAIN` mode has higher operational complexity than `LIGHT` mode.

---

## 📄 License

Academic / research use only.

---

## 👤 Author

Developed as a **Master Thesis – Proof of Concept**, later extended in the post-TFM phase.

---

## 📌 Summary

TrustNews is a flexible automated news validation platform.

It supports:

* **LIGHT mode** for centralized validation.
* **BLOCKCHAIN mode** for auditable validation.
* **RAG evidence search** with preferred-domain strategies.
* **AI validators** for unattended assertion verification.

The goal is to provide a modular, extensible and auditable approach to automated news verification.
