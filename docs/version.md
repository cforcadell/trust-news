# v0.0.13c — Generación y cierre de órdenes

**Estado al 21-11-2026: código de v0.0.13c registrado en `postTFM` mediante `43ef06367fff60e92d1221eb7772b4c42c85d6af`; sin etiqueta, promoción a `main` ni despliegue acreditado. NO-GO para abrir a clientes.** La rama local `postTFM` y la referencia local `origin/postTFM` apuntan a ese commit; esto no verifica por sí solo el remoto en vivo. Las referencias locales `origin/main` y `gitlab/main` no contienen los cambios de `postTFM`; no se ha consultado el remoto en vivo para esta ficha. La última evidencia de despliegue Hetzner/K3s documentada para v0.0.13b corresponde a `722c1d57`, no a este commit. Las pruebas locales citadas abajo no acreditan K3s.

El [registro de v0.0.13b](releases/v0.0.13b.md) conserva el alcance de demos controladas y sus puertas pendientes. Esta versión incorpora el trabajo posterior de `postTFM` y el cierre de validaciones por plazo incluido en `43ef063`. El alcance que antes figuraba como v0.0.13c (S04, S05, S06, S07b, S08→S09, S10, OAuth autónomo y S11/S12 completos) pasa a [v0.0.13d](releases.md#v0013d--seguridad-para-acceso-autónomo-limitado).

## Base de Git y contenido

La comparación de referencias locales muestra **36 commits en `postTFM` que no están en `origin/main`**. Los primeros 30 llegan hasta `d8b97af` (`release v0.013b`) y pertenecen al trabajo de v0.0.13b. El incremento de v0.0.13c son los seis commits posteriores, en orden. Ninguno de estos commits constituye una etiqueta de release.

| Commit posterior a v0.0.13b | Contenido verificable en el diff |
| --- | --- |
| `9cb6746` | Diseños y experimentos de estrategias de Generate Assertions, corpus sintético y motor de sondeo compacto. Los resultados aislados no prueban una mejora de calidad o latencia para producción. |
| `edef6b8` | Timeout HTTP de Generate Assertions y tiempo de espera de la GUI elevados a 120 segundos; ConfigMap y contrato de API actualizados. |
| `7e021a3` | Diseños movidos a `docs/architecture/designs/`, enlaces adaptados y diseño de streaming incorporado. |
| `e9bfa5f` | Prompt versionado de Generate Assertions ajustado para separar hechos independientes. Requiere evaluación de calidad con casos representativos. |
| `d693c25` | GUI: duración visible de generación, propagación de `source_url` en la publicación y diseño de cierre por plazo. |
| `43ef063` | Implementación del cierre de órdenes por plazo, pruebas y documentación de v0.0.13c/v0.0.13d. |

**Incluido en `43ef063`:** `ORDER_VALIDATION_DEADLINE_MINUTES` en Gateway (30 minutos por defecto, rango `0..1440`; `0` desactiva el plazo para órdenes nuevas), plazo persistido al entrar en `VALIDATION_PENDING`, reconciliador en News Handler, transición condicional de respuestas LIGHT/BLOCKCHAIN, estado terminal `VALIDATED_AUTOMATICALLY`, auditoría de cierres y respuestas tardías, resultado parcial traducido en la GUI y seguimiento hasta el plazo de la orden. [Diseño y límites](architecture/designs/order-validation-deadline-design-2026-11-21.md). Las órdenes antiguas sin plazo no vencen automáticamente; [el backfill](../scripts/operations/backfill_validation_deadlines.py) ofrece vista previa y aplicación explícita, pero no se ha ejecutado.

No se incorporan timeouts individuales a los validadores. El cierre no cancela trabajos ya enviados; una respuesta tardía no altera el resultado final ni cobra cuota de validación. Las validaciones ausentes se cuentan aparte, sin inventar votos ni resultados `ERROR`.

El [diseño de OAuth para integraciones API](architecture/designs/oauth-api-integrations-design.md) tiene [implementación local](security/s03-api-integrations.md) en este árbol de trabajo para el alcance planificado de v0.0.13d. Solo admite altas nuevas y deja `TrustNewsApi` para retirada; `S03_INTEGRATIONS_ENABLED=false` mantiene el acceso deshabilitado. No se ha desplegado ni aceptado. El login OpenID Connect de la GUI con `TrustNewsWeb` queda fuera de ese cambio.

## Evidencia y límites

- Las pruebas locales del cierre y la GUI pasaron: 26 pruebas Python en `test_order_validation_deadline.py` y `test_news_handler_document_shape.py`, las suites JS `pending-navigation.test.js` y `consensus-ui.test.js`, compilación Python y `git diff --check`. Cubren órdenes antiguas sin plazo, fechas UTC devueltas por MongoDB, cierre, respuesta tardía y seguimiento de la GUI. No constituyen una prueba E2E en K3s ni una migración de datos.
- El timeout de 120 segundos se aplica a la ruta configurada de Generate Assertions; los overrides de proveedor, `LLM_TIMEOUT` y el proxy deben verificarse en el entorno efectivo antes de atribuir una mejora de latencia. Los experimentos de prompts y estrategias siguen siendo evidencia exploratoria.
- v0.0.13b conserva el límite de demos guiadas LIGHT/SMART, Blockchain OFF, mTLS y máximo dos organizaciones, con gasto supervisado. La apertura externa sigue **NO-GO** hasta completar las puertas S02/S03/S07a, S11-D/S12-D y la decisión explícita sobre el SHA y configuración realmente desplegados. Ningún resultado local de v0.0.13c sustituye esa aceptación.

## Puerta de candidato y siguiente versión

Antes de proponer release o despliegue de v0.0.13c: revisar el commit `43ef063` y cualquier cambio posterior, aprobar un SHA candidato, ejecutar preflights en ese mismo SHA, verificar render y configuración efectivos, imágenes/digests y comportamiento LIGHT/SMART en Hetzner/K3s, probar el cierre por plazo y la respuesta tardía sobre datos desechables, y registrar la decisión GO/NO-GO. Esta ficha no acredita pipeline ni despliegue.

[v0.0.13d](releases.md#v0013d--seguridad-para-acceso-autónomo-limitado) conserva los P1 diferidos antes de la beta cerrada v0.0.14. La v0.0.13c no habilita OAuth autónomo, retirada de mTLS, beta ni producción.
