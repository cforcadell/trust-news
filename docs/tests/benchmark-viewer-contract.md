# Contrato de órdenes para el visor (`order-diagnostic-v1`)

Este contrato define **un diagnóstico por orden y repetición guardadas**. El visor lee el diagnóstico como índice de navegación y usa los artefactos originales para abrir datos completos. No se aplica a ejecuciones directas sin `order_id`, ni transforma campañas antiguas.

Archivos de la fase 0:

- Esquema: `tests/evaluation/viewer/order-diagnostic-v1.schema.json`.
- Validación de identidades y referencias: `tests/evaluation/viewer_contract.py`.
- Muestra autocontenida: `tests/evaluation/viewer/fixtures/order-diagnostic-v1.json`.

Las ejecuciones `--publish` y las importaciones `--order` publican `<parent_run_id>-viewer.json` junto a `<parent_run_id>-order.json` y los `<run_id>.json` existentes. La ruta se resolverá **dentro de la carpeta de campaña**; `artifact_refs` contiene rutas relativas a esa carpeta. El builder `tests/evaluation/viewer/build.py` escribe el JSON mediante la utilidad atómica de artefactos. La fixture ilustra el contrato: sus rutas relativas son ejemplos y no corresponden a archivos de orden reales.

## Identidad y cardinalidad

`identity` incluye `campaign_id`, `dataset_id`, `order_id` y `repetition` (desde 1). `parent_run_id` es opcional: existe en el flujo `--publish`, pero puede faltar al importar una orden local. `artifact_refs.order` señala la orden original y `artifact_refs.results` empareja cada `run_id` con su archivo de resultado.

`order.generation` aparece **una vez por orden**. `order.assertions[]` contiene todas las afirmaciones generadas, incluidas las que no casan con el dataset. `validations[]` contiene una entrada por (`assertion_id`, `validator_id`), con `run_id` único; cada `run_id` debe figurar exactamente una vez en `artifact_refs.results`. Una afirmación sin validador sigue en `order.assertions[]` sin entrada en `validations[]`. Si la orden falla antes de generar afirmaciones, ambas listas pueden estar vacías y `order.generation` explica el fallo.

Los `source_id`, `chunk_id` y `context_id` viven **dentro de una validación**. Es válido que dos validaciones tengan `source-1`; no representan necesariamente la misma URL. Una cita se resuelve únicamente contra los contextos entregados en la misma validación. `checks[].observation_refs` usa punteros JSON absolutos al diagnóstico y sirve para saltar del hallazgo a la observación.

## Etapas y estados

Cada etapa tiene `execution_status`, `assessment`, `observations` y `checks`:

| Campo | Valores | Significado |
| --- | --- | --- |
| `execution_status` | `COMPLETED`, `FAILED`, `SKIPPED`, `NOT_RECORDED` | Qué ocurrió en la ejecución. Una lectura de caché puede estar `COMPLETED` aunque no se hiciera búsqueda nueva. |
| `assessment` | `PASS`, `FAIL`, `PARTIAL`, `NOT_EVALUATED`, `SKIPPED` | Resultado de las comprobaciones disponibles. Controla el color del nodo. |
| `missing_reason` | Texto obligatorio para `NOT_EVALUATED` y `SKIPPED` | Explica por qué no hay juicio o por qué se omitió la etapa. |
| `observations` | Objeto | Datos realmente recogidos; su estructura depende de la etapa y puede crecer sin cambiar esta versión. |
| `checks` | Lista de `{code,status,detail,observation_refs?}` | Juicios automáticos con fundamento en observaciones. Pueden coexistir comprobaciones superadas y fallidas. |

`NOT_RECORDED` indica una laguna de captura. `SKIPPED` indica una etapa que deliberadamente no se ejecutó. `NOT_EVALUATED` permite mostrar observaciones sin afirmar su corrección. La falta de `acceptable_domains` deja la calidad del Router en `NOT_EVALUATED`, aunque se conozcan los dominios. Citar un par válido (`source_id`, `context_id`) prueba identidad y elegibilidad; la pertinencia o apoyo semántico exige referencias revisadas o anotación humana.

