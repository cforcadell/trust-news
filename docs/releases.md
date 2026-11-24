# Releases

Este documento distingue versiones desplegadas, desarrollo local y siguientes hitos. Una entrada planificada o sin commit no acredita implementación en Hetzner/K3s. La ficha actual es [v0.0.13c](version.md) y el roadmap está en [next_releases.md](next_releases.md).

## v0.0.13b — Plataforma de demos controladas

**Estado: trabajo de software registrado en `postTFM`; NO-GO para abrir a clientes.** `d8b97af` documentó la release v0.0.13b, pero no existe una etiqueta local `v0.0.13b` ni promoción comprobada a `main`. La evidencia del pipeline `#3070111046` y de salud K3s corresponde a `722c1d57`, no al commit documental posterior. S02/S03/S07a, S11-D y S12-D no tienen aceptación integral sobre un candidato exacto en Hetzner. Hetzner/K3s es preproducción; producción no existe. [Alcance y puertas archivados](releases/v0.0.13b.md) · [Ficha del candidato](deploy/candidate-v0.0.13b-k3s.md).

- Demos guiadas LIGHT/SMART, Blockchain OFF, mTLS general/administrativo y máximo dos organizaciones invitadas con identidad separada, datos desechables y vigencia limitada.
- S02/S03/S07a requieren verificar su integración efectiva y completar la aceptación en Hetzner; S11-D y S12-D prueban borde, aislamiento, coste, baja y rollback sobre el mismo candidato. S01 exige vincular los preflights al SHA desplegado y aceptar sus riesgos residuales para la ventana.
- Hasta S05 no se permite a invitados iniciar trabajos con gasto; cada ejecución autorizada es supervisada por el operador. Si ese límite no puede imponerse, solo hay demos internas.
- El cierre habilita exclusivamente las demos descritas en [la ficha v0.0.13b](releases/v0.0.13b.md#puertas-de-apertura-de-demos). No cierra v0.0.13, no retira mTLS, no acredita beta autónoma ni producción.

### Etiquetado pendiente de v0.0.13b

No hay etiqueta local ni promoción comprobada a ambas ramas `main`. Antes de etiquetar, fijar el candidato aprobado, contrastar su contenido con la evidencia efectiva de Hetzner/K3s y completar las puertas de demos. Seguir el [procedimiento general de release](deploy/gitlab-github-release-workflow.md#6-release) con autorización explícita. Esta actualización documental no crea ni publica etiquetas.

## v0.0.13c — Generación y cierre de órdenes

**Estado: versión actual en desarrollo local; sin commit final, tag, promoción ni despliegue acreditado.** Se basa en los cinco commits del rango `d8b97af..d693c25` posteriores al trabajo de v0.0.13b y añade el cierre por plazo aún sin commit. La comparación local `origin/main..postTFM` contiene 35 commits en total: 30 hasta `d8b97af` son la base v0.0.13b y cinco son el incremento de v0.0.13c. [Inventario por commit, cambios locales y aceptación](version.md).

- Generate Assertions: pruebas de estrategias y prompts, prompt versionado que separa hechos, timeout HTTP/GUI de 120 segundos y documentación de diseños. Las pruebas aisladas no acreditan mejora de calidad o rapidez en producción.
- GUI: muestra el tiempo de generación y propaga `source_url` al publicar una noticia importada.
- Desarrollo local pendiente de commit: plazo configurable de orden, cierre `VALIDATED_AUTOMATICALLY`, respuestas tardías auditadas y resultado parcial en GUI. [Diseño](architecture/designs/order-validation-deadline-design-2026-11-21.md). La migración de órdenes antiguas no se ha ejecutado.
- **GO/NO-GO:** requiere candidato de un solo SHA, preflights y verificación efectiva en Hetzner/K3s; mantiene NO-GO para clientes mientras sigan abiertas las puertas de demos v0.0.13b. No habilita acceso autónomo.

## v0.0.13d — Seguridad para acceso autónomo limitado

**Estado: planificada; es el alcance antes asignado a v0.0.13c y sus paquetes siguen sin aceptación.** Hito entre v0.0.13c y beta cerrada v0.0.14. Conserva motores compartidos y completa las barreras que las demos guiadas compensan operativamente:

- S04: segmentación declarativa default-deny con enforcement probado; S05: cuotas con reserva/consumo/liberación idempotentes y concurrencia; S06: estado/vigencia y revocación de organizaciones, usuarios y clientes; S07b: identidad, ACL y política de eventos Kafka.
- S08: copia cifrada externa y restauración aislada MongoDB/Keycloak, **antes** de S09: migración reproducible de MongoDB 4.4 a versión soportada con retorno ensayado. S10 completa caché, rotación y fallo acotado de JWKS sobre el verificador S03.
- S11/S12 completos: contrato de borde, aislamiento, gasto, bajas, mensajería, recuperación y regresión LIGHT/SMART sobre SHA/digests exactos. Los hallazgos P0 requieren contención inmediata; no esperan esta versión.
- OAuth para integraciones API: [diseño](architecture/designs/oauth-api-integrations-design.md) e [implementación local](security/s03-api-integrations.md) de clientes nuevos por integración, asociación S03, cuota y ciclo de vida. `TrustNewsApi` queda destinado a retirada; `TrustNewsWeb` y el login GUI permanecen fuera del cambio. Activación, despliegue y aceptación pendientes.
- **GO:** todos los P1 anteriores implementados y aceptados en Hetzner, con recuperación, operación y riesgos residuales documentados. Este GO acredita preparación para la puerta propia de v0.0.14; no abre acceso autónomo. La estimación histórica 178–314 h correspondía al alcance integral anterior y debe reestimarse para el trabajo restante.

## v0.0.14 — Beta cerrada por invitación

**Estado: planificada y condicionada a v0.0.13d y aceptación funcional aplicable.** Acceso autónomo de hasta dos clientes, retirada controlada del mTLS general con gate de rutas y mTLS administrativo conservados, revocación probada y aceptación propia. [Alcance y aceptación](next_releases.md#v0014---beta-closed-by-invitation). Esta entrada no autoriza abrir el acceso ni indica cambios aplicados al borde.

## v0.0.13 — Estabilización funcional

**Estado: desplegada en Hetzner (preproducción); validación funcional y aceptación pendientes.** El operador comunicó el despliegue y comprobaciones correctas de pods, rollouts, SMART y Blockchain OFF. El despliegue no acredita por sí solo aceptación ni una etiqueta de release. [Detalle y anexos](releases/v0.0.13.md) · [Incidencias](issues.md) · [Guía histórica de despliegue](deprecated/deploy/main-posttfm-hetzner-smart-light.md) · [Runbook actual](deploy/skaffold-server.md).

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
