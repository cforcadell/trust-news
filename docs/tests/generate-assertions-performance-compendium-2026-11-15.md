# Compendio de estrategias para acelerar Generate Assertions

**Fecha:** 2026-11-15
**Estado:** compendio y diseño candidato de C en dos fases; sin implementación ni mediciones nuevas.
**Problema comunicado:** noticias largas cuya generación supera 90 s. No hay en este análisis una traza de una de esas órdenes que atribuya el tiempo a una fase concreta.

## Fuentes y conclusión conjunta

Este documento pone en comparación dos análisis independientes aportados para esta revisión y el análisis previo del repositorio. Se contrastaron sus propuestas con [el generador](../../api/generate-asertions/main.py), [el cliente LLM común](../../api/common/llm/factory.py), [la configuración versionada](../../k8s/apis/generate-asertions/configmap.yaml), [el benchmark de modelos](generate-assertions-openrouter-2026-10-31.md) y [la prueba de prompts](generate-assertions-prompt-ab-2026-10-29.md).

Los tres análisis coinciden en medir por fases, reducir trabajo innecesario por petición y tratar de forma específica los textos extensos. Tras revisar la dependencia de un clasificador semántico local, la **primera candidata a desarrollar es C: extracción ligera y enriquecimiento LLM en dos fases**. A, B y D quedan como alternativas para comparar si C no mejora el tiempo completo manteniendo calidad.

| Análisis | Prioridad propuesta | Aporte que se conserva | Ajuste tras contrastarlo con el repositorio |
| --- | --- | --- | --- |
| **Adjunto A: análisis de rendimiento** | Extracción en dos fases y, después, arquitectura híbrida con fragmentos, reglas locales y selección global. | Distingue extracción de enriquecimiento; exige procedencia textual y contempla el coste de reparar un JSON entero. | Sus porcentajes, plazos y umbrales son hipotéticos. Recortar el ejemplo JSON o las reglas del prompt como primera optimización choca con la prueba local de prompts; las reglas locales necesitan límites claros. |
| **Adjunto B: revisión del flujo y benchmarks** | Instrumentación y reintentos; luego salida compacta; fragmentación para entradas largas si el perfil de tiempos lo aconseja. | Separa latencia de una petición, espera en Kafka y tiempo total; propone ruta por dificultad y concurrencia acotada. | `MAX_ASSERTIONS=20` es el valor por defecto del código; el ConfigMap versionado fija 7. La ruta por dificultad y la reutilización HTTP quedan como hipótesis que requieren medir. |
| **Análisis previo de esta conversación** | Trazas reales; competir entre selección previa de pasajes, fragmentación con selección global y reducción de salida. | Señala que los benchmarks existentes son demasiado cortos y que la calidad debe abarcar negación, jurisdicción y búsquedas. | La selección extractiva también puede perder hechos centrales y solo debe adoptarse tras medir su cobertura. |

## Hechos comprobados y límites de la evidencia

