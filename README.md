# 📰 TrustNews

> **Automated news verification using AI, IPFS and Ethereum**
> Proof of Concept (Academic / Research Project)

![status](https://img.shields.io/badge/status-proof--of--concept-blue)
![python](https://img.shields.io/badge/python-3.10+-blue)
![docker](https://img.shields.io/badge/docker-compose-blue)
![blockchain](https://img.shields.io/badge/blockchain-ethereum-lightgrey)
![license](https://img.shields.io/badge/license-academic-lightgrey)

---

## 🔍 What is TrustNews?

**TrustNews** is a **Proof of Concept** for a system that automatically verifies news content by:

* Breaking news into **atomic, objective assertions**
* Validating each assertion using **AI-based validators**
* Persisting the full validation process **immutably on Ethereum**
* Storing documents in a **distributed way using IPFS**

The entire verification pipeline is **fully automated and unattended**, from publication to final validation.

---

## ✨ Why does this matter?

Most fact-checking solutions are:

* Manual or semi-automated
* Centralized
* Not auditable end-to-end

TrustNews explores a different approach:

* ✅ Assertions instead of full-text validation
* ✅ Multiple automated validators
* ✅ Tamper-proof validation history
* ✅ Full traceability (Order → IPFS → Blockchain)

---

## 🧠 Core Ideas

1. **Atomic Assertions**
   News is decomposed into small, verifiable statements.

2. **Unattended Validation**
   AI validators automatically verify assertions without human intervention.

3. **Immutable Traceability**
   Every step is recorded either in IPFS or Ethereum.

---

## 🏗️ Architecture (High Level)

```text
Frontend
   │
   ▼
news-handler (Orchestrator)
   │
   ├─ Kafka ─▶ generate-assertions (AI)
   ├─ Kafka ─▶ ipfs-fastapi (IPFS)
   ├─ Kafka ─▶ news-chain (Ethereum)
   └─ Kafka ─▶ validate-assertions (AI Validators)
```

**Key traits**:

* Domain-oriented microservices
* Asynchronous messaging (Kafka)
* Pluggable AI validators
* Private Ethereum network (PoA)

---

## 🧩 Main Components

| Component             | Responsibility                 |
| --------------------- | ------------------------------ |
| `news-handler`        | End-to-end orchestration       |
| `generate-assertions` | AI-based assertion extraction  |
| `validate-assertions` | Automated assertion validation |
| `news-chain`          | Blockchain access layer        |
| `ipfs-fastapi`        | Document storage abstraction   |
| `TrustNews.sol`       | Immutable system state         |
| `frontend`            | User interaction & monitoring  |

---

## 🚀 Quick Start

### Prerequisites

* Docker >= 24
* Docker Compose >= 2
* 8GB RAM recommended

### Clone & Run

```bash
git clone https://github.com/<your-user>/trustnews.git
cd trustnews
docker compose up --build
```

After startup, services will be available locally (frontend, APIs, blockchain, IPFS).

> ⏳ First startup may take a few minutes (Ethereum + Kafka initialization)

---

## 📂 Project Structure

```text
.
├── smart-contracts/
├── news-handler/
├── news-chain/
├── generate-assertions/
├── validate-assertions/
├── ipfs-fastapi/
├── frontend/
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 🔐 Configuration & Secrets

* `.env.example` provided
* Each developer must create its own `.env`
* **Never commit real secrets**

AI providers and blockchain accounts are configured via environment variables.

---

## ✅ Integrity Checks

The system includes **automatic consistency checks** across:

* MongoDB orders
* IPFS documents
* Ethereum posts, assertions and validations

Ensuring the system is **auditable and tamper-resistant**.

---

## 🛣️ Roadmap

* [ ] Validator reputation system
* [ ] External validator registration
* [ ] Public Ethereum deployment
* [ ] Advanced AI ensemble validation
* [ ] Performance and cost analysis

---

## 🤝 Contributing

This is an academic PoC, but contributions are welcome:

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Open a Pull Request

---

## 📄 License

Academic / research use only.

---

## 👤 Author

Developed as a **Master Thesis – Proof of Concept**.

---
