# Estrategia de implementación: Generate Assertions en dos fases

**Fecha:** 17 de noviembre de 2026. **Estado:** diseño para revisión; no implementado ni desplegado.

**Resultado posterior de 20 llamadas reales:** el [experimento encadenado](../../tests/generate-assertions-two-stage-live-probes-2026-11-17.md) encontró selección completa en dos casos sintéticos breves, pero solo 3/9 cadenas llegaron a `AssertionsDocumentV2` y ninguna combinación mejoró el tiempo total frente a su única medición LEGACY emparejada. La segunda llamada consumió el ahorro de la primera. La auditoría detectó que el esquema LEGACY permitió 20 elementos mientras su prompt pedía 7; la comparación debe repetirse con ambos límites iguales. **Esta estrategia permanece como hipótesis de implementación, no como optimización acreditada.** Antes de construir el selector o activar `TWO_STAGE`, se necesita la prueba larga indicada abajo. El valor inicial propuesto sigue siendo `LEGACY`.

## Evidencia que condiciona el diseño

| Evidencia | Consecuencia para la implementación |
| --- | --- |
| El [estudio histórico](../../tests/generate-assertions-prompt-history-2026-11-17.md) sitúa el salto principal en `v0.0.12`: de categoría y texto a contexto y búsquedas. Con el mismo modelo, las dos respuestas del caso de 449 caracteres tardaron 38,762–51,625 s en `v0.0.12` y 37,267–51,108 s en `v0.0.13`, frente a 14,725–29,955 s en las variantes anteriores. | Separar selección de hechos de enriquecimiento es una hipótesis concreta. Son muestras demasiado pequeñas y cortas para prometer una reducción de latencia en noticias largas. |
| La [prueba de prompts](../../tests/generate-assertions-prompt-ab-2026-10-29.md) observó pérdidas de negación y jurisdicción al acortar el prompt actual, sin mejora de tiempo. | La fase 1 necesita reglas breves pero explícitas sobre negación, cifras, fechas y hechos centrales. La fase 2 necesita el contexto original suficiente para asignar jurisdicción y construir búsquedas fieles. No basta con recortar instrucciones. |
| El [benchmark de modelos](../../tests/generate-assertions-openrouter-2026-10-31.md) encontró mayor velocidad con `reasoning=minimal` y con otro modelo, pero peor F1, más reparaciones o fallos. | En la primera comparación se mantienen proveedor, modelo, temperatura, límite de aserciones y política de reintentos. Cambiar el modelo es un experimento distinto. |
| El [compendio de rendimiento](../../tests/generate-assertions-performance-compendium-2026-11-15.md) señala que una reparación puede repetir el JSON completo y que Kafka procesa una orden cada vez. | Medir ambas fases, reparaciones, publicación y tiempo total por orden. Dos llamadas secuenciales pueden ser más lentas aunque la extracción aislada mejore. |

**Orden de optimización:** primero probar dos fases con salida intermedia pequeña y un solo lote de enriquecimiento; después ajustar únicamente los campos deterministas que el servidor ya puede asignar (índices y versión de taxonomía) y el tamaño de las ventanas, verificando cobertura. Si las trazas muestran reparaciones frecuentes, estudiar reparación acotada sin crear otro cliente LLM. Paralelizar aserciones u órdenes Kafka puede aumentar capacidad, pero no demuestra una mejora de latencia por noticia y exige otros controles. Los resultados anteriores no respaldan empezar por recortar el prompt actual o rebajar el razonamiento/modelo. La suma de tiempo y tokens de **ambas** fases debe compararse con `LEGACY`.

## Contrato que permanece estable

`LEGACY` significa **el generador actual de `postTFM`**, no el prompt de `v0.0.11`. El selector solo altera el interior del microservicio `generate-asertions`. El punto de entrada común seguirá siendo [`extract_assertions_from_text`](../../../api/generate-asertions/main.py), usado por `/extraer` y por el consumidor Kafka. Ambas estrategias devolverán `List[Assertion]` completo y validado.