Las etapas de cada validación son `router`, `evidence_search`, `handoff`, `llm`, `citations` y `consensus`. Sus observaciones podrán incluir:

| Etapa | Observaciones previstas |
| --- | --- |
| Generate Assertions (`order.generation`) | Configuración, intentos/reparación, afirmaciones esperadas/generadas y emparejamiento. |
| Router | Estado de ruta/caché, consultas de descubrimiento, URLs, candidatos, clasificaciones, descartes y desglose de puntuación. |
| Evidence Search | Plan y consultas realmente ejecutadas, filtros, URLs, descargas, chunks completos, puntuación desglosada y contextos. |
| Handoff | Hash recuperado y hash de entrada del validador. |
| LLM | Configuración, tiempos, error resumido, veredicto original y efectivo. |
| Citations | Pares citados, contexto entregado, elegibilidad y motivo del rechazo. |
| Consensus | Votos, pesos, abstenciones, errores, veredicto y código de decisión. |

En una ruta `FRESH` se presenta la decisión cacheada y se marca que la consulta de descubrimiento **no se ejecutó en esa orden**. Lo mismo vale para Evidence Search con `cached=true`: la consulta del plan puede mostrarse, pero `executed=false`. Una URL o chunk descartado se registra con motivo; el texto de todos los chunks queda en la traza de evaluación, incluso si no se seleccionó.

## Observaciones, juicios y anotaciones

`observations` conserva lo visto; `checks` contiene conclusiones automáticas. No se escriben evaluaciones humanas en el artefacto original. Si se aprueban las anotaciones manuales, vivirán en un archivo lateral versionado, referido a `order_id`, `run_id` y un puntero JSON. Ese formato se decidirá en la fase 6.

Los artefactos de evaluación pueden contener texto de noticias y chunks. El visor los muestra como texto, nunca como HTML ejecutable. La captura detallada se activa solo en evaluación; el esquema no requiere prompts completos, respuestas crudas del proveedor ni credenciales. Los hashes y los códigos de error permiten diagnosticar la entrega y los fallos sin esos datos.

## Validación de la muestra

Desde la raíz del repositorio:

```bash
PYTHONPATH=tests python3 -m pytest tests/evaluation/test_viewer_contract.py -q
```

La muestra cubre dos afirmaciones y dos validadores, una ruta `FRESH` reutilizada, una descarga fallida, chunks elegidos y descartados, un resultado de Evidence Search cacheado, una cita a `source_id` inexistente y una etapa `NOT_EVALUATED`. Las pruebas comprueban también referencias cruzadas inválidas.

## Captura disponible desde la fase 2

Para guardar metadatos de Generate Assertions en una ejecución de evaluación, configurar `EVALUATION_CAPTURE_GENERATION=true` en el **worker** antes de publicar la orden. El mensaje opcional `evaluation_trace` se persiste como `generation_evaluation_trace` en la orden; no se incorpora a `assertions-document-v2` ni al documento de IPFS. Registra proveedor, modelo, temperatura, versión, duración, estado, tipo de error, número de afirmaciones, si hubo reparación y número de llamadas estructuradas (inicial + reparación). No registra reintentos internos de transporte, prompts ni respuestas crudas. Si la opción no estaba activa, el snapshot deja tiempos e intentos en `null`.

Las anotaciones adicionales de un caso pueden incluir `source_excerpt` (texto literal de `news`), `expected_topic_code`, `expected_evidence_kind` y `expected_context` con listas de nombres de entidades, lugares y valores temporales, más una jurisdicción parcial. El emparejamiento de afirmaciones y la detección de pérdidas léxicas son aproximaciones explícitas; no certifican fidelidad semántica.

## Captura disponible desde la fase 4

