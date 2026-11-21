# Documentación de Assermetry

La referencia para el alcance, estado y puertas de la versión en curso es
[version.md](version.md). Hetzner/K3s es preproducción; los nombres técnicos
`-prod` de perfiles y overlays no acreditan producción. Las pruebas en kind no
acreditan el mismo resultado en Hetzner.

## Guías vigentes

- **Estado y planificación:** [versión actual](version.md),
  [roadmap](next_releases.md), [historial de releases](releases.md),
  [incidencias funcionales](issues.md) y [bitácora operativa](../working.md).
- **Despliegue:** [kind local](deploy/skaffold-local.md),
  [Hetzner/K3s](deploy/skaffold-server.md), [procedimientos comunes](deploy/k8s-common.md),
  [Secrets de Hetzner](deploy/secrets-hetzner.md),
  [ficha del candidato](deploy/candidate-v0.0.13b-k3s.md) y
  [flujo GitLab/GitHub](deploy/gitlab-github-release-workflow.md).
- **Seguridad:** [inventario S00](security/s00-inventory.md),
  [diseño S02](architecture/designs/s02-design.md), [diseño S03](architecture/designs/s03-design.md),
  [S03 en Skaffold](security/s03-skaffold.md),
  [migración de propietarios](security/s03-owner-migration.md),
  [alta GUI y cuotas](security/s03-gui-user-provisioning.md) y
  [Kafka TLS S07a](security/s07a-kafka-tls.md).
- **Pruebas:** [catálogo y selección de suites](tests/tests.md),
  [E2E de navegador](../tests/frontend/e2e/README.md),
  [evaluación](tests/evaluation.md), [benchmark LLM](tests/llm-benchmark.md)
  y [contrato del visor](tests/benchmark-viewer-contract.md).
- **Arquitectura:** [visión general](architecture/TrustNews_detailed.md),
  [APIs](architecture/apis/), [proveedores comunes](architecture/common-providers.md),
  [mensajería Kafka](architecture/kafka-messaging-and-use-cases.md),
  [validadores](architecture/validator-summary.md) y
  [configuración LLM](architecture/llm-runtime-configuration.md).

Los inventarios JSON de `security/` también son entradas de scripts y no deben
tratarse como documentos archivables: `s03-local-services.json`,
`s03-keycloak-clients.json` y `s03-owner-migration.json`.

## Evidencia y documentos históricos

Los informes fechados, auditorías, planes y bitácoras de `architecture/`,
`tests/`, `security/`, `deploy/` y `releases/` conservan conclusiones de su
fecha, no una prueba del estado efectivo actual. Consultar la versión y el
entorno de cada resultado. En particular, el plan del motor de evidencias y el
plan del visor contienen decisiones y evolución; sus contratos de API y de
visor son las referencias de uso.

Algunos informes enlazan a `tests/data/*/artifacts/`: esas salidas son locales
y están excluidas de Git, por lo que los enlaces pueden no existir en otro
checkout. El texto del informe no sustituye la conservación verificable de los
artefactos originales.

Los procedimientos sustituidos se conservan en [deprecated/](deprecated/README.md)
para consulta histórica; no ejecutar sus comandos. Al cambiar una ruta, revisar
referencias en el repositorio y en automatizaciones antes de retirarla.