Después del selector se seguirá usando [`build_generated_document`](../../../api/generate-asertions/main.py), que llama a [`build_assertions_document_v2`](../../../api/common/models/protocol_models.py). El documento final conservará `AssertionsDocumentV2`, `EnrichedAssertion`, `assertions-document-v2`, `categoryId`, `topic_code`, `evidence_kind`, `taxonomy_version`, contexto, `search_hints`, `GeneratorInfo` y los modos LIGHT/BLOCKCHAIN. Se conservarán `/extraer`, los mensajes `assertions_generated`/`assertions_not_generated`, topics Kafka, cuotas, orden de índices e identificadores y la ausencia de `order_id` en el documento de protocolo. [`news-handler`](../../../api/news-handler/main.py), [`evidence-search`](../../../api/evidence-search/main.py), los validadores y `news-chain` recibirán el mismo modelo e interfaces de comunicación.

`search_hints` forma parte del contrato útil, no solo del esquema: Evidence Search prioriza `suggested_queries` y combina contexto temporal, entidades y lugares. No se sustituirá por listas vacías para acelerar. Por la misma razón, las aserciones publicadas deben preservar negaciones, números, fechas y jurisdicción verificable.

## Selector y motor único

Introducir `GENERATION_STRATEGY=LEGACY|TWO_STAGE` como propiedad del ConfigMap del generador, con valor inicial `LEGACY` y validación estricta al iniciar. Un valor desconocido debe impedir el arranque del worker; no debe activar otra estrategia silenciosamente. La propiedad es del proceso y se aplica igual a HTTP y Kafka. El ConfigMap llega por `envFrom`, por lo que cambiarla requiere desplegar/reiniciar y verificar el valor efectivo en el pod. No se añade al payload de las órdenes.

El despacho dentro de `extract_assertions_from_text` será mínimo: `LEGACY` llama a la actual `_call_configured_llm`; `TWO_STAGE` llama a un solo orquestador interno que devuelve la misma lista `Assertion`. HTTP y Kafka mantienen sus funciones de respuesta y publicación. No se duplican cliente HTTP, política de reintentos, construcción del documento, manejo de cuotas ni lógica de mensajería. Se reutilizan `LLMRequest` y `acomplete_structured_with_repair` de [`common.llm`](../../../api/common/llm/factory.py) para ambas fases.

El [Admin de LLM](../../../api/admin/main.py) actualmente solo persiste y replica proveedor, modelo, temperatura y versión; su normalizador descartaría una propiedad de estrategia. La primera entrega usará el ConfigMap y registrará la estrategia efectiva en métricas. Si posteriormente se requiere cambio desde Admin, habrá que extender de forma coherente su contrato de configuración por componente, la API del generador, la persistencia y la comprobación `desired/actual`; añadir el campo solo al generador no crearía un control central fiable.

```text
                    extract_assertions_from_text(text, trace)
                               │
                  GENERATION_STRATEGY
                    ┌──────────┴──────────┐
                    │                     │
                 LEGACY              TWO_STAGE
          _call_configured_llm     extracción → enriquecimiento
                    └──────────┬──────────┘
                         List[Assertion]
                               │
                      build_generated_document
                               │
                  AssertionsDocumentV2 → HTTP/Kafka
```

## Fase 1: seleccionar afirmaciones y su procedencia

Recibe la noticia completa **una sola vez** y usa el mismo proveedor/modelo de `LEGACY` durante la comparación inicial. Su esquema interno pide una lista de hasta `MAX_ASSERTIONS` candidatas: `text` autónomo, uno o varios `source_excerpts` literales breves y un índice local estable. Puede incluir pasajes globales literales si fecha, jurisdicción o sujeto se expresan lejos de la afirmación. No pide categoría, `topic_code`, `evidence_kind`, entidades normalizadas ni consultas de búsqueda.

El prompt de selección conserva los criterios probados: hechos que sostienen la tesis global, una proposición por aserción, idioma original, negaciones, cifras y fechas exactas, sin opiniones ni hechos introductorios accesorios. Un validador local comprueba cantidad, unicidad, índices y presencia literal de cada pasaje en el texto de entrada. La afirmación puede estar reformulada; el pasaje de apoyo debe existir. No se certifica fidelidad semántica solo por coincidencia textual: la suite gold y revisión humana cubren ese riesgo.

