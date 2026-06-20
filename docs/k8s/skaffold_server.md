# Despliegue Trust News en Hetzner

## Orden de inicialización de un entorno nuevo

El orden recomendado evita que las APIs arranquen contra una base de datos o un contrato incompletos:

1. Crear namespaces y secretos.
2. Desplegar `infra-prod` y esperar a MongoDB, Kafka e IPFS.
3. Inicializar MongoDB con usuarios, índices, taxonomías y preferred domains.
4. Desplegar la blockchain privada.
5. Desplegar `TrustNews` e inicializar/verificar las categorías on-chain.
6. Configurar `CONTRACT_ADDRESS` en las APIs y desplegar `apis-prod`.
7. Crear clientes/cuotas de negocio mediante `admin`; no deben incluirse como datos fijos del bootstrap.

## Inicialización general de MongoDB

### Secretos requeridos

El secreto `mongodb-secret` del namespace `infra` debe contener:

```dotenv
MONGO_INITDB_ROOT_USERNAME=<root-user>
MONGO_INITDB_ROOT_PASSWORD=<root-password>
MONGO_APP_USERNAME=<application-user>
MONGO_APP_PASSWORD=<application-password>
MONGO_APP_DATABASE=newsdb
```

`mongodb-app-secret` en `apis` debe usar el mismo usuario, contraseña y base de datos de aplicación. No se deben versionar estos valores.

El fichero [`k8s/infra/mongodb/init-users.js`](../../k8s/infra/mongodb/init-users.js) montado en `/docker-entrypoint-initdb.d` crea el usuario de aplicación automáticamente, pero Mongo solo ejecuta estos scripts cuando `/data/db` está vacío. No basta para restauraciones, PVC reutilizados o actualizaciones de configuración.

### Bootstrap idempotente después de desplegar infra

Desde la raíz del repositorio en el servidor:

```bash
kubectl apply -k k8s/infra/mongodb/overlays/prod
kubectl rollout status statefulset/mongodb -n infra --timeout=180s

scripts/k8s/init-mongodb-server.sh --dry-run
scripts/k8s/init-mongodb-server.sh
```

El script [`scripts/k8s/init-mongodb-server.sh`](../../scripts/k8s/init-mongodb-server.sh):

- crea o actualiza el usuario de aplicación;
- crea los índices generales de `news`, `clients_quotas`, `events` y `validations`;
- reemplaza solamente el perfil `default` en `evidence_domain_profiles`;
- elimina los documentos e índices del antiguo modelo `profile_index/profile_subset` para ese perfil;
- hace upsert de los tres documentos de `evidence_normalization_configs`;
- crea los índices de `evidence_search_cache` y limpia la caché por defecto.

Los seeds versionados son:

```text
api/evidence-search/config/evidence-domain-profile-default.json
api/evidence-search/config/evidence-normalization-configs.json
```

Para conservar la caché —normalmente no es recomendable después de cambiar perfiles—:

```bash
scripts/k8s/init-mongodb-server.sh --keep-cache
```

Para indicar otro namespace o pod:

```bash
scripts/k8s/init-mongodb-server.sh --namespace infra --pod mongodb-0
```

El script usa el cliente `mongo` que ya existe dentro del pod y las credenciales del propio secreto; no requiere exponer el puerto 27017 ni instalar `pymongo` en el servidor.

### Verificación MongoDB

```bash
kubectl exec -it mongodb-0 -n infra -- sh -c \
  'mongo -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "$MONGO_APP_DATABASE" --quiet --eval "const p=db.evidence_domain_profiles.findOne({profile_id: \"default\"}); printjson({profiles: db.evidence_domain_profiles.countDocuments({profile_id: \"default\"}), normalization: db.evidence_normalization_configs.countDocuments({}), domains: p ? p.domains.length : 0})"'
```

Resultado esperado:

```text
profiles: 1
normalization: 3
domains: 8
```

Los servicios también recrean sus índices al arrancar. El script de bootstrap los crea anticipadamente para detectar duplicados o problemas de permisos antes de desplegar las APIs.

## Inicialización de categorías blockchain

Las categorías no se guardan en MongoDB. Su fuente de verdad es el contrato `TrustNews`; `api/common/category_catalog.py` es el espejo backend y debe coincidir con [`smart-contracts/config/categories.json`](../../smart-contracts/config/categories.json).

### Contrato nuevo

El despliegue ya registra las diez categorías. La clave no se escribe en `hardhat.config.js`; se proporciona mediante `DEPLOYER_PRIVATE_KEY`:

```bash
cd smart-contracts
read -rsp "Deployer private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/deployGeth.js --network cloudGeth
unset DEPLOYER_PRIVATE_KEY
```

Anotar la dirección mostrada y configurarla como `CONTRACT_ADDRESS` en los componentes que consumen el contrato.

### Contrato ya desplegado o despliegue interrumpido

El inicializador es idempotente: crea categorías ausentes, deja intactas las correctas y falla si un ID existente tiene otro nombre. Debe ejecutarse con la cuenta propietaria del contrato:

