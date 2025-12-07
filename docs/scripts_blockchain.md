# Smart Contract Tests

This project contains scripts to compile, deploy, and test the **TrustNews** smart contracts.  
**Requires Hardhat to be installed.**

---

## 0. Start the Blockchain

**Hardhat (Local Node):**
npx hardhat node --hostname 0.0.0.0

**Geth (Private Network):**
./rebuild.blockchain.sh

---

## 1. Compile & Deploy Smart Contract (Local) and Run Basic Tests

cd smart-contracts
npx hardhat run scripts/testDeployTrustNewsValidators.js

---

## 2. Deploy Smart Contract and Register Categories

**Private Geth Network:**
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth

**Hardhat Localhost:**
cd smart-contracts
npx hardhat run scripts/deployLocal.js --network localhost

---

## 3. Get Registered Validators

> **IMPORTANT:** Update the smart contract address inside the script before running it.

**Private Geth Network:**
cd smart-contracts
npx hardhat run scripts/registeredValidators.js --network privateGeth

**Hardhat Localhost:**
cd smart-contracts
npx hardhat run scripts/registeredValidators.js --network localhost

---

## 4. Set Up APIs

Don't forget to **inform `CONTRACT_ADDRESS`** with the deployed contract address and **rebuild & restart the API containers**.

- `.env` at `news-chain`
- `docker-compose.apis.yml`
