# 🛠️ Installation & Setup Guide

This document explains how to install and run the **TrustNews Proof of Concept** locally.

Two blockchain execution modes are supported:
- **Hardhat (recommended for development)**
- **Private Ethereum (Geth – PoA)**

---

## 1️⃣ Blockchain Setup

### Option A – Hardhat (Development Mode ✅ Recommended)

```bash
cd smart-contracts
npx hardhat node --hostname 0.0.0.0
```

✅ Hardhat RPC should be available at:
```
http://127.0.0.1:8545
```

#### Deploy Smart Contract

```bash
npx hardhat run scripts/deploy.js --network localhost
```

#### Verify Registered Validators (initially empty)

```bash
npx hardhat run scripts/registeredValidators.js --network localhost
```

#### Environment Configuration

Copy the deployed **contract address** into:
- `news-chain/.env`
- `validate-assertions*/.env`
- `registeredValidators.js`

---

### Option B – Private Ethereum (Geth – PoA)

If using the private Ethereum network based on Geth:

👉 Follow the instructions located at:
```
docs/installation_blockchain.md

```

(This option is more realistic but slower and heavier.)

---

## 2️⃣ Environment Configuration

Before starting containers, create local environment files:

```bash
cp .env.example .env
```

Repeat for each module that provides its own `.env.example`.

⚠️ **Never commit real `.env` files**

---

## 3️⃣ Start Base Infrastructure

This includes:
- MongoDB
- Kafka
- Zookeeper
- Ethereum / IPFS (depending on mode)

```bash
docker compose -f docker-compose.base.yml down
docker compose -f docker-compose.base.yml build
docker compose -f docker-compose.base.yml up
```

---

## 4️⃣ Start API Services

```bash
docker compose -f docker-compose.apis.yml down
docker compose -f docker-compose.apis.yml build
docker compose -f docker-compose.apis.yml up
```

After startup, verify that validators are correctly registered:

```bash
npx hardhat run scripts/registeredValidators.js --network localhost
```

✅ Validators should now appear in the list.

---

## 5️⃣ Run End-to-End Tests

```bash
cd api/tests
source venv/bin/activate
pytest -v test_news-handler.py
```

---

## 6️⃣ Run Statistics & Load Tests

```bash
cd api/tests
source venv/bin/activate
```

Example:

```bash
python stats.py \
  --text "Text to validate" \
  --num_runs 2 \
  --timeout 200 \
  --csv_file ./stats.out
```

---

## 7️⃣ Available Swagger UIs

| Service | URL |
|--------|-----|
| Frontend | http://127.0.0.1:8000 |
| IPFS API | http://127.0.0.1:8060/docs |
| News Handler | http://127.0.0.1:8072/docs |
| Assertion Generator | http://127.0.0.1:8071/docs |
| News Chain | http://127.0.0.1:8073/docs |
| Validator Worker 1 | http://127.0.0.1:8070/docs |
| Validator Worker 2 | http://127.0.0.1:8069/docs |

---