```bash
cd smart-contracts
export CONTRACT_ADDRESS=0x<direccion-trust-news>
read -rsp "Contract owner private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/initCategories.js --network cloudGeth
# Repetir para verificar idempotencia: debe mostrar diez entradas "unchanged".
npx hardhat run scripts/initCategories.js --network cloudGeth
unset DEPLOYER_PRIVATE_KEY
```

Si aparece `Signer ... is not contract owner`, hay que usar la clave privada de la cuenta que desplegó el contrato. Si aparece un `mismatch`, no se debe continuar: `addCategory` no permite modificar una categoría existente y hay que corregir la red/contrato seleccionado o desplegar uno nuevo.

## Reejecución y recuperación

- `initCategories.js` se puede repetir siempre que se use el propietario y el mismo contrato.
- `init-mongodb-server.sh` preserva noticias, validaciones, eventos, cuotas y perfiles distintos de `default`.
- El bootstrap Mongo reemplaza el perfil `default` y las taxonomías por las versiones del repositorio.
- Los scripts de `/docker-entrypoint-initdb.d` no se vuelven a ejecutar con un PVC existente; usar siempre el bootstrap explícito tras restaurar o actualizar.
- Antes de cambiar datos productivos, realizar backup del PVC o `mongodump`.

---

**Just one shot execution**
```bash infra inside server 
scripts/k8s/create-namespaces.sh

secrets/create-secrets.sh

touch worker-1.env worker-2.env worker-3.env generate-asertions.env news-chain.env mongodb-app.env mongodb.env gateway.env keycloak.env ethereum.env
chmod 600 *.env

kubectl create secret generic validator-secret-1 --from-env-file=worker-1.env -n apis
kubectl create secret generic validator-secret-2 --from-env-file=worker-2.env -n apis
kubectl create secret generic validator-secret-3 --from-env-file=worker-3.env -n apis

kubectl create secret generic api-keys --from-env-file=generate-asertions.env -n apis

kubectl create secret generic news-chain-secrets --from-env-file=news-chain.env -n apis

kubectl create secret generic mongodb-app-secret --from-env-file=mongodb-app.env -n apis

kubectl create secret generic gate-config --from-env-file=gateway.env -n apis


kubectl create secret generic mongodb-secret --from-env-file=mongodb.env -n infra

kubectl create secret generic keycloak-admin-secret --from-env-file=keycloak.env -n infra

kubectl create secret generic ethereum-secrets  --from-env-file=ethereum.env -n blockchain

#create gitlab secrets

create-secrets-gitlab.sh*

kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=gitlab+deploy-token-13012600 \
  --docker-password= \
  --docker-email=cforcadell@gmail.com \
  --namespace=apis

kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=gitlab+deploy-token-13012600 \
  --docker-password= \
  --docker-email=cforcadell@gmail.com \
  --namespace=infra
kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=gitlab+deploy-token-13012600 \
  --docker-password= \
  --docker-email=cforcadell@gmail.com \
  --namespace=blockchain
kubectl create secret docker-registry gitlab-pull-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=gitlab+deploy-token-13012600 \
  --docker-password= \
  --docker-email=cforcadell@gmail.com \
  --namespace=frontend


kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=apis

kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=infra

kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=blockchain

kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "gitlab-pull-secret"}]}' \
  --namespace=frontend



#inside secrets folder
kubectl create secret tls keycloak-tls-secret \
  --cert=./tls-keycloak.crt \
  --key=./tls-keycloak.key \
  -n infra


#kubectl create secret tls frontend-tls \
#  --cert=./web_classic/certs/fullchain.pem \
#  --key=./web_classic/certs/privkey.pem \
#  -n frontend

```
**Deploy blockchain resources**
#use apipeline with PROFILE=blockchain-prod and check peers

kubectl exec -it geth-miner-0 -n blockchain -- geth attach --exec "net.peerCount"

kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec "net.peerCount"

**Deploy contract using ssh tunnel**


```bash blockchain ~/blockchain/hetzner/keys-github
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 8565:localhost:8555 sysadmin@135.181.80.57 -t "kubectl port-forward pod/geth-rpc-endpoint-0 -n blockchain 8555:8555"


```

La red `cloudGeth` ya está definida en `hardhat.config.js`. Mantener el túnel abierto y proporcionar la cuenta mediante entorno:

```bash
cd smart-contracts
read -rsp "Deployer private key: " DEPLOYER_PRIVATE_KEY && echo
export DEPLOYER_PRIVATE_KEY
npx hardhat run scripts/deployGeth.js --network cloudGeth
unset DEPLOYER_PRIVATE_KEY

# Guardar la dirección mostrada como CONTRACT_ADDRESS en las APIs.
```

```bash blockchain inside server

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

#check contract
kubectl exec -it geth-rpc-endpoint-0 -n blockchain -- geth attach --exec 'eth.getCode("0x9eA62eb7944349C407B307025644E47bF22F8bCc")'
```


