# 🟣 Private Ethereum Network (Geth – PoA) Setup

This document describes how to initialize, configure, and run a **private Ethereum network using Geth (PoA)** for the TrustNews project.

This setup is intended for **advanced users** and realistic blockchain simulation.

---

## 1️⃣ Backup Existing Accounts (Optional)

```bash
mkdir -p accounts
cp blockchain/volumes/miner/keystore accounts/
cp blockchain/volumes/rpc/keystore accounts/
```

---

## 2️⃣ Remove Previous Configuration

Stop and remove blockchain containers and volumes:

```bash
docker compose -f docker-compose.blockchain.yml down -v
```

Remove existing data and recreate directories:

```bash
sudo rm -rf ./volumes/bootnode ./volumes/rpc ./volumes/miner

mkdir ./volumes/bootnode
mkdir ./volumes/rpc
mkdir ./volumes/miner
```

---

## 3️⃣ Create Master Account (Skip if Restoring Accounts)

Create the main Ethereum account (RPC node):

```bash
docker run --rm \
  -v $(pwd)/volumes/rpc:/root/.ethereum \
  -it ethereum/client-go:v1.10.1 \
  account new --datadir /root/.ethereum
```

Example output:
```
Public address of the key:   0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5
Path of the secret key file: /root/.ethereum/keystore/UTC--...
```

Verify the account creation:

```bash
ls volumes/rpc/keystore/
```

---

## 4️⃣ Copy Account to Miner Node (Skip if Restoring)

```bash
sudo mkdir -p ./volumes/miner/keystore
sudo cp ./volumes/rpc/keystore/UTC--* ./volumes/miner/keystore/
```

---

## 5️⃣ Restore Accounts (Optional)

If you previously backed up accounts:

```bash
sudo cp -r ./accounts/miner/keystore ./volumes/miner
sudo cp -r ./accounts/rpc/keystore ./volumes/rpc
```

---

## 6️⃣ Configure Account Passwords (Auto-Unlock)

Create password files:

```bash
sudo echo "<PASSWORD>" > ./volumes/rpc/password.txt
sudo echo "<PASSWORD>" > ./volumes/miner/password.txt
```

⚠️ Use **development-only passwords**.

---

## 7️⃣ Configure Environment Variables

Update `.env`:

```env
MASTER_PUBLIC_KEY=0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5
```

---

## 8️⃣ Generate `genesis.json` (Skip if Restoring)

```bash
cd blockchain
source ~/venv-geth/bin/activate
python3 generate_genesis.py
```

---

## 9️⃣ Distribute `genesis.json`

```bash
sudo cp blockchain/genesis.json volumes/bootnode
sudo cp blockchain/genesis.json volumes/rpc
sudo cp blockchain/genesis.json volumes/miner
```

---

## 🔟 Initialize All Nodes

```bash
docker run --rm -v $(pwd)/volumes/rpc:/root/.ethereum ethereum/client-go:v1.10.1 init /root/.ethereum/genesis.json
docker run --rm -v $(pwd)/volumes/miner:/root/.ethereum ethereum/client-go:v1.10.1 init /root/.ethereum/genesis.json
docker run --rm -v $(pwd)/volumes/bootnode:/root/.ethereum ethereum/client-go:v1.10.1 init /root/.ethereum/genesis.json
```

---

## 1️⃣1️⃣ Extract Private Key (Skip if Restoring)

```bash
cd blockchain
source ~/venv-geth/bin/activate

sudo chmod -R 755 volumes/rpc/keystore
sudo chmod 644 volumes/rpc/keystore/UTC--*
python get_private_key.py volumes/rpc/keystore/UTC--* <PASSWORD>
```

---

## 1️⃣2️⃣ Configure Hardhat Network

Update `hardhat.config.js`:

```js
privateGeth: {
  url: "http://localhost:8555",
  accounts: [
    "0x<PRIVATE_KEY>"
  ],
  chainId: 1214
}
```

---

## 1️⃣3️⃣ Start the Blockchain Network

```bash
docker compose -f docker-compose.blockchain.yml down
docker compose -f docker-compose.blockchain.yml up
```

---

## 1️⃣4️⃣ Verify RPC Accounts

```bash
curl --location --request POST 'localhost:8555' \
--header 'Content-Type: application/json' \
--data-raw '{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "eth_accounts",
  "params": []
}'
```

---

## 1️⃣5️⃣ Check Account Balance

```bash
docker exec -it geth-miner-container geth attach ipc:/root/.ethereum/geth.ipc
```

```js
eth.getBalance("<ADDRESS>")
web3.fromWei(eth.getBalance("<ADDRESS>"), "ether")
```

---

## 1️⃣6️⃣ Deploy Smart Contract

```bash
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network privateGeth
```

Verify deployment:

```js
eth.getCode("<CONTRACT_ADDRESS>")
```

---

## 1️⃣7️⃣ Update Application Configuration

- Update `news-chain/.env`
- Update `docker-compose.apis.yml`

---

## 1️⃣8️⃣ Create Validator & Service Accounts

Create additional accounts:

```bash
docker exec -it geth-rpc-container geth account new --datadir /root/.ethereum
```

Retrieve private key:

```bash
python get_private_key.py volumes/rpc/keystore/UTC--* <PASSWORD>
```

Unlock accounts and fund them:

```bash
docker exec -it geth-rpc-container geth attach /root/.ethereum/geth.ipc
```

```js
personal.unlockAccount("<ADDRESS>", "<PASSWORD>", 0)
eth.sendTransaction({
  from: "<MASTER_ADDRESS>",
  to: "<ADDRESS>",
  value: web3.toWei(10, "ether")
})
```

Repeat for:
- `news-chain`
- `validator1`
- `validator2`
- `validator3`

---

## 🔧 Utilities & Debugging

### Test Connectivity

```bash
docker exec -it validate-asertions-worker_3 /bin/bash
apt update
apt install -y iputils-ping curl
```

```bash
curl -X POST \
  --data '{"jsonrpc":"2.0","method":"web3_clientVersion","params":[],"id":1}' \
  http://geth-rpc-endpoint:8555
```

---

### Check Block Gas Limit

```bash
docker exec -it geth-rpc-container geth attach /root/.ethereum/geth.ipc
```

```js
eth.getBlock("latest").gasLimit
```

---