**Corrección exigida por el experimento:** en el caso de cuatro países, `F1` y `F2` seleccionaron 4/4 hechos, pero dejaron `2025` fuera del texto de tres aserciones; LEGACY también lo hizo. Los pasajes literales por sí solos no garantizan que el texto sea autónomo. La próxima prueba debe incluir un anclaje global explícito de tiempo y lugar en la salida intermedia y rechazar, o reparar con apoyo textual, una aserción cuyo `text` omita un dato global necesario. Esta regla debe aplicarse de forma general a cualquier noticia, no con lógica específica para 2025 ni para países del benchmark.

Si no hay candidatas válidas se devuelve lista vacía mediante el comportamiento ya existente de `assertions_not_generated`, sin ejecutar la fase 2. Una referencia ausente, un lote excesivo o un JSON inválido se reparan con la política común; si siguen fallando, la orden termina con error explícito. No se publica un lote parcial.

## Fase 2: enriquecer un lote acotado

Recibe únicamente las candidatas seleccionadas, sus pasajes y ventanas contiguas del texto original, más los pasajes globales necesarios. No repite la noticia completa por aserción. En la primera versión se realiza **una llamada para todo el lote**; el paralelismo por aserción se reserva para una medición posterior porque incrementa llamadas, coste y complejidad de fallos. Las ventanas se obtienen conservando posiciones del texto original; el [`chunker` de Evidence Search](../../../api/evidence-search/app/chunker.py) normaliza espacios y actualmente no conserva esas posiciones, por lo que no debe reutilizarse sin adaptar su contrato de manera general.

El esquema interno de respuesta usa el índice local como clave y pide solo decisiones semánticas: `categoryId`, `topic_code`, `evidence_kind`, `context`, `search_hints` y `context_confidence`. No permite añadir, omitir, reordenar ni reescribir candidatas. El servidor añade `text`, `assertion_id`, `assertion_index` y la constante `taxonomy_version` al construir cada `Assertion`; una única función de ensamblado valida después cada `EnrichedAssertion`. [`routing_taxonomy.py`](../../../api/common/routing_taxonomy.py) y [`category_catalog.py`](../../../api/common/category_catalog.py) siguen siendo la única fuente de etiquetas. Jurisdicción y compatibilidad tema/categoría se validan con los modelos actuales. Datos ausentes quedan como desconocidos; ninguna regla local debe convertir ambigüedad en certeza.

**Corrección exigida por el experimento:** el JSON Schema estricto permitió jurisdicciones y parejas tema/categoría que los validadores semánticos rechazaron. La variante compacta falló 4/4 veces; la completa pasó 3/5. El enriquecimiento debe usar el contrato canónico de jurisdicción y la compatibilidad actual, pasar siempre por los modelos de dominio y registrar las causas de reparación. No conviene normalizar silenciosamente `jurisdiction_code`, `applicable_country_codes` ni una categoría incompatible: podría ocultar un cambio de significado. El tipo de evidencia necesita una evaluación separada: en la cadena válida de cuatro afirmaciones solo coincidió con la etiqueta gold en 1/4.

La fase 2 debe producir consultas autónomas con el contexto necesario. Ante un error de esquema se usa la reparación común sobre el lote acotado; si falla, se emite `assertions_not_generated`. No se relanza automáticamente `LEGACY` para la misma orden: duplicaría llamadas y ocultaría el fallo. El operador puede volver a `LEGACY` para órdenes posteriores mediante la propiedad.

## Secuencia de implementación y verificación