```bash infra

#use pipeliney  profile infra-prod


kubectl get pods -n infra


kubectl logs -n infra -f kafka-0


#si al parar los pods a replicas=0 o eliminar los statefuls quedan pvcs
kubectl get pvc -n infra
kubectl delete pvc ipfs-storage-ipfs-0 -n infra
kubectl delete pvc kafka-data-kafka-0 -n infra
kubectl delete pvc mongodb-storage-mongodb-0 -n infra

```



```bash tunnel vmlinux home-> apis c
#ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 9443:127.0.0.1:10443 sysadmin@135.181.80.57 "kubectl port-forward pod/frontend-web-75b7d945cb-bg2bh -n frontend 10443:443 --address 0.0.0.0"

#in hetzner (~/trust-news/scripts/port-forward.sh)
kubectl port-forward service/frontend-service -n frontend 10443:443

# in local vm machine ~/blockchain/hetzner/keys-github (dev)
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 9443:127.0.0.1:10443 sysadmin@135.181.80.57


https://localhost:9443/

https://localhost:9443/backend/docs


```

kubectl get pods -n infra
**start/stop pods**
```bash 

kubectl scale statefulset --all --replicas=0 -n infra blockchain 
kubectl scale statefulset --all --replicas=1 -n infra blockchain 

```
**keycloak**
```bash 
https://localhost:9443/auth/admin/master/console/



Crea el Realm: * Haz clic en el desplegable de arriba a la izquierda (Master) y dale a Create Realm.

Nombre: TrustNews.

Crea el Cliente para la Web (Frontend):

Clients -> Create client.

ClientID: TrustNewsWeb.

Root URL: https://localhost:9443 (o la URL de tu frontend).
Valid redirect: https://localhost:9443/*

Web Origins: * (para evitar problemas de CORS en desarrollo).

Crea el Cliente para los Backends Públicos (Lo que pediste al inicio):

Clients -> Create client.

ClientID: TrustNewsApi.

Client Authentication: Ponlo en ON.

Authorization: Ponlo en OFF.

Authentication Flow: Marca solo Service accounts roles (desmarca el resto). 

Una vez guardado, ve a la pestaña Credentials y ahí verás el Client Secret que necesitarán los backends externos para llamarte.

En realm settings (TrustNews)
Frontend URL: https://localhost:9443/auth/ ¿?¿?¿?¿?

Craer usuario p federetad identity

#get token
curl -k -X POST https://localhost:9443/auth/realms/TrustNews/protocol/openid-connect/token -H "Content-Type: application/x-www-form-urlencoded" -d "grant_type=client_credentials" -d "client_id=TrustNewsApi" -d "client_secret=xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"





```


**grafana**
```bash tunnel grafana ~/blockchain/hetzner/keys-github. Si ocupado abrir terminal en hetzner y matar proceso netstat -nap | grep 10443
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 3300:127.0.0.1:3300 sysadmin@135.181.80.57 "kubectl port-forward pod/grafana-7964997b9b-skqjw -n infra 3000:3000 --address 0.0.0.0"

http://localhost:3300/



#Add datasource in grafana: http://loki.infra.svc.cluster.local:3100

Explore + Run query

#change inside hetzner. ex: bootnode
kubectl edit statefulset geth-bootnode -n blockchain
```



```bash problemas de connection refused en descargar imágenes (Ej: python:3.11-slim )
docker pull mirror.gcr.io/library/python:3.11-slim

docker tag mirror.gcr.io/library/python:3.11-slim python:3.11-slim
```

**admin & quotas**
```bash admin
#in hetzner (scripts/port-forward.sh)
kubectl port-forward service/admin-service -n apis 7400:8400

#~/blockchain/hetzner/keys-github (dev)
ssh -i ./id_rsa_hetzner_deploy -p 2222 -L 0.0.0.0:7400:127.0.0.1:7400 sysadmin@135.181.80.57

http://127.0.0.1:7400/docs 


Ex: craeate user 
http://localhost:7400/clients
  {
    "name": "cforcadellm",
    "limits": {
      "news_generation": 99999999,
      "blockchain_validation": 99999999
    },
    "consumed": {
      "news_generation": 0,
      "blockchain_validation": 0
    },
    "status": "Active",
    "active_date": "2026-05-01T09:59:08.903000",
    "deactivate_date": null,
    "client_id": "user_e96fcb10-25a3-4773-88e0-86452cf3d309"
  }


Ex: craeate API KEY (get sub from existing token)
http://localhost:7400/clients

  {
    "name": "Test Quota Client",
    "limits": {
      "news_generation": 2,
      "blockchain_validation": 2
    },
    "consumed": {
      "news_generation": 2,
      "blockchain_validation": 2
    },
    "status": "Active",
    "active_date": "2026-04-30T18:22:40.269000",
    "deactivate_date": null,
    "client_id": "TrustNewsApi_<id_API>"
  }
```