| Hallazgo | Evidencia y alcance |
| --- | --- |
| El generador envía el texto completo y pide simultáneamente afirmaciones, clasificación, contexto y consultas. | `build_assertions_prompt` y `AssertionBatch` en [main.py](../../api/generate-asertions/main.py). No hay una ruta de segmentación de la noticia en ese módulo. |
| Una respuesta inválida puede originar otra llamada con el JSON completo y el error de validación. | `acomplete_structured_with_repair` en [factory.py](../../api/common/llm/factory.py) y prompt de reparación en [main.py](../../api/generate-asertions/main.py). Los fallos de transporte tienen reintentos adicionales. |
| El consumidor Kafka espera a que acabe una orden antes de tomar la siguiente. | `consume_and_process` en [main.py](../../api/generate-asertions/main.py). Esto puede elevar la espera en cola; por sí solo no demuestra que una generación aislada tarde 90 s. |
| La configuración versionada indica `MAX_ASSERTIONS=7`, `HTTP_TIMEOUT=60` y `LLM_MAX_RETRIES=3`. | [configmap.yaml](../../k8s/apis/generate-asertions/configmap.yaml). El código tiene otros valores por defecto y admite configuración administrativa; el valor efectivo del pod no se ha verificado aquí. `LLM_TIMEOUT`, si existe, prevalece sobre `HTTP_TIMEOUT` en el cliente. |
| Ya existe una traza de generación, pero no desglosa cada reintento ni el tiempo previo en cola. | `GenerationEvaluationTrace` en [async_models.py](../../api/common/models/async_models.py); el [visor](benchmark-viewer-plan.md) indica expresamente que los reintentos internos no se exponen. |
| Los ensayos comparativos no representan artículos largos. | El benchmark de modelos usó cinco noticias de **78 a 103 caracteres**, dos repeticiones por configuración. La prueba de prompts usó tres textos de **220 a 349 caracteres**, una repetición por variante. Esas longitudes proceden de los casos versionados en `tests/data/benchmark/resources/cases/`. |
| Cambiar solo el modelo o acortar el prompt no ha demostrado una mejora segura de calidad. | En el [benchmark](generate-assertions-openrouter-2026-10-31.md), las opciones más rápidas perdieron F1 o fiabilidad. En la [prueba de prompts](generate-assertions-prompt-ab-2026-10-29.md), quitar el ejemplo o compactar instrucciones no redujo la mediana y produjo pérdidas de negación, jurisdicción o detalles de consulta. Las muestras son pequeñas. |

**No son resultados medidos:** los porcentajes de mejora (15–70 %), las horas de desarrollo (49–81 h), el ejemplo de 90 → 68 s, los umbrales de 1.800/1.000 tokens y el objetivo `p95 < 45 s` del primer análisis. Sirven para formular hipótesis o presupuestos, no para estimar el resultado de este sistema. Tampoco puede afirmarse que el JSON extenso sea la causa dominante de los 90 s sin una traza larga.

## Alternativas en competencia

La columna de latencia describe el mecanismo esperado, no una reducción cuantificada.

| Candidata | Mecanismo | Pros | Contras y condición para adoptarla |
| --- | --- | --- | --- |
| **A. Salida compacta en una llamada** | Mantener la noticia completa; pedir solo los campos semánticos que el LLM debe decidir. Construir identificadores, índices y constantes en código mediante los constructores existentes. | Un solo viaje al proveedor; reduce generación de JSON y posibles errores de formato; menor cambio de flujo. | Sigue leyendo todo el artículo. Hay que demostrar que disminuyen los tokens de salida sin degradar contexto, taxonomía ni consultas. **No equivale a recortar solo el prompt**, ya ensayado con resultado desfavorable. |
| **B. Selección extractiva de pasajes y una llamada final** | Seleccionar fragmentos pertinentes a la tesis, conservar citas y posiciones de origen, y enviar una selección acotada al generador estructurado actual. | Reduce el texto de entrada sin multiplicar llamadas de generación completa; preserva el contrato final. | Un selector puede omitir la afirmación decisiva, sobre todo si aparece en medio o lejos del titular. Necesita medir *recall* de selección antes de usarlo. |
| **C. Extracción ligera y enriquecimiento en dos fases** | Una llamada identifica afirmaciones y fragmentos de apoyo; una segunda enriquece únicamente las seleccionadas, preferiblemente en un lote acotado. | Separa selección y elaboración estructural; permite observar y optimizar cada coste. | Son dos fases secuenciales. Si ambas reciben el artículo completo o la segunda genera demasiado, puede tardar más. Una puntuación `relevance` del modelo no es calidad calibrada. |
| **D. Candidatos por fragmento en paralelo y selección global** | Segmentar por secciones, producir candidatos breves con concurrencia limitada, eliminar duplicados y elegir globalmente hasta siete antes del enriquecimiento final. | Puede reducir el tiempo de pared en noticias muy largas; procesa información situada en cualquier sección. | Aumenta llamadas, tokens facturados y presión sobre límites del proveedor. La selección global es indispensable: el objetivo son hechos centrales, no todos los hechos. Hay que preservar relaciones entre secciones y gestionar fallos parciales sin publicar lotes incompletos. |
| **E. Reglas locales para campos inequívocos** | Normalizar valores derivados, validar compatibilidad de taxonomías y resolver solo casos semánticos con LLM. | Evita pedir al modelo datos ya conocidos; podría reducir salida y reparaciones. | Un NLP local nuevo (`spaCy`, `dateparser`, etc.) añade dependencias y mantenimiento. Fechas implícitas, negaciones, entidades referidas por pronombres y jurisdicción requieren interpretación; no deben rellenarse con reglas dudosas. Primero adaptar validadores y modelos comunes existentes. |
| **F. Reparación selectiva y presupuesto de reintentos** | Medir cada intento; corregir localmente solo errores deterministas y remitir al LLM únicamente elementos que requieren juicio semántico. Limitar la espera acumulada según política explícita. | Mejora la cola de latencia cuando hay errores o reparaciones; evita regenerar lotes completos por un campo. | No acelera la primera respuesta válida. Un plazo demasiado corto eleva los fallos; el resultado final debe superar Pydantic y conservar todas las afirmaciones seleccionadas. |
| **G. Concurrencia de órdenes Kafka y reutilización HTTP** | Varias órdenes en vuelo con límites, confirmación de offsets e idempotencia por `order_id`; estudiar reutilizar conexiones HTTP. | Reduce esperas entre órdenes y mejora capacidad de proceso cuando hay carga. | No reduce necesariamente la duración de una noticia aislada. Exige revisar entrega, duplicados, reinicios y cuotas del proveedor. |
| **H. Caché y progreso visible** | Caché por hash exacto de artículo/configuración; eventos de progreso sin publicar aserciones provisionales como definitivas. | Mejora repetidos y experiencia de usuario. | La caché no ayuda a noticias nuevas; la similitud semántica puede reutilizar hechos obsoletos. El progreso no reduce el tiempo de generación. |