1. **Base comparable:** preparar casos sintéticos o expresamente autorizados de longitud corta, media y larga, con hechos decisivos al principio, medio y final; fijar referencias manuales de negaciones, cifras, jurisdicciones, entidades y búsquedas. Capturar tiempos de petición, proveedor, reparación, parseo y publicación. Separar la espera Kafka del tiempo de generación. Los casos de 78 y 449 caracteres del estudio histórico son insuficientes para el problema de noticias largas.
2. **Motor interno aislado:** definir los dos modelos Pydantic internos y el orquestador `TWO_STAGE`; reutilizar `common.llm` y el constructor V2. Probar extracción, procedencia literal, correspondencia exacta de índices, clasificación, errores, salida vacía y no publicación parcial. Mantener el modelo y temperatura iguales en ambas fases para que `GeneratorInfo` continúe describiendo fielmente el resultado.
3. **Despacho y propiedad:** añadir el selector en el único punto de entrada, con `LEGACY` por defecto, y la propiedad versionada del ConfigMap. Las pruebas de contrato deben ejecutar ambas estrategias por `/extraer` y Kafka, en LIGHT y BLOCKCHAIN, y comparar la forma serializada de `AssertionsGeneratedResponse` y `AssertionsDocumentV2`; comprobar también el evento de error y que `order_id` no entra en el documento.
4. **Benchmark emparejado:** adaptar el [ejecutor aislado existente](../../../tests/llm-benchmark/generate_assertions_isolated.py) para seleccionar la estrategia, sin crear otro cliente ni otro motor de métricas. Ejecutar `LEGACY` y `TWO_STAGE` sobre las mismas noticias, mismo SHA, proveedor, modelo, temperatura, máximo y configuración de reintentos. Alternar el orden y repetir lo suficiente para estimar p50/p95; contabilizar todos los intentos, reparaciones, tokens y coste por noticia completa. Revisar manualmente fidelidad de las afirmaciones y medir que `search_hints` recupera evidencias útiles en el flujo existente.
   - **Puerta previa a implementar:** construir primero una batería de noticias sintéticas largas con hechos esenciales al inicio, centro y final, fechas/jurisdicciones expresadas una sola vez, negaciones y cuantificadores. Probar prototipos de prompts y esquema en el ejecutor aislado, con los modelos/ICs finales como validadores. En los dos casos breves ya medidos, las cadenas fueron entre 20 % y 80 % más lentas en mediana por caso; no se debe trasladar esa cifra a noticias largas ni prometer aceleración antes de medirlas.
5. **Activación controlada:** desplegar primero con `LEGACY`, verificar el valor efectivo y los contratos; activar `TWO_STAGE` solo tras superar la comparación de calidad, tiempo total y coste acordada. Un cambio a `LEGACY` en la misma imagen y su rollout es la ruta de reversión. La evidencia kind/local no sustituye aceptación en Hetzner/K3s.

El criterio de adopción es **mejora sostenida del tiempo completo de noticias largas sin pérdida de afirmaciones centrales, negaciones, cifras, jurisdicción, clasificación ni utilidad de búsqueda**, y sin aumento inaceptable de fallos o coste. Los umbrales numéricos se fijan después de disponer de una base larga suficiente. Si la segunda llamada consume el ahorro de la primera, se conserva `LEGACY` y se estudia salida compacta o selección de pasajes como experimento separado.

## Observabilidad y alcance del cambio

El modelo externo [`GenerationEvaluationTrace`](../../../api/common/models/async_models.py) tiene `extra="forbid"`. Para preservar su contrato, los campos actuales mostrarán el total de la orden (`structured_attempts`, `repair_used`, `duration_seconds`, `usage` y tiempos agregados); los tiempos, tokens y fallos de cada fase se registrarán en métricas/logs internos con el identificador de orden y el nombre de fase, sin contenido de noticia, prompts ni respuestas. Si se decide exponer ese desglose en la traza pública, hará falta un cambio aditivo y coordinado del modelo y sus consumidores, evaluado aparte.

No se propone modificar `news-handler`, Evidence Search, validadores, topics, Blockchain/IPFS ni los modelos de protocolo en esta implementación. El trabajo se limita al motor interno del generador, su configuración y las pruebas necesarias para demostrar equivalencia de contrato y calidad. Este documento no activa ninguna estrategia ni autoriza despliegue.
