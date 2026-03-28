**Just one shot execution**
```bash infra
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

