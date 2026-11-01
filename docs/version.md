# v0.0.13 — Estabilización funcional

**Estado: alcance de desarrollo cerrado; release en Deploying (1 de noviembre de 2026).** Este documento fija lo incorporado y los límites conocidos. Deploying no significa publicada, aceptada en Hetzner ni acreditada como verificador factual. [issues.md](issues.md) conserva las incidencias y sus criterios de cierre; [la guía de despliegue](deploy/main-posttfm-hetzner-smart-light.md) describe la promoción.

## Qué se ha incorporado

| Área | Resultado incluido | Evidencia y límite |
| --- | --- | --- |
| Órdenes LIGHT y BLOCKCHAIN | Contrato v2 de afirmaciones a través de generación, Kafka, validadores, persistencia e IPFS; registro BLOCKCHAIN por CID; estados de error y reintento explícitos. | Pruebas locales y una orden BLOCKCHAIN con CID, post y transacción. Falta repetir la ruta en destino (023). |
| Validación y decisión | Consensus-v2 distingue votos, abstenciones y errores, conserva pesos y motivo; las citas RAG se reconstruyen desde context_id entregados y elegibles. | Pruebas locales y campañas LIGHT. Una cita válida acredita identidad, no apoyo semántico ni independencia (007, 008, 013, 017). |
| Búsqueda y documentos | Source Router dinámico, routing-taxonomy-v1, route-v2, cachés versionadas y Evidence Search con adquisición configurable DIRECT, PROVIDER o SMART, extracción HTML/PDF, procedencia y diagnósticos. La URL de origen y metadatos de ruta llegan a la recuperación. | Continúan fallos de fuentes oficiales, clasificación de copias y validación de ruta/caché en Hetzner (015, 021, 022). |
| Identidad, API y GUI | Aislamiento por propietario, comprobación de audiencia y cliente JWT, saneamiento de enlaces; fechas UTC/ISO, estados terminales y resumen de órdenes parciales. | Pruebas locales y parte desplegada históricamente; faltan matrices de dos identidades, tokens negativos y navegador en destino (005, 006, 011, 012, 014, 018, 019). |
| Evaluación y operación | Once casos activos de Official Gold v0, runner full --publish, artefactos versionados, análisis offline, visor, trazas y costes observados, regresión local y diagnóstico de navegador. | Infraestructura de medida implementada; gold aún sin homologación humana independiente (016, 017). |

Estas implementaciones son **motores y contratos configurables**; la release no introduce reglas especiales para una noticia, dominio, país o campaña.

## Campañas que delimitan el estado

La unidad e2e estricta es caso × repetición. Las dos campañas recientes usaron los mismos once hashes del gold, dos repeticiones y el mismo hash de prompt. Sus manifiestos declaran el commit da356fdf y árbol sucio. La generación observada cambió de temperatura 0,0 a 0,1 y de config_version 30 a 0: la comparación no aísla el efecto del modo de extracción.

| Campaña LIGHT | Modo observado | Órdenes | Decisión correcta | E2e estricto | Recuperación documental |
| --- | --- | --- | --- | --- | --- |
| [31-10-2026, 181209](../tests/data/evaluation/artifacts/e2e-20261031-181209/report.md) | SMART | 22 VALIDATED | 21/22 | 19/22 | 126 documentos citables desde texto de búsqueda; cero descargas HTTP. La tasa de descarga no es medible. |
| [01-11-2026, 101658](../tests/data/evaluation/artifacts/e2e-20261101-101658/report.md) | DIRECT | 19 VALIDATED, 2 VALIDATED_WITH_ERRORS, 1 DOCUMENT_CREATED | 16/22; 1 no evaluable | 12/22 | 88/139 documentos extraídos (63,3 %); 115/222 respuestas HTTP 2xx (51,8 %), incluidas 27 respuestas 202 sin texto. |