**Relación entre candidatas:** D ya contiene la selección global propia de *map–reduce*; no son dos reimplementaciones independientes. Si C demuestra calidad pero la primera fase sigue siendo lenta con artículos largos, se podrá estudiar B o D sin cambiar el contrato final.

## Recomendación de experimentación

1. **Establecer la línea base con órdenes reales:** separar publicación en Kafka, espera hasta inicio de procesamiento, construcción de la petición, cada intento HTTP, reparación, parseo y publicación de respuesta. Registrar longitudes y tokens de entrada, caché, razonamiento y salida cuando el proveedor los ofrezca; guardar solo métricas y errores resumidos, sin textos ni claves en logs operativos. Distinguir la latencia del generador de la validación posterior y de la experiencia completa en la GUI.
2. **Preparar un conjunto versionado de noticias cortas, medianas y largas:** incluir negaciones, cifras, fechas, entidades ambiguas, varias jurisdicciones y hechos decisivos al principio, medio y final. Revisar manualmente las afirmaciones clave y fragmentos de apoyo. La suite `official-gold-v0` es útil como regresión corta, no como muestra suficiente de artículos largos.
3. **Comparar con la misma base y el mismo modelo:** ejecutar el flujo actual y C sobre exactamente los mismos artículos, con configuración y presupuesto de llamadas fijados. Medir p50 y p95 con suficientes repeticiones para interpretar la variabilidad; contabilizar también reintentos, reparaciones, fallos y coste real. Si C no mejora las noticias largas sin perder calidad, contrastar B y D con esa misma base. Una corrida aislada no decide el ganador.
4. **Elegir por calidad y tiempo completos:** comparar *recall* de afirmaciones centrales, precisión, atomicidad, fidelidad al texto, negaciones, números, jurisdicción, entidades, contexto temporal, validez del contrato y utilidad de `search_hints` para encontrar evidencias. La revisión humana decide errores semánticos que el emparejamiento automático no resuelve. Medir también si la nueva salida empeora Evidence Search o la validación posterior.
5. **Adoptar la variante más simple que supere las puertas de calidad:** fijar los umbrales de latencia, coste y pérdida admisible de calidad después de medir la base larga. Las cifras del primer análisis pueden tratarse como aspiraciones para debatir, nunca como predicción ni criterio ya acordado.

## Coherencia de implementación si se abre desarrollo

