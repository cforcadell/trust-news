# Prueba de generación de aserciones en dos etapas

Estado: **propuesta; no ejecutada ni implementada**. Fecha: 2026-10-29.

## Objetivo

Comprobar si separar la división de una noticia en aserciones de su enriquecimiento con taxonomía, jurisdicción, contexto y pistas de búsqueda reduce el tiempo **hasta obtener aserciones utilizables** sin perder calidad ni romper el contrato público. Si la prueba cumple los criterios de aceptación, implementar un motor de ejecución configurable y reversible. No introducir reglas específicas para la noticia de ejemplo, países, categorías o proveedores.

## Punto de partida y cautelas

- El flujo actual hace una petición estructurada que devuelve `AssertionBatch` con `Assertion` completos. El esquema exige, entre otros campos, `categoryId`, `topic_code`, `evidence_kind`, `context` y `search_hints`. La respuesta alimenta el resto de la cadena; no puede publicarse una aserción parcial como si fuera completa.
- En nueve llamadas controladas del ensayo anterior, casi todo el tiempo medido estuvo dentro de la generación estructurada. Para los tres casos con el prompt original, la mediana fue **52,0 s**; hubo una ejecución por caso, así que no es una estimación robusta. La llamada incluye transporte, posible cola del intermediario, inferencia y recepción: la traza actual no permite atribuir todo el tiempo al modelo.
- Quitar el ejemplo o compactar el prompt, manteniendo el esquema completo, no mejoró esa pequeña muestra: medianas de **56,5 s** y **65,0 s**; además se perdieron una negación, jurisdicciones o precisión de consultas. No utilizar esas variantes como candidatas de producción.
- Que versiones antiguas sin categorización tardasen pocos segundos hace plausible la hipótesis, pero no constituye una comparación controlada: podrían haber cambiado modelo, ruta, esquema, instrucciones, carga o respuesta requerida.
- La [guía de latencia de OpenAI](https://developers.openai.com/api/docs/guides/latency-optimization) advierte que dos llamadas secuenciales añaden latencia; dividir solo gana si simplificar cada tarea compensa ese coste. La [guía de salidas estructuradas](https://developers.openai.com/api/docs/guides/structured-outputs) respalda contratos explícitos y tareas más simples, pero la validez de esquema no garantiza calidad semántica.

Datos de referencia: [ensayo anterior](tests/generate-assertions-prompt-ab-2026-10-29.md). Código actual: `api/generate-asertions/main.py`, `api/common/models/async_models.py` y `api/common/models/protocol_models.py`.

## Hipótesis y variantes

Hipótesis principal: la primera llamada, limitada a identificar afirmaciones verificables, será rápida y fiel; una segunda llamada que solo clasifique y complete metadatos sobre aserciones ya fijadas costará menos que la generación monolítica. La **métrica decisiva es la suma de las etapas**, no la rapidez aislada de la primera.

| Variante | Ejecución | Latencia crítica estimada conceptualmente |
| --- | --- | --- |
| A. `ONE_PASS` | Una llamada con el contrato completo actual | `T_actual` |
| B. `TWO_STAGE_BATCH` | Una llamada de división y otra de enriquecimiento de todo el lote | `T_división + T_enriquecimiento_lote` |
| C. `TWO_STAGE_PARALLEL` (solo si B no basta) | División; después enriquecimiento por aserción con concurrencia acotada | `T_división + máximo(T_enriquecimiento_i)` más coordinación |

La variante B es la primera candidata. C podría reducir el camino crítico para noticias con varias afirmaciones, pero aumenta llamadas, coste, presión sobre cuotas y superficie de fallo. No prometer paralelismo ilimitado ni presuponer que es más rápida. Mantener el mismo proveedor/modelo en A y B durante la primera prueba para aislar la arquitectura; probar otro modelo o nivel de razonamiento en un experimento separado.

### Contrato interno propuesto

1. **División:** recibir el texto completo y devolver una lista ordenada de objetos mínimos `{id, text, source_spans?}`. `text` conserva polaridad, cifras, unidades, fechas, atribuciones que cambian el significado y alcance de cada afirmación. Los fragmentos de origen, si se emiten, se validan contra el texto de entrada; no se inventan fuentes externas. Límite común `MAX_ASSERTIONS`.
2. **Enriquecimiento:** recibir el texto original y la lista congelada; devolver metadatos por `id`: `categoryId`, `topic_code`, `evidence_kind`, `taxonomy_version`, `context`, `search_hints` y `context_confidence`. La segunda etapa **no puede modificar, fusionar, dividir ni omitir** los textos de la primera. Si hace falta corregir una afirmación, se declara fallo de etapa en vez de cambiarla silenciosamente.
3. **Unión y validación:** unir por identificador estable, exigir correspondencia uno a uno y validar cada resultado con el `Assertion`/`EnrichedAssertion` vigente, incluida la compatibilidad `topic_code`–`categoryId`, jurisdicción y listas canónicas. Publicar solamente el contrato final existente. Los modelos internos de etapa no sustituyen el esquema público.
4. **Fallo:** registrar etapa, intento y razón saneada. Una política de recuperación explícita y acotada puede recurrir al flujo `ONE_PASS`; debe contabilizar tiempo, llamadas y coste del fallback. Nunca publicar un lote parcialmente enriquecido ni convertir una clasificación incierta en segura.

Todo lo anterior será código genérico gobernado por contratos y configuración, sin ramas para España, Alemania, Francia, una noticia concreta o un proveedor. El texto original se pasa a la segunda etapa para recuperar contexto implícito sin inducir inferencias externas.

## Plan de prueba antes de implementar el flujo productivo

### 1. Preparación de casos y gold

- Usar los tres casos del ensayo anterior para una criba inicial y ampliar después a un corpus revisado que cubra varias longitudes, idiomas, negaciones, comparaciones, temporalidad, entidades homónimas, jurisdicciones `GLOBAL`/`SUPRANATIONAL`/`COUNTRY`/`REGION`/`LOCAL`/`UNKNOWN`, atribuciones y afirmaciones no verificables.
- Revisar las anotaciones gold antes de usarlas como juez automático: en el ensayo anterior existía una referencia del RGPD que contradecía el texto de entrada. Registrar explícitamente cualquier corrección del gold y usar exactamente la misma versión para todas las variantes.
- Fijar modelo, proveedor, esquema final, temperatura efectiva, límites, versión de taxonomía, configuración de rutas y entorno. No mezclar cambios de prompt, modelo y arquitectura en la misma comparación.
- Definir de antemano presupuesto máximo de llamadas/coste y detener la prueba si se supera. No utilizar claves nuevas ni leer secretos para producir el informe.

### 2. Ejecución emparejada

- Criba: A frente a B, al menos tres repeticiones por caso, alternando o aleatorizando el orden para amortiguar cambios de carga del proveedor. Guardar artefactos individuales, nunca sobrescribirlos.
- Medir desde la entrada a la etapa hasta que el lote final validado está disponible. Separar división, enriquecimiento, unión/validación, reparaciones, fallback y espera en cola cuando el transporte lo permita.
- Registrar por etapa modelo/ruta observada si se conoce, duración, estado, reintentos reales, tokens de entrada y salida, y desglose de tokens de razonamiento **solo si el proveedor lo informa**. El conteo de salida puede incluir tokens no visibles; no inferir su composición a partir de la longitud del JSON.
- Si B supera la criba de calidad pero no de latencia, probar C sobre el mismo corpus y con concurrencia máxima configurada. Comparar coste total, errores y p95 además de la mediana.
- Repetir la mejor candidata sobre el corpus ampliado, sin cambiar la configuración durante la campaña. Después, hacer una E2E dirigida para verificar que Source Router, Evidence Search, validadores y viewer reciben un `Assertion` completo e idéntico en forma al actual.

### 3. Métricas de comparación

| Dimensión | Medición requerida |
| --- | --- |
| Tiempo | p50/p95 por etapa y total; tiempo desde solicitud de orden hasta aserciones publicadas; distribución por longitud y número de aserciones |
| Coste | Llamadas y tokens por etapa y lote; coste informado o estimado claramente etiquetado; coste de reparaciones y fallback |
| División | Cobertura de afirmaciones gold, duplicados, omisiones, fragmentación excesiva y afirmaciones inventadas |
| Fidelidad | Conservación de negaciones, cifras, unidades, fechas, entidades, atribuciones y alcance; revisión humana de divergencias |
| Enriquecimiento | Exactitud de categoría y tema, `evidence_kind`, jurisdicción, contexto explícito/inferido y consultas autónomas; incompatibilidades de esquema |
| Cadena posterior | Variación de rutas, fuentes citables, `UNKNOWN`, citas y veredicto en E2E, separando fallos técnicos de cambios semánticos |

### 4. Criterios de decisión, fijados antes del ensayo

- **Calidad obligatoria:** ninguna pérdida de una afirmación gold, negación, cifra o ámbito jurisdiccional relevante en el conjunto crítico revisado; sin afirmaciones inventadas, duplicados materiales ni violaciones del contrato final. Las diferencias de clasificación deben revisarse, no ocultarse tras una puntuación agregada.
- **Rendimiento:** en el corpus ampliado, la mediana del tiempo total hasta lote válido debe bajar al menos **20 %** frente a A y el p95 no debe empeorar más de **10 %**. Son umbrales de decisión propuestos, no resultados. Si la muestra no permite estimar p95 con confianza, repetir antes de decidir.
- **Coste y fiabilidad:** declarar el límite aceptable de coste antes de ejecutar; como punto de partida, no aumentar más de **20 %** el coste por lote válido ni la tasa de fallo/reparación. Cualquier fallback entra en ambos cálculos.
- Si el primer paso es rápido pero el segundo lleva el total cerca de A, **no implementar** B por esa sola observación. Si B incumple calidad o rendimiento, mantener A y documentar la causa; C solo se evalúa si existe una hipótesis concreta de cuello de botella por lote.

## Implementación condicionada a resultado positivo

1. Extraer un `AssertionGenerationEngine` con estrategias configurables `ONE_PASS` y `TWO_STAGE_BATCH`; añadir `TWO_STAGE_PARALLEL` únicamente si C supera las mismas puertas. Centralizar presupuestos, timeouts globales, concurrencia, diagnóstico y fallback; no duplicar lógica por proveedor o noticia.
2. Añadir modelos internos versionados de división y enriquecimiento y sus prompts respectivos. Mantener `Assertion` como salida canónica y la compatibilidad del mensaje Kafka, API, orden, caché y evaluadores. Versionar la estrategia en cualquier clave de caché que dependa del resultado generado.
3. Instrumentar y persistir la procedencia de etapa sin guardar secretos ni prompts completos. Distinguir duración del LLM, cola, validación y publicación. El timeout debe limitar la operación total, no solo periodos de inactividad de red.
4. Añadir pruebas unitarias de fidelidad, IDs estables, unión, jurisdicción, compatibilidad de taxonomía, respuestas incompletas, reparaciones, fallback y límites. Añadir pruebas de contrato de Kafka/API y de importación de artefactos antiguos.
5. Desplegar con `ONE_PASS` por defecto y activar B mediante configuración versionada en sombra o canary. Comparar campañas frías y emparejadas, observar p50/p95, coste y calidad; promover solo tras revisión. Mantener rollback inmediato a `ONE_PASS` sin migración de datos.

## Estado y siguiente acción

Este documento es solo una **propuesta de prueba y de implementación condicionada**. En esta edición no se han llamado modelos, ejecutado campañas, modificado configuración, desplegado servicios ni cambiado código de producción. El siguiente trabajo autorizado sería preparar el corpus/gold y un harness comparativo que produzca artefactos reproducibles; la implementación productiva depende de superar las puertas anteriores.