Configurar `EVALUATION_CAPTURE_PIPELINE=true` en `validate-asertions` para enviar `X-Evaluation-Run-ID` (ID de orden) a Router y Evidence Search. En una respuesta fresca, `evaluation_trace.query_execution` registra plan/estado de cada petición, proveedor, filtros, URLs y decisión de deduplicación o límite; `policy_drops` identifica descartes por tipo oficial. `evidences[].evaluation_chunks` contiene **todos** los chunks extraídos, también los no seleccionados, con texto, puntuación léxica, bonificaciones, posición, decisión y `context_ids`. `evaluation_trace.limits` documenta tamaños, ventanas y máximos. Son datos de la respuesta de evaluación y se persisten con la orden/resultado; no se escriben en la caché compartida.

La captura de chunks exige una búsqueda fresca y descarga de texto correcta. Con caché WARM, `chunk_detail=NOT_RECORDED_ON_CACHE_HIT` y `query_execution=[]`; los chunks descartados no se pueden recuperar de la caché compartida. Para órdenes publicadas nuevas, configurar además `EVALUATION_CAPTURE_COLD=true` en `validate-asertions` y `EVALUATION_ALLOW_COLD=true` en Router y Evidence Search; para ejecuciones directas usar `--cache COLD`. Una descarga fallida conserva URL, `fetch_status`, `fetch_error` y `content_type` cuando está disponible. La puntuación no certifica apoyo semántico; `reference_evidence` se muestra como anotación separada.

## Citas y consenso (fase 5)

Con `EVALUATION_CAPTURE_PIPELINE=true`, el validador adjunta `evaluation_citation_trace` al mensaje LIGHT con los `source_id`, `context_id` y `supports` originales declarados por el LLM y los códigos de auditoría. `news-handler` lo guarda en cada validación de la orden, fuera del documento público de validación. El snapshot resuelve cada par contra los contextos entregados **en esa validación** y distingue fuente inexistente, contexto inexistente y contexto no citable. En órdenes sin traza usa las citas normalizadas y la auditoría disponible; una cita rechazada cuyo ID original no persiste puede quedar sin detalle individual. La etapa de consenso copia motivo, distribución y votos/pesos resumidos de `assertion_results`, sin replicar los textos completos de `details`.

## Traza detallada de Source Router (fase 3)

`X-Evaluation-Run-ID` habilita `response.evaluation_trace` sin alterar la ruta persistida. `cache_lookup` indica `FRESH`, `STALE`, `MISSING` o `BYPASSED_COLD`; `planned_queries[]` separa consulta prevista de consulta ejecutada y `query_execution[]` guarda por llamada proveedor, URL devuelta, dominio normalizado, decisión (`RETAINED`, `DUPLICATE_DOMAIN`, `EMPTY_URL`, `INVALID_DOMAIN`) y error tipado. `classification[]` conserva tipo, autoridad, jurisdicción, coincidencias, puntuación base exacta y por componentes, elegibilidad y motivos de exclusión. `ranking[]` enumera todos los candidatos de ruta con base, bonificación de idioma, puntuación final, rango o descarte (`RANK_LIMIT`, `PROFILE_MISSING`). `profile_fallback_candidates[]` informa por qué se reutilizó o rechazó cada perfil, y `preserved_domains[]` separa candidatos retenidos de una ruta previa.

Una ruta fresca de caché no ejecuta descubrimiento en esa orden: `execution_detail=NOT_EXECUTED_CACHE`, `query_execution=[]`. Las listas de diagnóstico guardadas se etiquetan `diagnostics_origin=stored_route`; sus URLs y motivos históricos individuales no se reconstruyen. El ranking mostrado se calcula con los perfiles actuales y conserva `classification_components=NOT_STORED_IN_ROUTE` para no presentar un desglose histórico inventado. Un fallo parcial de clasificación conserva el dominio con `NO_VALID_CLASSIFICATION`, sin atribuir una causa individual no observada al LLM.
