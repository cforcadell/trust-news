# Published versions

This document retains the functional result of versions prior to the current version. Active planning is in [`version.md`](version.md) and future versions in [`next_releases.md`](next_releases.md).

## v0.0.12 - Closure of the perimeter and administrative access

- `assermetry.com` was published using Cloudflare with strict TLS and the
Hetzner's origin limited to its verified networks.
- The mTLS general temporary condition was maintained as `v0.0.14` and mTLS protection
Permanent Administrative Office of Keycloak.
- OIDC was aligned with the canonical issuer and log login, session were checked,
  renovación del token y logout.
- Gateway rejected the petitions without JWT and accepted a valid JWT with the role
  administrativo esperado.
- The Light and Blockchain tours were completed under protected access.
- The maintenance lock locked valid user and administrator sessions
and allowed both access to be recovered by disableting it.
- The base line closed the node and the 29 pods prepared without
Restarts, nine `Bound` PVC and observability available.
- `ISSUE-001` remains mitigated and its resolution is moved to `v0.0.13`.
- Controlled revocation of a disposable administrative certificate
will be done in `v0.0.14`.

[Detalle completo del cierre de v0.0.12](releases/v0.0.12.md).

## v0.0.11 - Validators with evidence and renewal of the frontend

- Economic model recommendation endpoints were added through a
API router.
- The Keycloak login theme, the frontend style and the
presentation of validation results.
- Support was incorporated in Spanish and English.
- Monitoring of MongoDB and Kafka was added by Kafdrop.
- Admin and normal users separated and one user adopted
application for APIs.
- The Pydatic models and common functions were centralized.
- Validators were classified as:
`LLM_MEMORY_VALIDATION`, `LLM_SEARCH_VALIDATION`, `RAG_EVIDENCE_VALIDATION`, `DETERMINISTIC_VALIDATION` and `HUMAN`.
- The `evidence-search` service was created, with an abstracted search provider,
Exa support, preferred domain profiles, cache and download content to chunks for RAG validators.
- A RAG validator with preferred domains and two RAG validators was configured
additional models, without such restriction.
- Online search validators support `LOCAL`, `NONE` modes,
`EXT_OFFICIAL_FIRST` and `EXT_ONLY_OFFICIAL`.
- The assertion generator limits each assertion to a single fact and uses the
standard categories throughout the chain.
- Traefik became the common Ingress of local and productive environments.

The historical source left unconfirmed proof that Light mode does not send validations when validators do not exceed health check.

## v0.0.10 - Validators configuration and v2 assertion protocol

- The settings of each validator are stored in IPFS and your hash remains
registered in blockchain during discharge, upgrade and drop.
- The contract issues `new_validator_config` and allows to recover validators with
Your configuration hashes.
- `validate-assertions` synchronizes the settings recorded when booting,
when changing the administrative configuration and de-coding a validator.
- `news-chain` exposes validators, listens to on-chain changes, recovers
IPFS configuration and publishes the relevant events in Kafka.
- `news-handler` maintains a cache of validators, updates it by
events and saves the applicable settings along with each validation.
- Added queries by hash, supplier and model, with recovery
optional validations and links to your orders.
- Gateway protects and routes new endpoints with the same security model
that the rest of the API.
- The frontend allows you to list validators, consult their settings and browse
from its validations to related orders.
- The shared Pydatic models were moved to the common module.
- The v2 assertion protocol was introduced for generation, validation, mode
Light and blockchain, with rich payloads, search context, domain selection, cache and RAG responses.
- The services of assertions, validation, chain and search for evidence
adopted the new form of payload and evidence metadata persist.

The versioned settings of a validator contain name, type, supplier, model, high and update dates, low date and status.

## v0.0.9.1 - Current consumption of quotes

- Fees are deducted when consuming the service.
- `news-handler` processes the received events and generates the assertions
  correspondientes.

## v0.0.9 - Limit Rate and User Management

- Key control and rate limitation were incorporated.
- Users have consumption limits for the generation of assertions and
  validaciones.
- An administrative module was added to manage new users.
- The Python tests were updated.
- Gateway automatically drifts and applies `client_id` to endpoints of
orders.
- The frontend restricts the visibility of the orders to the effective customer.

## v0.0.8 - Gateway, Keycloak and productive preparation

- They optimized and hardened the Dockerfiles.
- Keycloak's integrated.
- A unique Gateway was incorporated, with public APIs and integration with Keycloak.
- Nginx directs calls exclusively through the Gateway.
- Kafka works in KRaft mode, without ZooKeeper.
- Strict validation of the issuer, hostname and HTTPS was added.
- Volatile configuration moved to environment variables and were added
`.env` files without secrets.
- Automatic testing validates the creation and consultation calls of
  órdenes obteniendo previamente un token OAuth.
- Profiles and productive deployment configurations were prepared.
