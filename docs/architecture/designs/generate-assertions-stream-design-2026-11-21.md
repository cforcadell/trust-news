# Diseño: generación progresiva de aserciones

Fecha: 2026-11-21. Estado: diseño; sin implementación ni despliegue.

## Contrato y alcance

- `POST /assertions/generate` del Gateway y `POST /extraer` del generador aceptarán el parámetro de consulta `stream: bool = false`. Sin él, conservarán el JSON, los códigos HTTP y el comportamiento actuales. Un cliente OAuth puede solicitar `stream=true` explícitamente.
- `GUI_STREAM_GEN_ASSERTIONS`, con valor inicial `"false"`, se añadirá a `k8s/apis/gateway/configmap.yaml`. `GET /capabilities` expondrá `gui_stream_gen_assertions` para que la GUI envíe `stream=true` en Generate Assertions y Publish Order. La propiedad solo decide lo que solicita la GUI: no altera el valor por defecto ni activa streaming para otros clientes OAuth.
- `POST /orders/publishNew` también aceptará `stream: bool = false` como parámetro de consulta. La respuesta seguirá siendo `202` con el mismo cuerpo. La opción activa únicamente las vistas preliminares de generación de esa orden; el resto del proceso LIGHT/BLOCKCHAIN sigue igual.
- Se mantienen exactamente los modelos Pydantic de entrada y salida actuales: `TextoEntrada`, `PublishRequest`, `GenerateAssertionsRequest` y su payload, `Assertion`, `AssertionsGeneratedResponse`, `AssertionsNotGeneratedResponse` y `AssertionsDocumentV2`. Los nuevos marcos de transporte y el evento de vista preliminar tendrán contratos separados. En `stream=true`, el último marco HTTP contendrá el `AssertionsGeneratedResponse` actual sin modificar.

## Evidencia y piezas que se reutilizan

| Componente | Funcionamiento actual | Adaptación propuesta |
| --- | --- | --- |
| `api/common/llm` | `LLMRequest` deriva el esquema Pydantic; `acomplete_structured_with_repair` valida el lote y permite una reparación. Los proveedores solo tienen `complete`/`acomplete`. | Extender el proveedor y la factoría comunes con una operación asíncrona de streaming estructurado y la misma validación, reintentos y reparación. No crear otra implementación de extracción en el generador. |
| `api/generate-asertions/main.py` | `/extraer` comprueba cuota, genera el lote y construye una única respuesta; el consumidor Kafka publica un único resultado final. | Usar el mismo prompt, esquema, parser, constructor y respuesta final; emitir vistas preliminares únicamente desde aserciones completas y válidas. |
| `api/gateway/main.py` | `proxy_request` valida el transporte interno y lee toda la respuesta antes de devolver JSON. `/capabilities` ya suministra una propiedad de ejecución a la GUI. | Ampliar el proxy existente para reenviar el flujo sin almacenarlo completo y conservar su autenticación interna. Publicar la propiedad en `/capabilities`. |
| `api/news-handler/main.py` | `publishNew` envía `GenerateAssertionsRequest` a Kafka; `assertions_generated` inicia la cadena LIGHT/BLOCKCHAIN. `GET /orders/{id}` permite sondeo. | Guardar una proyección preliminar separada en la orden; el resultado final actual sigue siendo el único disparador de la cadena. |
| `web_classic/app/js/app.js` | Generate Assertions espera `response.json()`; Publish Order sondea la orden cada 3 s y usa `status` para el estado visual. | Leer marcos progresivos con `fetch` autenticado; mostrar preliminares durante el sondeo y mantener el cambio visual de estado como cierre de Publish Order. |

## Generación directa por HTTP

1. El Gateway valida el token OAuth, calcula `client_id` y construye la URL interna con `stream` tipado. Nunca reenvía un `client_id` proporcionado por el navegador. El generador comprueba la cuota antes de abrir el flujo.
2. Con `stream=false`, se ejecuta exactamente la ruta actual. Con `stream=true`, la respuesta usa `application/x-ndjson`; se consume mediante `fetch` y `ReadableStream`, compatibles con el `Authorization: Bearer` actual. Cada línea es un JSON completo con `type` y `seq`.
3. Los marcos son `start`, `assertion`, `reset`, `complete` y `error`. `assertion` lleva una sola `Assertion` validada y marcada como preliminar; `reset` invalida los preliminares anteriores tras un nuevo intento o reparación; `complete` lleva el `AssertionsGeneratedResponse` existente íntegro y es el **único** indicador de éxito; `error` es terminal. Un cierre de conexión sin `complete` ni `error` es una generación incompleta.
4. La GUI añade filas conforme llegan marcos `assertion`, sin habilitar «Publicar con aserciones» ni presentar un mensaje de éxito mientras sean preliminares. En `complete`, sustituye las filas por `payload.assertions_document.assertions` de la respuesta final, habilita la publicación y muestra un mensaje explícito: «Generación finalizada: N aserciones». Un `error`, timeout o cierre prematuro retira o invalida las filas preliminares y muestra la acción de reintento.
5. Un único parser incremental reutilizable en `common.llm`, parametrizado por el campo lista del `response_model`, acepta solo objetos completos del array `assertions` del JSON estructurado. Decodifica UTF-8 entre chunks, reconoce cadenas y escapes, impone tamaño máximo de buffer y `MAX_ASSERTIONS`, valida cada objeto con `Assertion` y no expone fragmentos. Al terminar, valida el lote completo con `AssertionBatch`, aplica la reparación existente cuando corresponda, llama a `build_generated_document` y emite `complete` con la respuesta final. Los IDs/índices definitivos proceden del documento final; la GUI reemplaza, no concatena, el resultado.
6. La cuota mantiene una sola comprobación y una sola actualización por generación completada, también si hubo reintento o reparación. El error de cuota se devuelve antes del primer marco. Tras abrir el flujo, los errores viajan en `error`, porque ya no puede cambiarse el código HTTP.

