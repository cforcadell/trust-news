# Análisis de modularidad y acoplamiento del repositorio

Fecha: 17 de octubre de 2026. Alcance: código propio versionado de `api/`, `web_classic/`, `smart-contracts/`, `tests/`, `scripts/`, `k8s/` y documentación. Se excluyen dependencias instaladas, artefactos generados y volúmenes de datos. Es una revisión estática: los riesgos de concurrencia y recuperación se deducen del código; no se han reproducido con infraestructura activa.

## Resumen ejecutivo

La base tiene límites útiles: contratos Pydantic compartidos, proveedores LLM y de búsqueda centralizados, utilidades de scoring y evidencia, y `source-router` separado en rutas, servicio, repositorio y reglas. El problema dominante es la concentración de **orquestación y estado mutable** en unos pocos archivos de entrada. Afecta sobre todo a `news-handler`, `evidence-search`, `news-chain` y la interfaz clásica. Hay además una operación de cuotas repartida entre servicios que permite perder actualizaciones concurrentes.

Recomiendo refactorizar por **casos de uso y límites de datos**, dentro de los servicios existentes. No hay evidencia de que añadir microservicios, un framework de eventos nuevo o una jerarquía genérica de repositorios mejore este prototipo.

## Método y mapa del código

Se inventariaron los archivos versionados y se revisaron definiciones, flujos de entrada, acceso a datos, llamadas externas, contratos compartidos, pruebas y despliegue. En Python propio de `api/`, `scripts/` y `tests/` hay 148 archivos y unas 27.526 líneas; esta cifra incluye pruebas y scripts, y sirve solo para dimensionar la revisión. Los focos son `news-handler/main.py` (2.540 líneas), `validate-asertions/main.py` (1.499), `admin/main.py` (1.407), `evidence-search/main.py` (1.350), `news-chain/main.py` (924), `generate-asertions/main.py` (715) y `web_classic/app/js/app.js` (4.698).

| Área | Estado arquitectónico observado | Decisión |
| --- | --- | --- |
| `api/common/models`, `common/llm`, `common/search`, `common/utils/scoring.py`, `common/utils/evidence.py` | Contratos y algoritmos compartidos, con pruebas específicas. | Conservar; ampliar solo ante una duplicación real. |
| `api/source-router/app` | Rutas, servicio, repositorio, clasificación, elegibilidad y ranking separados. | Usar como referencia de separación interna, sin copiar su estructura mecánicamente. |
| `api/news-handler`, `api/evidence-search`, `api/news-chain` | Entrada HTTP, consumidores, reglas, persistencia y clientes externos conviven en `main.py`. | Extraer los flujos de mayor riesgo de forma incremental. |
| `api/validate-asertions`, `api/generate-asertions`, `api/admin` | Responsabilidades reconocibles pero concentradas; configuración de ejecución repetida en dos workers. | Separación selectiva y reutilización de reglas comunes. |
| `web_classic/app/js` | Una aplicación global con funciones sobrescritas y pruebas que extraen texto fuente. | Dividir por pantalla y sustituir pruebas dependientes de posiciones en el archivo. |
| `smart-contracts/contracts/TrustNews.sol`, `k8s/`, `scripts/`, `tests/evaluation/` | No se encontró una necesidad clara de reestructuración general. El contrato concentra un dominio cohesivo; las pruebas de evaluación ya están divididas en `core`, `pipeline` y `viewer`. | Cambiar solo al tocar funcionalidades concretas. |

## Hallazgos priorizados

### P1. Orquestador de órdenes acoplado a transporte, estado y persistencia

