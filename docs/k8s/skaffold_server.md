**Just one shot execution**
```bash infra inside server
touch worker-1.env worker-2.env worker-3.env generate-asertions.env news-chain.env news-handler.env mongodb.env
chmod 600 *.env

kubectl create secret generic validator-secret-1 --from-env-file=worker-1.env -n apis
kubectl create secret generic validator-secret-2 --from-env-file=worker-2.env -n apis
kubectl create secret generic validator-secret-3 --from-env-file=worker-3.env -n apis

kubectl create secret generic api-keys --from-env-file=generate-asertions.env -n apis

kubectl create secret generic news-chain-secrets --from-env-file=news-chain.env -n apis

kubectl create secret generic news-handler-secrets --from-env-file=news-handler.env -n apis

kubectl create secret generic mongodb-secret --from-env-file=mongodb.env -n infra

kubectl create secret generic ethereum-secrets  --from-env-file=ethereum.env -n blockchain


kubectl create secret tls frontend-tls \
  --cert=./web_classic/certs/fullchain.pem \
  --key=./web_classic/certs/privkey.pem \
  -n frontend

```

**Deploy contract using ssh tunnel**
```bash blockchain
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 8565:localhost:8555 sysadmin@135.181.80.57 -t "kubectl port-forward pod/geth-rpc-endpoint-0 -n blockchain 8555:8555"


```

Add hardhat.config.js entry for cloud blockchain

    cloudGeth: {
      url: "http://localhost:8565", 
      accounts: [
        "0x*********************************"
      ],
      gas: 25_000_000,
      chainId: 1214
    }

```bash blockchain from hardhat
cd smart-contracts
npx hardhat run scripts/deployGeth.js --network cloudGeth

#get contract address and configure apis
```

```bash infra inside server

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach http://localhost:8555

eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "0xa28885a13a7b4d3561a7af64ea1ba0f82ed9f06b",
  value: web3.toWei(10, "ether")
})


eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "4504a1d4047583164919ae40c37c4f4c5b854bbb",
  value: web3.toWei(10, "ether")
})


eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "edbef53fc17dde65bf303b3d4983afb7028eb6eb",
  value: web3.toWei(10, "ether")
})


eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "be794abf86d173ddcfe937c6d8d739bdc4e94165",
  value: web3.toWei(10, "ether")
})


eth.sendTransaction({
  from: "0x1747D8AB4dBDc6B2aBe233d5688487A39Bc555B5",
  to: "42d488d0393fd1d6b72bb424db28dd7eb5e06737",
  value: web3.toWei(10, "ether")
})

```