## Publish Order por Kafka

1. La GUI añade `?stream=true` a `/orders/publishNew` únicamente si la capacidad está activa; los clientes API que no lo soliciten conservan el flujo actual. `PublishRequest` y el `GenerateAssertionsRequest` enviado a Kafka permanecen idénticos. News Handler transmite la intención en un *header* Kafka (`stream=true`) y deja constancia de ella como metadato operativo de la orden, fuera del documento de aserciones.
2. El trabajador lee el header; ausente equivale a `false`. Si está activo, usa el mismo motor de generación progresiva que `/extraer` y envía eventos `assertion_preview` separados al topic de respuestas. Cada evento contiene `order_id`, un identificador de generación, número de intento, secuencia y una `Assertion` validada. No se emiten `assertions_generated` parciales.
3. News Handler valida el nuevo evento con un modelo de evento propio, deduplica por generación/intento/secuencia y guarda las vistas en `generation_preview`, separadas de `assertions`, `document`, validaciones y estado canónico. Un evento de reinicio limpia la proyección anterior. El registro de eventos guarda solo metadatos de avance, sin duplicar el texto preliminar. Los mensajes de una misma orden, incluidos los de reinicio y el resultado final, llevan clave Kafka `order_id` para conservar su orden; la transición a `ASSERTIONS_REQUESTED` se persiste antes de emitir la solicitud.
4. La GUI obtiene `generation_preview` con el sondeo existente de `/orders/{id}` y muestra cada nueva aserción en la vista de proceso y en la pestaña de aserciones, identificada como «provisional». El polling de tres segundos limita la frecuencia visual; no se agrega un canal WebSocket/SSE para órdenes.
5. Solo el `assertions_generated` final, validado como hoy, sustituye la proyección por `assertions` y `document`, limpia `generation_preview` e inicia IPFS/validación según el modo. `assertions_not_generated` invalida la proyección y conserva el estado terminal `ASSERTIONS_NOT_AVAILABLE`. La GUI conserva su indicador visual de estado para señalar el fin de Publish Order; las filas preliminares nunca se tratan como documento publicado ni como resultado validado.

## Soporte del proveedor y recuperación

- El proveedor común declara si sabe hacer streaming estructurado. Para un proveedor o modelo que no lo soporte, o cuando el proveedor rechace explícitamente el parámetro de streaming **antes de producir contenido**, el motor usa la llamada estructurada actual (`stream=false`). La petición HTTP solicitada como stream conserva sus marcos NDJSON y termina con `complete`; Publish Order conserva el sondeo normal. Registrar el modo efectivo para diagnóstico, sin prompts ni respuestas crudas.
- Si una transmisión falla después de emitir vistas preliminares, se invalidan mediante `reset` antes de un reintento permitido por la política común. Si el error es definitivo, se emite `error` en HTTP o `assertions_not_generated` en Kafka. Una reparación puede reemplazar todas las vistas preliminares; nunca se publicará un subconjunto como resultado final.
- El soporte real de streaming estructurado se probará por proveedor/modelo configurado. La capacidad no se inferirá solo del nombre comercial del modelo. Aunque exista soporte, algunos proveedores pueden entregar el lote en un único chunk: en ese caso la corrección se mantiene y no habrá filas tempranas.
- El proxy del Gateway debe mantener abierta la sesión HTTP interna durante la iteración, cerrar la conexión al cancelar y respetar S03/mTLS. Verificar la transmisión sin buffering de respuesta a través del Ingress. Un `fetch` abortado o un tab cerrado detiene la vista directa; en órdenes publicadas, el procesamiento Kafka continúa y la proyección se recupera al reabrir la orden.

## Pruebas de aceptación antes de activar la propiedad

1. Comparación exacta de esquemas Pydantic y respuestas JSON para `stream=false`, sin cambios en las llamadas OAuth existentes.
2. Flujo HTTP con chunks que parten UTF-8, comillas y objetos; una fila solo tras validar cada objeto completo; `complete` único y obligatorio. Lote vacío, JSON inválido, reparación, reintento, timeout y desconexión.
3. Proveedor/modelo sin streaming: degradación a la ruta estructurada actual, sin doble publicación ni doble cargo de cuota.
4. Publish Order LIGHT y BLOCKCHAIN: proyección parcial visible, orden y deduplicación de eventos, recarga de la GUI, transición final canónica, error tras avances y ausencia de acciones downstream antes del resultado final.
5. `GUI_STREAM_GEN_ASSERTIONS=false`: la GUI y las órdenes se comportan como ahora. Con `true`, ambas acciones de la GUI solicitan stream; una llamada OAuth sin el parámetro permanece en `false` y una con `stream=true` puede optar al flujo.
6. Prueba extremo a extremo a través de Gateway, S03 e Ingress que mida el tiempo del primer objeto completo, la llegada progresiva y la finalización. La disponibilidad del modo no se acreditará solo con pruebas unitarias del parser.

## Límite de la propuesta

Es streaming de entrega y presentación. No cambia el prompt, la selección de aserciones, la calidad del modelo ni la velocidad de cálculo de una noticia. El único documento válido para la cadena sigue siendo el lote completo `AssertionsDocumentV2`.
