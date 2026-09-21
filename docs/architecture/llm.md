# Uso de LLM en Assermetry

> Inventario y recomendación de arquitectura revisados el 20 de septiembre de 2026.
> Los nombres de modelos cambian con rapidez: deben considerarse candidatos para una
> evaluación reproducible, no una configuración que se deba copiar sin medirla.

## Resumen ejecutivo

El proyecto realiza inferencia con LLM en tres módulos:

1. `generate-asertions`: extrae y estructura las aserciones verificables de una noticia.
2. `source-router`: clasifica los dominios candidatos para decidir qué fuentes son
   apropiadas para una ruta de evidencia.
3. `validate-asertions`: emite un veredicto `TRUE`, `FALSE` o `UNKNOWN`. Tiene tres
   variantes LLM: memoria, búsqueda online del proveedor y RAG con evidencias recuperadas
   por Assermetry.

La prioridad de calidad debe ser:

1. **Validador RAG**: necesita el mejor razonamiento probatorio y, si se incorpora, un
   segundo modelo especializado en entailment/NLI.
2. **Generador de aserciones**: necesita un modelo fuerte en extracción semántica y salida
   estructurada, porque un error suyo se propaga a toda la cadena.
3. **Validador con búsqueda online**: necesita un modelo competente y buen motor de
   búsqueda, aunque su traza actual no es auditable por Assermetry.
4. **Clasificador del source router**: puede usar un modelo pequeño y rápido, siempre con
   reglas deterministas y abstención.
5. **Validador por memoria**: un modelo mejor reduce errores, pero no corrige su carencia
   fundamental de evidencia actual y verificable; no conviene concentrar aquí el gasto.

No usan LLM `evidence-search`, `news-handler`, `news-chain`, `gateway`, IPFS ni los
contratos. `evidence-search` recupera y fragmenta documentos; el LLM que interpreta esos
fragmentos vive en `validate-asertions`. `admin` tampoco hace inferencia: consulta el
catálogo de OpenRouter y ordena modelos mediante una heurística local.

## Flujo

```text
noticia
  |
  v
generate-asertions -- LLM de extracción estructurada
  |
  +--> aserciones + taxonomía + contexto + consultas sugeridas
          |
          +--> source-router -- búsqueda de candidatos
          |       |
          |       +--> LLM de clasificación de dominios
          |
          +--> evidence-search -- recuperación/chunking, sin LLM
                  |
                  v
          validate-asertions -- LLM de verificación
                  |
                  +--> comprobaciones deterministas de JSON y grounding
                  |
                  v
             consenso / cadena
```

## Inventario por módulo

### `api/generate-asertions`

**Uso.** Convierte el texto completo en un máximo configurable de afirmaciones factuales,
atómicas, autocontenidas y verificables. También asigna `categoryId`, `topic_code`,
`evidence_kind`, entidades, lugares, jurisdicción, contexto temporal y pistas de búsqueda.

**Contrato.** La respuesta se valida contra `AssertionBatch` y los modelos Pydantic de
`common.models`. Con Gemini directo se envía un JSON Schema. Con OpenRouter el llamador
marca `json_mode`, pero el adaptador actual no traduce esa marca a `response_format` para
OpenRouter: en la práctica depende de la instrucción del prompt y valida después en local.
Existe un comentario explícito indicando que Gemini 2.5 Flash-Lite devolvía objetos vacíos
con el schema estricto a través de OpenRouter.

**Tipo de modelo necesario.** Modelo de extracción de información multilingüe con muy
buena obediencia a esquemas, cobertura de hechos, resolución de correferencias y
normalización taxonómica. No necesita navegar por Internet ni resolver la verdad de la
noticia. Debe preferir precisión a creatividad y trabajar a temperatura baja.

**Riesgo principal.** Es el mayor punto de propagación: una aserción omitida, compuesta,
mal contextualizada o mal clasificada condiciona el routing, la recuperación de evidencia,
los validadores y el resultado final.

