**Just one shot execution**
```bash infra
kubectl create namespace apis
kubectl create namespace infra
kubectl create namespace blockchain
kubectl create namespace frontend


kubectl create secret generic validator-secret-1 --from-env-file=worker-1.env -n apis
kubectl create secret generic validator-secret-2 --from-env-file=worker-2.env -n apis
kubectl create secret generic validator-secret-3 --from-env-file=worker-3.env -n apis

kubectl create secret generic api-keys --from-env-file=generate-asertions.env -n apis

kubectl create secret generic news-chain-secrets --from-env-file=news-chain.env -n apis

kubectl create secret generic news-handler-secrets --from-env-file=news-handler.env -n apis

kubectl create secret generic mongodb-secret --from-env-file=news-handler.env -n infra

kubectl create secret tls frontend-tls \
  --cert=./web_classic/certs/fullchain.pem \
  --key=./web_classic/certs/privkey.pem \
  -n frontend

```