**Evidencia.** [`process_kafka_message`](../../api/news-handler/main.py#L804) ocupa unas 650 líneas y bifurca por `action` para generación, IPFS, registro en cadena y validaciones LIGHT/BLOCKCHAIN. En el mismo módulo están los endpoints de publicación, selección de validadores, cuotas, Mongo, Kafka, comprobaciones de consistencia y extracción de artículos. [`update_order`](../../api/news-handler/main.py#L199) acepta tanto campos directos como operadores Mongo y modifica el diccionario recibido con `pop`; los manejadores construyen transiciones mediante actualizaciones dispersas. Las dos ramas de respuesta de validación comparten construcción de instantáneas, guardado, recuento de pendientes y estado terminal ([LIGHT](../../api/news-handler/main.py#L1255), [BLOCKCHAIN](../../api/news-handler/main.py#L1340)).

**Impacto.** Cambiar una transición exige entender el ciclo completo y favorece diferencias accidentales entre modalidades. El `asyncio.Lock` por orden ([línea 705](../../api/news-handler/main.py#L705)) protege dentro de un proceso, pero no constituye una garantía entre réplicas; una actualización de documento completo puede pisar otra. Esto es un riesgo arquitectónico, no una pérdida de datos demostrada.

**Mejora.** Extraer primero manejadores pequeños por evento, manteniendo `main.py` como adaptación HTTP/Kafka. Crear una función de dominio para aplicar una validación y calcular pendientes/estado común a ambas modalidades; conservar las diferencias de payload en adaptadores. Encapsular las operaciones Mongo necesarias detrás de funciones específicas (`guardar_validación`, `marcar_estado`, etc.) y, para actualizaciones concurrentes, usar operaciones atómicas o condición de versión donde proceda. No crear un motor genérico de estados.

### P1. Cuotas: lectura y escritura repartidas con riesgo de sobrescritura

**Evidencia.** [`common/utils/quotas_client.py`](../../api/common/utils/quotas_client.py#L7) expone GET y PATCH de un valor absoluto. `generate-asertions` lee `consumed` y envía `cons_news + 1` ([líneas 642–669](../../api/generate-asertions/main.py#L642)); `news-handler` repite el patrón para generación y validación ([líneas 911–928](../../api/news-handler/main.py#L911), [1373–1376](../../api/news-handler/main.py#L1373), [1942–1992](../../api/news-handler/main.py#L1942)). El PATCH administrativo aplica `$set` al contador ([línea 1319](../../api/admin/main.py#L1319)), mientras el consumidor de cuotas usa `$inc` ([línea 235](../../api/admin/main.py#L235)). Hay, por tanto, varias rutas de actualización y políticas distintas.

**Impacto.** Dos peticiones que lean el mismo valor pueden enviar el mismo incremento y perder uno. La comprobación de límite separada de la escritura también puede admitir consumos concurrentes superiores al límite. El ajuste `+1` seguido de `-1` al publicar aserciones pregeneradas añade un estado transitorio y complejidad.

**Mejora.** Definir en `admin` una operación única de **reservar/consumir cuota** con actualización condicional atómica y clave de operación idempotente. Hacer que ambos workers llamen a esa operación mediante `quotas_client`. Definir una sola regla de cuándo se cobra y cuándo se compensa; migrar cada ruta tras pruebas de concurrencia y reintento. Evitar cambiar la semántica de facturación sin decidirla explícitamente.

### P1. Recuperación del listener de cadena concentrada en un bucle largo

**Evidencia.** [`blockchain_event_listener`](../../api/news-chain/main.py#L532) ocupa unas 245 líneas y mezcla lectura de bloques, decodificación de tres eventos, recuperación IPFS, construcción de mensajes y publicación Kafka. Inicializa `last_block` con la altura actual ([línea 536](../../api/news-chain/main.py#L536)); tras el barrido asigna `last_block = latest` ([línea 770](../../api/news-chain/main.py#L770)). Ante fallos al leer un bloque o procesar un evento, continúa dentro del barrido.

**Impacto.** En un reinicio no existe cursor durable para recuperar bloques ocurridos durante la parada. En un fallo parcial, avanzar hasta `latest` puede dejar eventos sin reintento. La forma actual del bucle dificulta verificar exhaustivamente esos casos.

**Mejora.** Separar `decode_event`, `build_message` y `publish_event` de la iteración de bloques. Persistir un cursor de bloque confirmado después de publicar correctamente todos sus eventos y reanudar desde él; usar identificador `(tx_hash, log_index)` para deduplicar. Añadir pruebas de reinicio, fallo a mitad de bloque y reproducción. Es una mejora de confiabilidad del límite cadena/Kafka, sin necesidad de un servicio nuevo.

### P1. Búsqueda de evidencia en una sola operación de 413 líneas

**Evidencia.** [`search_evidence`](../../api/evidence-search/main.py#L938) prepara política y caché, genera consultas, ejecuta búsquedas, diversifica, aplica fallback, enriquece documentos, construye trazas de evaluación y persiste la respuesta. La lógica de enriquecimiento está además en [`build_evidences_with_optional_contexts`](../../api/evidence-search/main.py#L647), de unas 125 líneas, con bifurcaciones para fetch, ranking, citabilidad y trazas. Ya existen módulos `app/chunker.py`, `chunk_ranker.py` y `document_fetcher.py`, por lo que hay una base modular aprovechable.

**Impacto.** Un cambio de política de búsqueda puede alterar caché, trazas o fallback de forma indirecta. Es difícil probar una etapa en aislamiento sin preparar estado global.

**Mejora.** Extraer el plan de búsqueda, la ejecución/fallback y el ensamblado de respuesta en funciones con entradas y salidas explícitas. Mantener en la ruta validación HTTP y respuesta. Pasar el proveedor, la caché y opciones relevantes como dependencias del flujo, sin generalizar todos los clientes. Conservar las trazas de evaluación como datos opcionales del flujo, verificando que no se almacenen `evaluation_chunks` en caché ([líneas 1288–1294](../../api/evidence-search/main.py#L1288)).

### P2. Frontend global y declaraciones duplicadas

**Evidencia.** [`app.js`](../../web_classic/app/js/app.js#L1) es cargado como script clásico ([`index.html`, línea 251](../../web_classic/app/index.html#L251)) y concentra estado de navegación, solicitudes, polling, presentación de órdenes, explorador y administración LLM. `renderTableData` se declara en [2093](../../web_classic/app/js/app.js#L2093) y [3696](../../web_classic/app/js/app.js#L3696); `renderValidationsTree` en [2016](../../web_classic/app/js/app.js#L2016) y [4183](../../web_classic/app/js/app.js#L4183). Las declaraciones posteriores prevalecen en el mismo ámbito. Varias pruebas unitarias localizan funciones con `source.indexOf` y evalúan fragmentos con `vm.runInContext` ([ejemplo](../../tests/frontend/unit/evidence-links.test.js#L9)), lo que las acopla al orden y formato textual.

**Impacto.** La versión efectiva de una función no es evidente al leer su primera aparición; borrar o editar la equivocada es fácil. El estado global y las pruebas por extracción de texto frenan reutilización y cambios de pantalla.

**Mejora.** Eliminar las definiciones inactivas tras comparar comportamiento. Separar primero lógica pura de órdenes/evidencia y acceso API; después los controladores de pantallas principales. Usar módulos ES nativos o archivos clásicos con un espacio de nombres explícito; mantener un puente pequeño para los `onclick` existentes durante la migración. Probar funciones exportadas o comportamiento DOM real, no fragmentos localizados por texto. No introducir un framework de interfaz solo para dividir este archivo.

### P2. Worker de validación con límites poco explícitos

**Evidencia.** [`validate-asertions/main.py`](../../api/validate-asertions/main.py#L1) combina registro y configuración del validador, API administrativa, listeners LIGHT y cadena, consulta al router/buscador, LLM y publicación. [`validate_payload_v2`](../../api/validate-asertions/main.py#L452) mezcla preparación de evidencia, hash de auditoría, llamada al LLM, interpretación de respuesta y grounding. El uso de `AI_PROVIDER`, `VALIDATOR_TYPE`, `ai_validator` y configuración global complica ejecutar el caso de uso aislado.

**Impacto.** Una modificación de modo de validación puede tocar entrada, decisión y salida a la vez. Se dificulta reutilizar el mismo proceso de validación desde Kafka y cadena.

**Mejora.** Extraer un `validate_assertion` con dependencias inyectables para búsqueda y LLM, y un resultado tipado que ambas entradas adapten. Mantener el grounding en `common/utils/evidence.py`, que ya es compartido. Separar administración/registro solo cuando se trabaje en esos flujos.

### P2. Administración LLM mezcla políticas de recomendación y aplicación de configuración

**Evidencia.** [`admin/main.py`](../../api/admin/main.py#L1) contiene cuotas y clientes, descubrimiento de validadores, persistencia y aplicación de configuración LLM, catálogo OpenRouter y cálculo de recomendaciones. `build_deployed_recommendation` ([línea 505](../../api/admin/main.py#L505)) ocupa unas 113 líneas. `generate-asertions` y `validate-asertions` repiten modelos y validadores de actualización de configuración ([generador](../../api/generate-asertions/main.py#L159), [validador](../../api/validate-asertions/main.py#L164)), aunque los campos extra del validador tienen semántica propia.

**Impacto.** Las reglas de configuración pueden divergir entre workers. El módulo administrativo exige cargar muchas dependencias para probar recomendaciones o cuotas.

**Mejora.** Mover el cálculo puro de recomendaciones a un módulo local y las operaciones de cuotas a otro. Compartir únicamente el contrato base y validaciones idénticas de configuración; dejar extensiones específicas en cada worker. No intentar unificar todos los endpoints administrativos.

### P3. Ruta duplicada en gateway

**Evidencia.** `GET /auth/is-admin` y `check_admin_status` están definidos dos veces en [`gateway/main.py`, líneas 282 y 342](../../api/gateway/main.py#L282). Ambos son registrados en el mismo router incluido por la aplicación ([línea 480](../../api/gateway/main.py#L480)).

**Impacto.** La ruta y el esquema OpenAPI quedan ambiguos para mantenimiento y futuras modificaciones, aunque hoy ambos cuerpos parecen equivalentes.

**Mejora.** Conservar una sola definición y añadir una comprobación simple de unicidad de método/ruta en las pruebas del gateway. Es una corrección pequeña, no un proyecto de refactorización.

## Plan de implementación ordenado

| Orden | Entrega concreta | Comprobación de salida |
| --- | --- | --- |
| 1 | Congelar contratos de eventos/estados y casos de reintento de órdenes. Extraer manejadores de `process_kafka_message` y la aplicación común de validaciones, sin cambiar payloads. | Pruebas de LIGHT y BLOCKCHAIN con duplicados, eventos fuera de orden, error de validador y transición terminal; mismo esquema Kafka/Mongo visible. |
| 2 | Centralizar reserva/consumo de cuotas en `admin`, con escritura condicional e idempotencia, y migrar clientes. | Dos solicitudes concurrentes no pierden incrementos ni superan el límite; reintentar la misma operación no cobra dos veces. |
| 3 | Persistir cursor de `news-chain` y separar decodificación/publicación por evento. | Reinicio y fallo parcial reproducen pendientes sin duplicar efectos. |
| 4 | Dividir `search_evidence` por plan, ejecución y respuesta aprovechando `app/`. | Casos `LOCAL`, `EXT_OFFICIAL_FIRST`, `EXT_ONLY_OFFICIAL`, caché y trazas de evaluación conservan contrato y resultados esperados. |
| 5 | Retirar funciones JS sobrescritas; extraer lógica pura de órdenes/evidencia y luego pantallas. | Pruebas llaman módulos reales; navegación, polling, filtros y representación de evidencia funcionan en pruebas de UI. |
| 6 | Extraer caso de uso del validador y políticas puras de administración. Resolver la ruta duplicada del gateway. | Las entradas LIGHT/cadena producen el mismo resultado de dominio; configuración LLM y recomendaciones mantienen sus contratos; no hay rutas duplicadas. |

Cada entrega debe ser un cambio pequeño y reversible. Antes de mover código, fijar con pruebas el contrato observable correspondiente; después comparar los resultados de las pruebas API, frontend y evaluación que ya existen. El script [`tests/run-local-regression.sh`](../../tests/run-local-regression.sh#L1) cubre parte importante del área API/frontend, pero excluye varias integraciones: la verificación de Kafka, Mongo, IPFS y cadena requiere entornos o dobles de prueba específicos.

## Límites y criterios para evitar sobreingeniería

- No dividir archivos solo por longitud: `source-router` y el contrato Solidity contienen responsabilidades coherentes. La prioridad se basa en acoplamiento, duplicación y consecuencias operativas.
- No mover reglas específicas de un servicio a `common` por comodidad. Compartir solo contratos o algoritmos usados realmente por varios servicios; mantener la lógica de negocio cerca del dueño del dato.
- No rediseñar todos los eventos Kafka ni el modelo de persistencia a la vez. Conservar el contrato externo y migrar una transición cada vez.
- No sustituir el frontend ni cambiar de framework como requisito de modularidad. Módulos y pruebas de comportamiento bastan para el problema observado.
- La revisión es estática. Especialmente en concurrencia de cuotas y recuperación de bloques, las pruebas propuestas deben confirmar el comportamiento antes de cerrar cada hallazgo.