**Configuración encontrada.** La base de Kubernetes usa
`google/gemini-2.5-flash-lite` vía OpenRouter; producción sobrescribe el modelo con
`openai/gpt-5-nano`. El fichero `.env` de desarrollo no debe tomarse como descripción del
despliegue.

### `api/source-router`

**Uso.** El buscador descubre una lista cerrada de dominios candidatos. El LLM asigna a
cada uno tipo de fuente, nivel de autoridad, jurisdicciones, temas, clases de evidencia,
idiomas y grado de coincidencia con la ruta solicitada. No debe buscar dominios, seleccionar
fuentes ni decidir si la aserción es cierta.

**Guardas existentes.** El código rechaza dominios que no estén en la entrada, valida los
enums y el JSON Schema, normaliza jurisdicciones redundantes y reintenta solamente los
dominios omitidos o inválidos. El perfil persistido registra el modelo que hizo la
clasificación.

**Tipo de modelo necesario.** Modelo pequeño de clasificación estructurada, rápido y
barato. La especialización deseable es clasificación de autoridad documental y
jurisdicción, no razonamiento general de frontera.

**Riesgo principal.** Confundir un dominio secundario o impostor con una fuente oficial.
El LLM no debe ser la frontera de confianza: allowlists, identidad del dominio, metadatos
firmados y reglas por jurisdicción deben prevalecer sobre su clasificación.

**Configuración encontrada.** La base usa `google/gemini-2.5-flash-lite` vía OpenRouter.

### `api/validate-asertions`

El mismo módulo ejecuta tres tareas epistemológicamente distintas. No deben compararse
como si solo cambiaran de prompt.

#### Tipo 1: `LLM_MEMORY_VALIDATION`

Decide con conocimiento paramétrico y lógica, sin corpus recuperado. El servidor marca la
base del resultado como `MODEL_KNOWLEDGE`. Necesita conocimiento general amplio, buena
calibración y disposición a responder `UNKNOWN`.

Un modelo de frontera puede mejorar el razonamiento, pero no aporta trazabilidad ni
garantiza actualidad. Por eso el peso de consenso predeterminado es `0.25` y no se
recomienda gastar aquí el modelo más caro.

#### Tipo 2: `LLM_SEARCH_VALIDATION`

Solo está implementado para OpenRouter. El código añade `:online` al identificador del
modelo y la búsqueda queda dentro del proveedor. OpenRouter documenta que `:online` activa
su plugin web y que devuelve anotaciones normalizadas de citas, pero el adaptador actual de
Assermetry conserva únicamente `message.content`; no captura `message.annotations`.

Por ello las fuentes declaradas no pueden verificarse contra un corpus controlado y el
resultado se marca `PROVIDER_SEARCH_UNVERIFIED`. Requiere un modelo competente en búsqueda,
síntesis de fuentes y calibración, pero su señal debe seguir pesando menos que RAG. El peso
predeterminado actual es `0.5`.

#### Tipo 3: `RAG_EVIDENCE_VALIDATION`

`source-router` y `evidence-search` obtienen el corpus. El prompt exige usar exclusivamente
los fragmentos entregados y citar sus `context_id`. Después de la inferencia, el servidor
reconstruye las citas desde el corpus y convierte un `TRUE` o `FALSE` sin soporte verificable
en `UNKNOWN`.

**Tipo de modelo necesario.** Modelo de razonamiento sobre evidencia con excelente
entailment: debe distinguir soporte directo, contradicción, contexto insuficiente,
coincidencias parciales y cambios de entidad, fecha, magnitud o jurisdicción. También debe
resistir instrucciones hostiles contenidas dentro de documentos recuperados.

Este es el único uso donde se justifica de forma sistemática el modelo generalista más
fuerte. La especialización más útil sería un segundo clasificador multilingüe entrenado en
NLI/fact verification que puntúe cada par `aserción-fragmento`. No debe sustituir al LLM que
redacta la explicación: debe funcionar como comprobación independiente y provocar
`UNKNOWN` cuando ambos discrepen.

