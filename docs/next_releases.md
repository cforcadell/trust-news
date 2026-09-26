# Next versions

This document contains only versions after the current version. The status of the current version is in [`version.md`](version.md) and the versions published in [`releases.md`](releases.md).

## Summary

| Version | Objective | Main exit criterion |
| --- | --- | --- |
| v0.0.14 | Beta closed by invitation | Two external evaluations and one candidate for partner design |
| v0.0.15 | Pilot with design partners | A pilot with evidence of value and explicit decision of continuity |
| v0.0.16 | Production preparation | Hardening and recovery demonstrated; risks resolved or accepted |
| v0.9.0 | Release Candidate | Full regression and formal decision GO/NO-GO |
| v1.0.0 | Controlled production | Repeatable case, contractual commitment and accepted transaction |

## v0.0.14 - Beta closed by invitation

### Objective

Allow a maximum of ten external organizations to evaluate the platform for a defined period, with pseudonim identities and manually provided OIDC access. The controlled removal of the mTLS general temporary rule belongs to this version and is its first operating step, before opening external evaluations.

### Step 1: Remove temporary mTLS and keep the route gate

Before opening access to any customer:

1. Activate maintenance lock and keep rollback available.
2. Edit in the same slot `Temporary mTLS and public path gate - assermetry.com`.
3. Remove only the mTLS condition (`not cf.tls_client_auth.cert_verified`)
of the combined expression.
4. Keep namespaces lock condition not allowed and action
`Block` with `403` code.
5. Rename the rule to `Default deny - public path namespaces`.
6. Validate `/gui/`, `/backend`, `/auth` and unknown paths before opening
access.

The transition retains the same slot to avoid an unprotected window. The `default deny` of paths does not replace authentication, authorization, or the Gateway isolation and APIs.

### Scope

- An opaque identity per evaluator; no shared users are allowed nor are they
requires real name or personal mail.
- Keycloak retains only technical identifier, organization and roles
  imprescindibles.
- Logs and metrics do not include names, emails, tokens, credentials or data
  personales evitables.
- The mTLS rule general temporary is removed in a controlled window,
keeping active the lock, the administrative mTLS rule and a proven rollback.
- The interface is published under `/gui/`; Cloudflare redirects only `/`
and `/gui` to `/gui/` and blocks by default any path outside `/gui`, `/backend` and `/auth`.
- URL Normalization, Free Managed Rulet, rate limiting and closing of origin
Cloudflare's verified networks remain active: the path list does not replace them.
- The revocation cycle is validated with an administrative certificate
disposable and a proven backup certificate: the disposable exceeds mTLS before it is revoked and is later rejected without losing recovery access.
- Users access by OIDC without certificate; mTLS is reserved for the
administration.
- When API is enabled, each organization uses its own confidential client;
the secret of `TrustNewsApi` is not shared.
- Validate signature, issuer, validity, audience, client presenter and roles.
- The identity-organization association is immutable and resolves to serve-side.
- The isolation covers all resources, searches and exports.
- Fees are applied by organization, minimum audit, support and offboarding.
- Each evaluation has a guide, three tasks and structured collection of
  feedback.

### Limit and data

- Ten external organizations active simultaneously are allowed. Tenants
synthetics and internal identities do not consume that limit.
- No self-registration. Highs, roles and quotas are approved manually.
- High number eleven is locked and moved on to a waiting list.
- No credentials, personal, regulated or confidential data are entered
no need, authorisation and treatment agreed.
- Each evaluation defines final date, retention and cleaning.
- Synthetic or disposable data are not guaranteed recovery.
- A data to be kept requires minimal backup; an irreplaceable data requires
a proven restoration.

### Exit criterion

- One organization cannot read or infer resources from another, even if it manipulates
`client_id`, parameters or links.
- A client administrator cannot be elevated to a global administrator.
- Off users and incorrect or expired tokens lose access.
- The boundaries do not break legitimate login, refresh or chicken.
- The mTLS general rule is withdrawn and administration continues
protected by its permanent mTLS rule.
- Scanner paths such as `/wp-admin/`, `/.env` and random paths are blocked in
Cloudflare and they don't reach Hetzner.
- A revoked disposable administrative certificate is rejected and the
certificate of endorsement retains administrative access.
- The high number eleven is derived from the waiting list.
- Two external evaluations completed and one design candidate identified
partner with problem, metric and possible pilot.

