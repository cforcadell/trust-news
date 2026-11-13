# Releases

Este documento recoge las versiones desplegadas, sus límites conocidos y los siguientes hitos planificados. Una entrada planificada no acredita implementación ni despliegue. El roadmap completo está en [next_releases.md](next_releases.md).

## v0.0.13b — Plataforma de demos controladas

**Estado: en ejecución; NO-GO para abrir a clientes.** S00/S01 cerrados para preproducción con límites; S02/S03 aceptados localmente en kind, incluido el camino declarativo S03 confirmado por el operador; S07a tiene E2E técnico y funcional kind. Hetzner/K3s es preproducción, producción no existe y los perfiles `-prod` son nombres heredados. [Objetivo, estado y puertas](version.md) · [Inventario S00](security/s00-inventory.md) · [Auditoría contrastada](security/security_review_codex.md).

- Demos guiadas LIGHT/SMART, Blockchain OFF, mTLS general/administrativo y máximo dos organizaciones invitadas con identidad separada, datos desechables y vigencia limitada.
- S02/S03/S07a requieren integración y aceptación en Hetzner; S11-D y S12-D prueban borde, aislamiento, coste, baja y rollback sobre el mismo candidato. S01 exige revalidar preflight y aceptar sus riesgos residuales para la ventana.
- Hasta S05 no se permite a invitados iniciar trabajos con gasto; cada ejecución autorizada es supervisada por el operador. Si ese límite no puede imponerse, solo hay demos internas.
- El cierre habilita exclusivamente las demos descritas en [version.md](version.md#puertas-de-apertura-de-demos). No cierra v0.0.13, no retira mTLS, no acredita beta autónoma ni producción.

## v0.0.13c — Seguridad para acceso autónomo limitado

**Estado: planificada; sin aceptación de los paquetes diferidos.** Hito intermedio entre demos v0.0.13b y beta cerrada v0.0.14. Conserva motores compartidos y completa las barreras que las demos guiadas compensan operativamente:

- S04: segmentación declarativa default-deny con enforcement probado; S05: cuotas con reserva/consumo/liberación idempotentes y concurrencia; S06: estado/vigencia y revocación de organizaciones, usuarios y clientes; S07b: identidad, ACL y política de eventos Kafka.
- S08: copia cifrada externa y restauración aislada MongoDB/Keycloak, **antes** de S09: migración reproducible de MongoDB 4.4 a versión soportada con retorno ensayado. S10 completa caché, rotación y fallo acotado de JWKS sobre el verificador S03.
- S11/S12 completos: contrato de borde, aislamiento, gasto, bajas, mensajería, recuperación y regresión LIGHT/SMART sobre SHA/digests exactos. Los hallazgos P0 requieren contención inmediata; no esperan esta versión.
- **GO:** todos los P1 anteriores implementados y aceptados en Hetzner, con recuperación, operación y riesgos residuales documentados. Este GO acredita preparación para la puerta propia de v0.0.14; no abre acceso autónomo. La estimación histórica 178–314 h correspondía al alcance integral anterior y debe reestimarse para el trabajo restante.

## v0.0.14 — Beta cerrada por invitación

**Estado: planificada y condicionada a v0.0.13c y aceptación funcional aplicable.** Acceso autónomo de hasta dos clientes, retirada controlada del mTLS general con gate de rutas y mTLS administrativo conservados, revocación probada y aceptación propia. [Alcance y aceptación](next_releases.md#v0014---beta-closed-by-invitation). Esta entrada no autoriza abrir el acceso ni indica cambios aplicados al borde.

## v0.0.13 — Estabilización funcional

**Estado: desplegada en Hetzner (preproducción); validación funcional y aceptación pendientes.** El operador comunicó el despliegue y comprobaciones correctas de pods, rollouts, SMART y Blockchain OFF. El despliegue no acredita por sí solo aceptación ni una etiqueta de release. [Detalle y anexos](releases/v0.0.13.md) · [Incidencias](issues.md) · [Guía de despliegue](deploy/main-posttfm-hetzner-smart-light.md).

- Flujo LIGHT y contrato v2 de afirmaciones integrados con generación, validación, Kafka y persistencia; ruta BLOCKCHAIN por CID, IPFS y registro con estados de error y reintento.
- Consensus-v2 con votos, pesos, abstenciones, errores y motivos explícitos; citas RAG canónicas desde contextos entregados y elegibles.
- Source Router dinámico, taxonomía cerrada, route-v2, cachés versionadas y motor Evidence Search configurable DIRECT/PROVIDER/SMART, con extracción HTML/PDF y procedencia auditable.
- Aislamiento de consultas por propietario, comprobación de audiencia y cliente JWT, enlaces saneados; fechas UTC/ISO, estados terminales y resumen de órdenes parciales en GUI/API.
- Evaluación full --publish, corpus Official Gold v0 de once casos, visor, análisis offline, trazas de generación/ruta/recuperación, costes observados y regresión local estricta.
- Diagnóstico LIGHT: [SMART, 31-10](../tests/data/evaluation/artifacts/e2e-20261031-181209/report.md), 19/22 unidades e2e estrictas y 22 órdenes VALIDATED; [DIRECT, 01-11](../tests/data/evaluation/artifacts/e2e-20261101-101658/report.md), 12/22, 88/139 documentos extraídos y tres fallos de ejecución agrupados. Los manifiestos declaran árbol sucio y cambió la configuración observada de generación, por lo que no acreditan una comparación causal ni una release factual estable.
- El despliegue LIGHT utiliza SMART y mantiene Blockchain desactivado; DIRECT queda como campaña diagnóstica. Quedan pendientes la validación funcional por el borde de Hetzner, la resolución o aceptación formal de las incidencias P1, la homologación del gold y las demás comprobaciones de [aceptación](releases/v0.0.13.md#validación-y-aceptación-pendientes).

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
