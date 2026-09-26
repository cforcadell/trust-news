# IPFS

## Description

`api/ipfs` encapsulates the interaction with an IPFS node. It allows uploading documents via HTTP or Kafka and recovering content by CID.

## Endpoints

- `POST /ipfs/upload`: uploads a file or bytes of form to IPFS and returns `cid` and `filename`.
- `GET /ipfs/{cid}`: Consult the content of a CID using the IPFS `cat` API.

## Daemons

- Consumer Kafka `consume_and_process`: listens to `REQUEST_TOPIC` with `group_id=ipfs-agent-group`. Processes `upload_ipfs` messages, serializes the document, uploads it to IPFS and publishes `ipfs_uploaded` in `RESPONSE_TOPIC`.
- Local Kafka Producer: publishes the response with the generated CID.

## Initialisation

Load `.env`, configures logging, IPFS URLs and Kafka topics. In `startup` launches Kafka consumer in the background. Consumers retry connecting to Kafka to `MAX_RETRIES` with `RETRY_DELAY` wait.

## Environment variables

- `LOG_LEVEL`: logging level.
- The output format is JSON single line and is common to other Python services.
- `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_REQUEST_TOPIC`: Topic of IPFS upload requests.
- `KAFKA_RESPONSE_TOPIC`: topic of answers.
- `IPFS_API_ADD`: IPFS `/api/v0/add` endpoint URL.
- `IPFS_API_CAT`: IPFS `/api/v0/cat` endpoint URL.

Constantes internas:

- `MAX_RETRIES`: number of Kafka connection re-attempts.
- `RETRY_DELAY`: wait between retryings.