## v0.0.15 - Pilot with design partners

### Objective

Validate for four to eight weeks one or two specialized cases of use, with scope, data, support and metrics agreed before development.

### Scope

- Use case and success criteria agreed before the pilot.
- Delimited data, export, elimination and weekly monitoring defined.
- Representative load tests, controlled restarts and degradation of a
  dependencia.
- Hardening of the IC channel, minimum privilege of Geth and reproducible artifacts
in the components concerned.
- Laterance measurement, cost per validation, perceived quality, repetition and
support load.

This hardening is limited to the components affected by the pilot. The cross-sectional closure of the pipeline, Geth, segmentation and supply chain remains at `v0.0.16`.

Disposable data can accept risk of loss. Data to be stored requires minimal backup before entering; irreplaceable data are not supported until a standalone restoration is demonstrated.

The reputation of validators and dedicated LLM is only incorporated if the pilot demonstrates its need. X/Threads remains in backlog until a specific flow or commercial channel is validated.

### Exit criterion

At least one pilot ends up with evidence of value and an explicit decision to continue, change the product or stop the use case.

## v0.0.16 - Production preparation

### Objective

Converting the validated platform with customers into a service that can be operated. It is a stabilization version and does not incorporate commercial functionalities except those necessary to close a production risk.

### Identity Hardening

- Review and harden `aud` validation implanted before beta.
- Keep `azp` or `client_id` validation by means of an explicit list
of clients presenters.
- Maintain signature validation, algorithm, issuer, expiration and validity.
- Separate user permissions and service account.
- Do not register unverified heads, tokens or claims.
- Remove duplicate implementations of administrative routes.
- Expand and maintain negative hearing evidence, presenter, issuer,
  expiración, firma y ausencia de token.

### Pipeline confidence

