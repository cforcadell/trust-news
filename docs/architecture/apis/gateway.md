# API Gateway

## Description

`api/gateway` expone la API pública unificada bajo `root_path=/backend`. Valida tokens JWT de Keycloak y reenvía las peticiones autenticadas a los microservicios internos de órdenes, generación de aserciones, IPFS y blockchain. También calcula el `client_id` efectivo a partir del token y propaga permisos de administración.

## Endpoints

- `GET /auth/is-admin`: returns if the authenticated user has the `trust-admin` role.
- `POST /assertions/generate`: forward the text to `generate-asertions` (`/extraer`) and inject `client_id` for quota control.
- `POST /orders/publishNew`: Creates a new command in `news-handler` to generate assertions and continue validation flow.
- `POST /orders/publishWithAssertions`: Creates an order in `news-handler` using pre-generated assertions.
- `POST /extract_text_from_url`: forwards text extraction from URL to `news-handler`.
- `GET /orders/list`: Lists commands from `news-handler`; if the user is admin and `view_all=true`, it allows you to view all.
- `GET /orders/{order_id}`: recovers a specific command, spreading `client_id` and flag `admin`.
- `GET /orders/checkOrderConsistency/{order_id}`: forwards Order/IPFS/Blockchain. consistency check
- `GET /orders/{order_id}/events`: Recovers events from an order from `news-handler`.
- `GET /ipfs/{cid}`: Recovers IPFS content using IPFS service.
- `GET /blockchain/tx/{hash}`: Consult a transaction in `news-chain`.
- `GET /blockchain/block/{block_id}`: Consult a block in `news-chain`.
- `GET /blockchain/post/{post_id}`: see a post registered in the contract.
- `GET /validators/cache`: Checked validation list from `news-handler`.
- `GET /validators/cache/{validator_hash}`: recovers detail from a cached validator.
- `GET /validators/cache/{validator_hash}/validations`: recovers validations associated with a validator, with optional filters by proveedor/modelo.

## Limits and traceability

The security middleware rejects with `413` any body that exceeds the maximum, including if it arrives fragmented or without `Content-Length`. Before invoking the proxy stores as maximum that volume and reproduces the body for FastAPI. Each response generates a JSON `gateway_access` event and returns `X-Request-ID`; no tokens, query strings or bodies are recorded.

## Daemons

It does not start consumers or producers of its own. Its task is to act as an authenticated HTTP proxy.

## Initialisation

When booting up `.env`, configure logging, build internal Keycloak microservices and URLs URLs. In each protected request, download the Keycloak JWKS, valid JWT signature and issuer, and use the claims to calculate identity and management role.

## Environment variables

- `LOG_LEVEL`: logging level.
- `NEWS_HANDLER_URL`: Internal command orchestrator URL.
- `NEWS_CHAIN_URL`: Internal URL of the blockchain service.
- `IPFS_API_URL`: IPFS service internal URL.
- `GENERATE_ASSERTIONS_URL`: internal URL of the assertion generator.
- `KEYCLOAK_ISSUER_URL`: issuer público exacto que debe contener el token.
- `KEYCLOAK_JWKS_URL`: Full internal URL used to download keys
Keycloak public. It does not alter the validated issuer.
- `KEYCLOAK_SERVER_INNER_URL`: compatibility with old configurations; only
is used to build the JWKS URL when `KEYCLOAK_JWKS_URL` is not defined.
- `KEYCLOAK_REALM`: realm used by the local configuration fallback.
- `GATEWAY_API_DOCS_ENABLED`: enables `/docs`, `/redoc` and `/openapi.json`.
Productive overlays are set at `false`.
- `GATEWAY_MAX_REQUEST_BODY_BYTES`: HTTP body maximum positive; by
defect `5242880` (5 MiB) and must match the middleware of Traefik.

- `PORT`: uvicorn port if executed directly.
