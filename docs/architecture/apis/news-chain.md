# News Chain

## Descripción

`api/news-chain` es la capa HTTP/Kafka sobre el smart contract TrustNews. Registra noticias en blockchain, consulta transacciones, bloques, posts y validadores, y escucha eventos del contrato para propagar solicitudes o resultados de validación al flujo Kafka.

## Endpoints

- `POST /registerNew`: envía una transacción `registerNew` al contrato para registrar una noticia/documento y devuelve `tx_hash`.
- `GET /tx/status/{tx_hash}`: comprueba si una transacción está pendiente, minada o fallida, y extrae eventos relevantes si existen.
- `GET /tx/{tx_hash}`: devuelve detalle de transacción y receipt.
- `GET /block/{block_id}`: devuelve información de bloque y sus transacciones.
- `GET /blockchain/post/{post_id}`: recupera post, CID, aserciones y validaciones desde el contrato.
- `GET /blockchain/validators`: lista validadores registrados y opcionalmente recupera su configuración desde IPFS.
- `GET /blockchain/validators/{validator_address}`: recupera un validador concreto y su configuración.

## Daemons

- `blockchain_event_listener`: escucha eventos blockchain relacionados con validaciones, especialmente resultados `ValidationSubmitted`, y publica mensajes de validación completada en Kafka.
- Consumidor Kafka `consume_register_kafka`: escucha `KAFKA_REQUEST_TOPIC` con `group_id=trustnews-api-group`. Recibe solicitudes de registro blockchain, llama a `registerNew`, espera confirmación, parsea eventos y publica `blockchain_registered` en `KAFKA_RESPONSE_TOPIC`.

## Inicialización

Al cargar el módulo valida la conexión Web3 con `RPC_URL`, carga el ABI, crea la instancia del contrato y comprueba que hay bytecode desplegado en `CONTRACT_ADDRESS`. Si falla, termina el proceso. En `startup` lanza el listener de eventos blockchain y el consumidor Kafka en segundo plano.

## Variables de entorno

- `RPC_URL`: endpoint RPC Ethereum.
- `PRIVATE_KEY`: clave privada usada para firmar transacciones.
- `ACCOUNT_ADDRESS`: cuenta emisora.
- `CONTRACT_ADDRESS`: dirección del contrato TrustNews.
- `CONTRACT_ABI_PATH`: ruta al ABI del contrato.
- `KAFKA_BOOTSTRAP`: bootstrap Kafka.
- `KAFKA_REQUEST_TOPIC`: tópico de solicitudes de registro blockchain.
- `KAFKA_RESPONSE_TOPIC`: tópico de respuestas.
- `IPFS_FASTAPI_URL`: URL del servicio IPFS para recuperar documentos/configuraciones.
