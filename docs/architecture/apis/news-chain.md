# News Chain

## Description

`api/news-chain` is the HTTP/Kafka layer on the smart contract TrustNews. It registers news in blockchain, consults transactions, blocks, posts and validators, and listens to contract events to propagate requests or validation results to the Kafka flow.

## Endpoints

- `POST /registerNew`: Sends a `registerNew` transaction to the contract to register a noticia/documento and returns `tx_hash`.
- `GET /tx/status/{tx_hash}`: Checks if a transaction is pending, mined or failed, and extracts relevant events if they exist.
- `GET /tx/{tx_hash}`: returns transaction detail and recipit.
- `GET /block/{block_id}`: returns block information and its transactions.
- `GET /blockchain/post/{post_id}`: recovers post, CID, assertions and validations from the contract.
- `GET /blockchain/validators`: list of validators registered and optionally retrieves their settings from IPFS.
- `GET /blockchain/validators/{validator_address}`: Recovers a concrete validator and its configuration.

## Daemons

- `blockchain_event_listener`: listens to blockchain events related to validations, especially `ValidationSubmitted` results, and publishes validation messages completed in Kafka.
- Consumer Kafka `consume_register_kafka`: listen to `KAFKA_REQUEST_TOPIC` with `group_id=trustnews-api-group`. Receive blockchain registration requests, call `registerNew`, wait for confirmation, parse events and publish `blockchain_registered` in `KAFKA_RESPONSE_TOPIC`.

## Initialisation

When loading the module validates the Web3 connection with `RPC_URL`, load the ABI, create the instance of the contract and check that there is bytecode deployed in `CONTRACT_ADDRESS`. If it fails, the process ends. In `startup` launches the blockchain event lister and the Kafka consumer in the background.

## Environment variables

- `RPC_URL`: endpoint RPC Ethereum.
- `PRIVATE_KEY`: clave privada usada para firmar transacciones.
- `ACCOUNT_ADDRESS`: cuenta emisora.
- `CONTRACT_ADDRESS`: address of TrustNews contract.
- `CONTRACT_ABI_PATH`: route to ABI of the contract.
- `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_REQUEST_TOPIC`: Topical blockchain registration requests.
- `KAFKA_RESPONSE_TOPIC`: topic of answers.
- `IPFS_FASTAPI_URL`: IPFS service URL to recover documentos/configuraciones.