En SMART fallaron estrictamente un consenso UNKNOWN y dos categorías frente al gold. En DIRECT hubo cinco decisiones no conformes, una no evaluable, tres categorías divergentes y un error técnico adicional con decisión correcta. Dos fallos de Source Router y un timeout de sondeo quedaron agrupados como fallos de ejecución. EUR-Lex devolvió 27 respuestas 202 sin texto; también hubo denegaciones y fallos de acceso a otras fuentes. La segunda campaña **no acredita mejora de calidad ni estabilidad de DIRECT**.

## Configuración que se va a desplegar

El commit da356fdf y el ConfigMap actual fijan SMART como modo previsto del despliegue LIGHT de v0.0.13. DIRECT se probó en la campaña diagnóstica del 01-11, pero no es el valor configurado para la promoción actual. Hay que congelar una revisión limpia y comprobar SMART en cada pod; actualizar un ConfigMap no cambia las variables de procesos ya iniciados. [La guía de Hetzner](deploy/main-posttfm-hetzner-smart-light.md) incluye esa puerta. BLOCKCHAIN permanece desactivado por defecto en el despliegue LIGHT; la ruta BLOCKCHAIN implementada no se elimina.

## Puerta de salida de Deploying

- Congelar SHA, imágenes, SMART, modelos, temperatura, hashes del gold y configuración efectiva; verificarlos en pods y artefactos de una campaña nueva. Un cambio posterior a DIRECT exige otra revisión y validación.
- Ejecutar la regresión local y validar por el borde real de Hetzner: login, JWT, dos identidades, enlaces, errores, navegador ES/EN, móvil, LIGHT y la comprobación BLOCKCHAIN requerida. Conservar pruebas de despliegue y reversión.
- Resolver o aceptar formalmente los riesgos P1 aplicables; investigar fallos de Router, extracción, categorías y timeout; repetir casos y lote completo con configuración comparable.
- Homologar el gold, fijar umbrales previos a la aceptación, incluir abstención UNKNOWN y revisar fuentes primarias, independencia y apoyo semántico. VALIDATED y la elegibilidad de una cita no son certificación factual.
- Aplicar los criterios específicos de [issues.md](issues.md) antes de marcar una incidencia como resuelta. Solo entonces decidir publicación y etiqueta.

## Anexo A — Fuera del alcance incorporado

| Trabajo | Destino o tratamiento | Límite de esta release |
| --- | --- | --- |
| Revisión humana obligatoria antes de validar y reporte reutilizable (009, 010) | v0.0.14 | La GUI ofrece edición y pestañas de evidencia, pero no ese recorrido completo. |
| Retirada controlada del mTLS general, invitaciones externas y revocación probada de certificado administrativo | v0.0.14 | Se conserva la protección temporal y el mTLS administrativo. |
| CA de K3s y clave SSH del servidor en CI (003, 004) | v0.0.16 propuesto | El aplazamiento exige responsable, mitigación, alcance de demo y decisión de riesgo. |
| Piloto, recuperación productiva, pruebas de carga y compromiso comercial | v0.0.15 y posteriores | No se deducen de las campañas locales. |
| Generación de aserciones en dos etapas | [working.md](working.md), propuesta del 29-10-2026 | No está implementada ni ejecutada; depende de ensayo emparejado. No es puerta de v0.0.13. |
| X/Threads, nueva reputación, LLM dedicado y Cloudflare Tunnel | Evolución posterior | No forman parte de esta release. |

## Anexo B — Implementado, pero sin aceptación demostrada

Siguen abiertos la calidad factual, recuperación de fuentes primarias y clasificación de copias (017, 021); validación de taxonomía/ruta/caché en Hetzner (015, 022); pruebas completas GUI/API/BLOCKCHAIN en destino (001, 005–008, 011–016, 018–020, 023, 025); y retirada y revisión segura de la credencial local de 024. Este anexo registra **verificación o corrección pendiente**, no funcionalidades añadidas por declaración. El inventario y condiciones de cierre están en [issues.md](issues.md).