**Configuración encontrada.** Los tres workers local y prod son RAG y usan, vía
OpenRouter, `meta-llama/llama-3.1-8b-instruct`,
`qwen/qwen3-30b-a3b-instruct-2507` y
`mistralai/mistral-small-24b-instruct-2501`. Cada worker cambia además la estrategia de
evidencia (`EXT_ONLY_OFFICIAL`, `EXT_OFFICIAL_FIRST` y `LOCAL`). La diversidad de familias
es positiva para evitar errores correlacionados, pero `mistral-small-2501` figura ya como
retirado en el catálogo actual de Mistral y debe migrarse.

Los tipos 4 (`DETERMINISTIC_VALIDATION`) y 5 (`HUMAN`) no ejecutan inferencia LLM automática.

### Infraestructura compartida y administración

`api/common/llm` abstrae `mistral`, `gemini`, `openrouter` y `grok`, con llamadas síncronas
y asíncronas, reintentos, contabilización de tokens y validación de JSON. No es un cuarto
caso de uso: es la capa de transporte de los anteriores.

OpenRouter recibe `response_format=json_schema`, `strict=true` y
`provider.require_parameters=true` cuando el llamador proporciona un schema. Esto evita
enrutar deliberadamente a endpoints que ignoren el parámetro, aunque la documentación del
proveedor advierte que el cumplimiento exacto puede variar por endpoint.

Hay dos excepciones relevantes: `generate-asertions` no envía ahora el schema por
OpenRouter debido a la incompatibilidad observada, y `validate-asertions` no configura ni
schema ni modo JSON. Sus respuestas se estructuran mediante el prompt y se validan al
volver. Además, el adaptador siempre envía `temperature`; algunos modelos de razonamiento
no anuncian ese parámetro. Todo candidato debe superar primero una prueba de compatibilidad
del payload real, no solo aparecer en el catálogo.

`api/admin` obtiene `/api/v1/models` sin llamar a un LLM. Mantiene un ranking general de
calidad/precio por compatibilidad, pero la vista administrativa principal usa perfiles
curados por carga: extracción, routing, RAG por estrategia, búsqueda y memoria. Combina la
configuración efectiva de cada servicio con el precio vigente del catálogo y calcula el
coste actual, el recomendado y su diferencia sobre una muestra de tokens visible. La
selección sigue siendo un candidato para benchmark, no una decisión automática de
producción: el catálogo no mide entailment, calibración ni calidad con el corpus propio.

## Ponderación de la necesidad de calidad

La puntuación pondera impacto en el resultado (30 %), dificultad de razonamiento y
grounding (25 %), propagación del error (20 %), exigencia de salida estructurada (15 %) y
necesidad de actualidad/búsqueda (10 %). La columna de inversión reparte el esfuerzo de
evaluación y optimización; **no es el peso de voto en el consenso ni una cuota exacta de
coste por tokens**.

| Uso | Puntuación | Inversión orientativa | Nivel recomendado | Especialización |
|---|---:|---:|---|---|
| Validación RAG | 4.45/5 | 35 % | Frontera o gama alta | Sí: entailment/NLI y grounding |
| Generación de aserciones | 4.05/5 | 30 % | Gama media-alta | Sí: extracción y schema estricto |
| Validación con búsqueda online | 3.75/5 | 15 % | Gama media-alta con búsqueda | Sí: búsqueda y síntesis con citas |
| Clasificación de fuentes | 3.40/5 | 15 % | Pequeño/rápido | Sí: clasificación; muchas reglas pueden ser deterministas |
| Validación por memoria | 2.55/5 | 5 % | Gama media | No; priorizar calibración y `UNKNOWN` |

Conclusión: si solo se puede mejorar un modelo, debe ser el de RAG. Si se pueden mejorar
dos, el segundo es `generate-asertions`. El router no debe competir por el mismo presupuesto
de inferencia que esos dos usos.