- Mantener `AssertionsDocumentV2`, LIGHT/BLOCKCHAIN y los eventos Kafka actuales como contrato final. [build_assertions_document_v2](../../api/common/models/protocol_models.py) ya normaliza los índices y los identificadores de las afirmaciones finales.
- Reutilizar `LLMRequest`, la validación y la reparación de [common.llm](../../api/common/llm/) en lugar de crear otro cliente o motor de reintentos.
- [Evidence Search ya divide texto](../../api/evidence-search/app/chunker.py); estudiar extraer o adaptar ese mecanismo como módulo común para ambas funciones. Su versión actual normaliza espacios y no conserva posiciones exactas, así que una selección con fragmentos de origen necesita ampliar ese contrato antes de reutilizarlo.
- `search_hints` admite listas vacías en el modelo, pero [Evidence Search las consume](../../api/evidence-search/main.py). Generarlas bajo demanda o quitarlas del primer resultado requiere medir el efecto aguas abajo y revisar el contrato entre servicios.
- Si se añade selección por longitud, parametrizar y probar el motor de estrategia para todos los textos. Los umbrales son parámetros experimentales, no excepciones codificadas para una noticia concreta.

## Diseño candidato: C, extracción y enriquecimiento en dos fases

### Decisión y límite

La primera fase usará el LLM para seleccionar y redactar hasta `MAX_ASSERTIONS` afirmaciones centrales de la **noticia completa**. La segunda usará el LLM para completar `categoryId`, `topic_code`, `evidence_kind`, jurisdicción, entidades, tiempo, confianza de contexto y `search_hints` **solo para las afirmaciones elegidas**. El código asignará índices e identificadores, validará el resultado y construirá el documento V2. Así se evita crear un clasificador semántico local: los catálogos existentes restringen y validan etiquetas, pero no infieren su significado.

C es una candidata para comparar, no una mejora de velocidad demostrada. Las dos llamadas son secuenciales y la primera sigue leyendo el artículo completo. El diseño solo compensa si la reducción del trabajo de extracción y el menor contexto de enriquecimiento superan el coste de esa segunda llamada.

### Flujo y contratos internos

```text
Noticia original
  → fase 1: extracción LLM breve, selección global y fragmentos de apoyo
  → validar cantidad, unicidad y apoyo en el texto
  → recuperar ventanas de contexto del artículo para las elegidas
  → fase 2: enriquecimiento LLM de un lote acotado
  → validar correspondencia exacta, taxonomía y esquema final
  → build_assertions_document_v2
  → respuesta HTTP o evento Kafka ya existente
```

- **Salida de fase 1:** lista ordenada de candidatas con `text` autónomo y un fragmento literal de apoyo o referencia a su posición. No pide clasificación, jurisdicción ni objetos de búsqueda. Selecciona los hechos cuya falsedad cambiaría la tesis global y conserva cifras, fechas y negaciones. Si no hay hechos verificables devuelve lista vacía, como permite el prompt actual.
- **Entrada de fase 2:** cada afirmación seleccionada, su pasaje de apoyo, contexto contiguo y los datos globales imprescindibles de la noticia. El enriquecimiento procesa el lote completo o lotes acotados; **no recibe de nuevo todo el artículo por cada afirmación**. El tamaño y forma de las ventanas se fijarán con casos reales para no perder contexto inferido de otra sección.
- **Salida de fase 2:** los campos semánticos requeridos por [`EnrichedAssertion`](../../api/common/models/protocol_models.py), asociados a la posición estable de cada candidata. No puede añadir, omitir, reordenar ni reescribir afirmaciones de fase 1. El servidor asigna `assertion_id`, `assertion_index` y la versión fija de taxonomía al construir [`AssertionsDocumentV2`](../../api/common/models/protocol_models.py).
- **Contrato externo:** `/extraer`, `assertions_generated`, `assertions_not_generated`, LIGHT y BLOCKCHAIN conservan los modelos actuales. El mismo orquestador de fases será llamado por HTTP y Kafka; no habrá dos implementaciones de C.