- Resolve [`ISSUE-003`](issues.md#issue-003---ci-no-autentica-el-api-de-k3s-con-su-ca):
authenticate the K3s API with your real CA and remove unsafe TLS jumps.
- Resolve [`ISSUE-004`](issues.md#issue-004---ci-no-fija-la-clave-ssh-del-servidor):
fix and verify the expected SSH key with `StrictHostKeyChecking=yes`.
- Make mandatory the security checks applicable to each profile.
- Prove that an incorrect CA, TLS name or SSH key fails before running
  despliegues.

### Geth and internal segmentation

- Remove `admin`, `personal`, remote unlocking and CORS wildcards
and virtual hosts of the PRC.
- Only publish modules and methods consumed by the application.
- Keep RPC as `ClusterIP`, no Ingress or NodePort.
- Check that the CNI applies `NetworkPolicy`.
- Implement progressive `default-deny` with minimal allowables, including DNS.
- Aislar Geth, MongoDB, PostgreSQL, Kafka, IPFS, panels and services
  administrativos.
- Prove that an unauthorized pod cannot reach sensitive services.

### Supply chain and capacity

- Remove `latest`, floating references and images without version.
- Fix images and dependencies by digest; display constructed digests
for the pipeline.
- Generate inventory or SBOM, run scanning and add controls to render
  productivo.
- Complete `requests` and `limits`, measure rolls and set alerts for
memory, disk and node pressure.
- Define SLO, RTO and RPO.
- Explicitly decide whether to accept the single node as SPOF or adopt
multinode infrastructure; a replica in a node is not presented as HA.
- Resolve or expressly accept `DNSConfigForming`.

### Backups, restoration and operation

- Create external MongoDB and PostgreSQL encryption backups from Keycloak.
- Support genesis, keystores, Ethereum credentials, contract, ABI,
categories, Kubernet secrets, CI/CD variables, API keys and OIDC secrets.
- Check hash, date, size, encryption and readability outside the cluster.
- Restore MongoDB and Keycloak in an isolated destination and check login and
  recuentos.
- Check the address and bytecode of the contract against the baseline.
- Rehearsing application rollback, manifests, configuration, images and data.
- Run load, soak, bugs and recovery.
- Prepare incident runbooks, credentials, certificates, support and casualties.
- Review privacy, retention and conditions of service.

A destructive restoration of active PVCs is never tested. The result requires evidence of restoration, not just the existence of backup files.

### Cloudflare Tunnel opcional

The HTTPS inbound can be replaced by a Named Tunnel initiated from the cluster, only if an explicit analysis justifies the change. It is not part of the current version and is estimated at 12 to 18 technical hours.

Minimum conditions:

- `cloudflared` as a restricted workload, with external credentials, tests,
limits, two replicas and `--no-autoupdate`.
- Traefik remains the only router for `/gui`, `/backend` and `/auth`.
- The `cloudflared -> Traefik` jump validates the Origin CA and
`originServerName=assermetry.com`; no `noTLSVerify` is used.
- `forwardedHeaders.insecure` remains disabled and only the
defined internal origins.
- The lock and administrative mTLS remain active during the change.
- The inbound `443` does not withdraw until the end-to-end tests are completed.
And prepare the rollback.
- After the observation period, Traefik passes to `ClusterIP` and there is no
alternative route via LoadBalancer, NodePort, hostPort, public IP or historical DNS.
- Real IP validation, rate limits, log, connector loss, smoke tests and
  rollback completo.
- The local profile does not depend on `cloudflared`.

Expected result: the domain works exclusively by tunnel, Hetzner does not support inbound web ports and WAF, OIDC, mTLS administrative, limits and observability are retained. The option does not provide high host availability as long as the cluster remains in a single node.

### Exit criterion

- All flows apply strict identity and authorization.
- CI authenticates SSH and Kubernetes and does not allow omitting controls.
- Geth no expone APIs administrativas ni desbloqueo inseguro.
- NetworkPolicy limits lateral movement.
- Production uses immutable and inventoryable artifacts.
- Capacity and availability have evidence and risk decision.
- External encrypted backups and isolated restoration are proven.
- Rollback, charging, soak, faults and recovery are proven.
- The remaining risks are formally resolved or accepted.

Any non-compliance maintains the NO-GO state and blocks `v0.9.0`.

## v0.9.0 - Release Candidate

- Functional freezing.
- Full deployment, migration and rollback test.
- Repeated, isolated and timed restoration.
- Integral functional regression.
- Negative security, charge and soak tests.
- Review of observability, support and operating procedures.
- GO/NO-GO formal with registered responsible and exceptions.

Any critical failure produces NO-GO and requires a new candidate release.

## v1.0.0 - Controlled production

Production does not require self-registration or anonymous access. The service can continue to be invited only by OIDC and with mTLS exclusively administrative.

The version receives GO when:

- Two specialized organizations have completed an evaluation or pilot.
- At least one maintains a contractual production commitment.
- There is a case of repeatable use and a sustainable economic proposal.
- Backup, restoration, security, capacity and support are accepted.
- Responsible, timetables, scaling and service boundaries are known.
- The opening or closing rollback is tested.

WAF, administrative mTLS, rate limits, logs and alerts remain active. The lock rule remains available and its activation is proven.

## Secuencia transversal

1. Internal demo with synthetic data and operator present.
2. External demo guided with temporary IODC identity and, as long as the
temporary protection of the current version, temporary customer certificate.
3. Closed evaluation with persistent credentials and final date.
4. Pilot with scope, metrics and agreed support.
5. Release Candidate without new features.
6. Controlled production for contracted customers.

Before each demo or evaluation changes are frozen for 24 to 48 hours, the lock is activated to deploy, preflight, regression and smoke are executed and only the authorized window opens. At the end of the access, temporary credentials are revoked and the expected data is cleaned.

Material needed: one-pager, short presentation, demo script, evaluation guide, explanation of the guarantees and limits of Assermetry, safety and data sheet, FAQ, known limitations and pilot proposal.

The planned commercial process is:

```text
descubrimiento -> demo guiada -> evaluación -> design partner -> piloto -> producción
```

Time to first useful validation, task completion, perceived utility, repetition, cost and latency by validation, support load and interstage conversion shall be measured.

## Invariantes

- Do not rename the current `TrustNews` or existing OIDC customers.
- Do not publish databases, Kafka, IPFS API, RPC, panels or APIs
  administrativas.
- Do not add `www.assermetry.com` without proven canonical redirection.
- Do not use this roadmap as a substitute for operating runbooks.
- Not to claim that blockchain guarantees the truth; the message focuses on
traceability, evidence, diversity of validators and auditability.