## Candidatos a evaluar

La lista se basa en los catálogos oficiales consultados en la fecha de revisión. No afirma
que un modelo sea mejor para este proyecto sin ejecutar el benchmark de Assermetry.
OpenRouter permite usar slugs propios; Gemini y Mistral también pueden utilizarse por sus
adaptadores directos. En producción debe fijarse una versión concreta después de la
evaluación, en lugar de depender de alias `latest`.

| Familia/candidato | Papel candidato | Motivo para incluirlo | Precaución |
|---|---|---|---|
| `openai/gpt-6-astra` | RAG premium y juez de referencia | Modelo de máxima capacidad para casos difíciles | Coste/latencia altos; probar schema por OpenRouter |
| `openai/gpt-5.6-sol` | RAG premium | Alternativa fuerte al modelo máximo | Sobredimensionado para router |
| `openai/gpt-5.6-terra` | Generación, RAG equilibrado y búsqueda online | Equilibrio oficial entre capacidad y coste | Medir calibración factual, no inferirla del posicionamiento comercial |
| `openai/gpt-5.6-luna` | Router y generación de alto volumen | Orientado a cargas sensibles a coste | No adoptarlo para RAG sin superar entailment y citas |
| `google/gemini-3.1-pro-preview` | RAG premium y juez de referencia | Familia Pro para razonamiento complejo | Es preview; no fijarlo como único proveedor crítico |
| `google/gemini-3.8-flash` | Generación, router y RAG equilibrado | Flash actual, gran contexto y salida estructurada documentada | Verificar compatibilidad real del schema en el endpoint elegido |
| `google/gemini-3.5-flash-lite` | Router de alto volumen | Variante pequeña para clasificación barata | No asumir que corrige el problema observado con 2.5 Flash-Lite |
| `anthropic/claude-sonnet-5` | RAG premium y diversidad de ensemble | Segunda familia de razonamiento disponible en OpenRouter | Solo vía OpenRouter con el código actual |
| `mistralai/mistral-medium-3-5` | Generación/RAG equilibrado y opción europea | Chat Completions y Structured Outputs oficiales | Evaluar español y entailment con el corpus propio |
| `mistral-small-2603` | Router, memoria y generación económica | Sustituto vigente de la línea Small antigua; salida estructurada | No usar el ahorro como sustituto del benchmark RAG |

Configuraciones iniciales razonables para el benchmark:

- **RAG:** GPT-6 Astra, GPT-5.6 Sol, Gemini 3.1 Pro Preview, Claude Sonnet 5 y
  Mistral Medium 3.5.
- **Generación:** GPT-5.6 Terra, Gemini 3.8 Flash y Mistral Medium 3.5; añadir Luna o
  Mistral Small 4 como baseline económico.
- **Router:** GPT-5.6 Luna, Gemini 3.5 Flash-Lite y Mistral Small 4.
- **Online:** las variantes `:online` de GPT-5.6 Terra, Gemini 3.8 Flash y Claude Sonnet 5,
  después de implementar la captura y persistencia de anotaciones de citas.
- **Memoria:** uno de los modelos equilibrados anteriores, nunca como fuente principal de
  verdad para hechos recientes.

No conviene usar el mismo modelo en todos los validadores: la diversidad de proveedor y
familia reduce fallos correlacionados. Tampoco conviene mezclar en una misma comparación
un cambio de modelo y un cambio de corpus/estrategia de búsqueda, porque no se sabría cuál
explica el resultado.

## Evaluación mínima antes de cambiar modelos

Construir un conjunto versionado en español y otros idiomas soportados, con casos
verdaderos, falsos y genuinamente indeterminados. Debe incluir negaciones, cifras próximas,
fechas, homónimos, cambio de jurisdicción, fuentes en conflicto, fragmentos irrelevantes y
prompt injection dentro de la evidencia.

Medir por tarea:

- **Generación:** validez de schema, precisión y recall de aserciones centrales, atomicidad,
  fidelidad al texto, exactitud de contexto/taxonomía y éxito posterior de recuperación.
- **Router:** precisión por `authority_level`, jurisdicción y tipo de fuente; recall de
  fuentes oficiales; tasa de impostores aceptados; abstenciones y dominios omitidos.
- **RAG:** macro-F1 de `TRUE/FALSE/UNKNOWN`, calibración, precisión de citas, cobertura de
  evidencia decisiva y tasa de veredictos decisivos degradados a `UNKNOWN` por grounding.
- **Online:** exactitud, actualidad, calidad de dominio y porcentaje de citas recuperables.
- **Memoria:** calibración y uso correcto de `UNKNOWN`, separado por antigüedad del hecho.
- **Operación:** p50/p95 de latencia, errores, reintentos, JSON inválido y coste por noticia
  completa, no solo por llamada.

El criterio de promoción debe imponer umbrales, no un promedio único. Para RAG, por
ejemplo, un modelo no debería aprobar si mejora el F1 pero aumenta las citas falsas o los
veredictos decisivos sin soporte.

## Cambios de arquitectura recomendados

1. Añadir un `task` explícito a la configuración (`ASSERTION_EXTRACTION`,
   `SOURCE_CLASSIFICATION`, `RAG_VERDICT`, etc.) y mantener selección de modelo por tarea.
2. Hacer que los tres validadores RAG usen familias distintas y modelos vigentes; conservar
   también estrategias de evidencia distintas, pero evaluarlas por separado.
3. Añadir un verificador NLI multilingüe como segunda señal del RAG. Ante desacuerdo con el
   LLM o evidencia insuficiente, producir `UNKNOWN`, no forzar mayoría.
4. Capturar `message.annotations` y metadatos de búsqueda en `LLMResponse.raw_metadata`;
   validar y persistir las citas del modo online antes de aumentar su peso.
5. Recuperar Structured Outputs para `generate-asertions` vía OpenRouter solo con endpoints
   que lo soporten y mantener siempre la validación Pydantic local.
6. Reemplazar la heurística de calidad de `admin` por filtros de capacidades
   (`structured_outputs`, parámetros requeridos, contexto, versión/retirada) más métricas del
   benchmark propio.
7. Registrar en cada ejecución proveedor, slug exacto/versionado, prompt versionado,
   temperatura, tokens, latencia, estrategia de evidencia y hashes del corpus. Sin ello no
   hay comparación reproducible ni auditoría completa.

## Referencias del repositorio

- [`api/generate-asertions/main.py`](../../api/generate-asertions/main.py)
- [`api/source-router/app/classifier.py`](../../api/source-router/app/classifier.py)
- [`api/validate-asertions/main.py`](../../api/validate-asertions/main.py)
- [`api/common/llm`](../../api/common/llm)
- [`api/admin/main.py`](../../api/admin/main.py)
- [`k8s/apis/generate-asertions/configmap.yaml`](../../k8s/apis/generate-asertions/configmap.yaml)
- [`k8s/apis/source-router/base/configmap.yaml`](../../k8s/apis/source-router/base/configmap.yaml)
- [`k8s/apis/validate-asertions`](../../k8s/apis/validate-asertions)

## Fuentes externas

- [Catálogo oficial de modelos de OpenAI](https://developers.openai.com/api/docs/models)
- [Catálogo oficial de Gemini](https://ai.google.dev/gemini-api/docs/models)
- [Structured Outputs de Gemini](https://ai.google.dev/gemini-api/docs/structured-output)
- [Catálogo oficial de Mistral](https://docs.mistral.ai/models)
- [Structured Outputs de OpenRouter](https://openrouter.ai/docs/guides/features/structured-outputs)
- [Búsqueda web de OpenRouter](https://openrouter.ai/docs/guides/features/plugins/web-search)
- [Catálogo API de OpenRouter](https://openrouter.ai/api/v1/models)