La comprobación de apoyo textual debe aceptar reformulaciones fieles, pero el fragmento citado ha de existir en el artículo original. Esta comprobación mecánica no prueba por sí sola que la afirmación sea semánticamente correcta. Si una afirmación depende de pasajes distantes, la segunda fase necesita ambas ventanas; no se inventará un contexto ausente para forzar el esquema.

### Reutilización y configuración

La implementación se apoyaría en `LLMRequest` y [`common.llm`](../../api/common/llm/) para las dos llamadas y para la reparación estructurada. [`EnrichedAssertion`](../../api/common/models/protocol_models.py) ya valida `categoryId` y su compatibilidad con `topic_code`; [`routing_taxonomy.py`](../../api/common/routing_taxonomy.py) y [`category_catalog.py`](../../api/common/category_catalog.py) serán las únicas fuentes de etiquetas. La lógica de selección y ensamblado estará en un único motor interno del generador, con contratos Pydantic separados por fase. El [divisor de Evidence Search](../../api/evidence-search/app/chunker.py) puede adaptarse a un módulo compartido si las ventanas necesitan segmentación; su versión actual normaliza espacios y no conserva posiciones exactas.

Para una comparación controlada, una propiedad de estrategia del generador podría seleccionar el flujo actual o C durante las pruebas. No se necesita la propiedad `ASSERTION_CLASSIFICATION_VERIFY_ENABLED` del diseño A+C, que queda descartada: **la segunda fase de C produce la clasificación y el contexto, no valida una clasificación local**. Antes de añadir una nueva propiedad o ampliar la administración se revisarán los mecanismos de configuración existentes; el [contrato administrativo de LLM](../../api/admin/main.py) solo gestiona proveedor, modelo, temperatura y versión. Tras decidir la adopción, se debe evitar mantener indefinidamente dos motores que hagan lo mismo.

### Fallos y observabilidad

| Situación | Comportamiento previsto |
| --- | --- |
| Fase 1 devuelve cero candidatas válidas. | Usar el resultado existente `assertions_not_generated` sin llamar a la fase 2. |
| Fase 1 devuelve candidatas sin apoyo trazable o supera el máximo. | Rechazar o reparar mediante la política común; no enviar afirmaciones no verificables a la fase 2. |
| Fase 2 omite, añade o altera una afirmación, o produce clasificación incompatible. | Intentar la reparación estructurada acotada al lote; si sigue inválida, emitir `assertions_not_generated`. No publicar un subconjunto silenciosamente. |
| Timeout, reintento agotado o error de proveedor en cualquier fase. | Mantener la semántica de error existente y registrar fase, intento, duración y tipo de fallo. |

Ampliar la [traza actual](../../api/common/models/async_models.py) con duración y tokens por fase, reintentos reales, reparaciones, número de candidatas y causa de descarte. Separar también espera Kafka y publicación. Los logs operativos contendrán metadatos y errores resumidos, sin claves, prompts ni texto crudo de la noticia.

### Prueba de la hipótesis y puertas de adopción

1. **Línea base:** medir órdenes largas reales para distinguir tiempo de extracción, reparación, cola y validación posterior. El benchmark anterior de textos muy cortos no permite estimar el ahorro.
2. **Comparación emparejada:** flujo actual frente a C, mismo modelo, proveedor, configuración, artículos y repeticiones. Contabilizar las dos llamadas y todas las reparaciones o reintentos; medir p50/p95, coste y tasa de éxito por artículo completo.
3. **Calidad:** revisar con casos versionados las afirmaciones centrales omitidas o añadidas, negaciones, cifras, jurisdicción, entidades, fechas y autonomía de `search_hints`. Verificar el contrato V2 y el efecto de las consultas en Evidence Search, no solo la validez del JSON.
4. **Decisión:** activar C únicamente si mejora el tiempo completo de las noticias largas sin degradar calidad ni disponibilidad según umbrales fijados después de medir la línea base. Si la fase 1 sigue dominando el tiempo, estudiar selección de pasajes o fragmentación paralela como experimento posterior.

**Estado:** C es el candidato de desarrollo. Este documento no modifica código, configuración efectiva ni despliegues.
