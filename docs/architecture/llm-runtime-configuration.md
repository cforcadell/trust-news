# LLM Runtime Settings

LLM model configuration is managed from GUI only for users with the realm `trust-admin` role. Configurable components are `generate-asertions`, `source-router` and each registered instance of `validate-asertions`.

## Security and border

Administrative LLM configuration APIs require authentication by client certificate. Protection is permanent and consists of the following three layers:

```text
cliente con certificado mTLS
  -> Cloudflare (política administrativa permanente)
  -> /backend/admin/llm/* en Gateway
  -> JWT Keycloak válido (issuer, audience y cliente permitido)
  -> realm role trust-admin
  -> Admin API interna
```

The browser only calls Gateway. `Admin`, `generate-asertions`, `source-router` and workers are `ClusterIP` services; their internal `/admin/config` routes are not published by Ingress. The Gateway discards the identity headers provided by the browser and creates the audit identity from the validated JWT.

## Origin and precedence of configuration

| Almacenamiento | Contenido | Uso |
| --- | --- | --- |
| ConfigMap / environment | default provider, model and temperature | boot value |
| Kubernetes Secret / environment | API keys, private keys and other credentials | only source of secrets |
| MongoDB `config` | `desired`, `actual`, non-sensitive version, status and audit | override runtime persistente |
| Process Memory | effective configuration | immediate application without rebooting |

When starting, each service takes its default values from the environment and asks for the override `llm:*` to Admin. If Admin or Mongo are not available, it registers a warning and continues with the default values. ConfigMaps, Secrets are not modified and the Kubernetes API is not used.

Los PUT runtime solo admiten `provider`, `model` y `temperature` (la versión es asignada por Admin). Los schemas rechazan campos adicionales: no se aceptan ni se muestran `api_key`, `private_key`, tokens, passwords, ni secretos aunque estén enmascarados. Las respuestas solo exponen el booleano `credentials_configured` cuando resulta útil.

## Operation

The external route is `/backend/admin/llm/*` and the internal Admin routes are:

```text
GET/PUT /llm/components/generate-asertions
GET/PUT /llm/components/source-router
GET     /llm/validators?type=&strategy=
GET/PUT /llm/validators/{validator_id}
```

Admin persists first `desired` as `PENDING`, calls `GET/PUT /admin/config` as the service and compares the effective result. If it matches it passes to `APPLIED`; if it fails it retains the latest `actual` and marks `ERROR`. Each change leaves component or validator, provider/model previous and new version, user, date and result in `config.last_audit`.

Validators are dynamically discovered from the existing `news-handler` cache, backed by blockchain/IPFS. Its stable identifier is `ACCOUNT_ADDRESS` and its registered configuration provides the `service_url` used only by Admin within the cluster. The GUI never sends an internal URL. Before reading or modifying a worker, Admin re-discovers it and requires it to be active and accessible. The type is derived from the enum `ValidatorType` and returned as `{id, name}`; for RAG the evidence strategy is also returned.

Changing a validator reuses your `PUT /admin/config`: rebuilds the AI client and retains its IPFS configuration updates, blockchain and existing events. The change does not alter the type of validator or the evidence strategy.

## Trazabilidad

The assertion documents include provider, model and version. The router saves model and classification version in new profiles and paths. Supported validation responses incorporate provider, model and LLM version; the identity of the validator is already part of your contract.

## mTLS manual verification matrix

The Cloudflare rule must be tested from an external client, never from the local port-forward:

| Certificado cliente | JWT / rol | Expected outcome |
| --- | --- | --- |
| Ausente | Valid JWT `trust-admin` | Cloudflare rejects before Gateway |
| Valid | Absent or invalid | Gateway responde 401 |
| Valid | Valid JWT without `trust-admin` | Gateway responde 403 |
| Valid | Valid JWT with `trust-admin` | Gateway allows operation |

The exact Cloudflare policy and review procedure are in [`skaffold-server.md`](../deploy/skaffold-server.md#12-cloudflare).
