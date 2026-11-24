# Diseño: cierre por plazo de órdenes con validaciones pendientes

Fecha: 2026-11-21. Estado: implementado en el repositorio; sin despliegue.

## Objetivo y alcance

Cerrar como `VALIDATED_AUTOMATICALLY` una orden que permanece en `VALIDATION_PENDING` tras un plazo configurable, conservando las respuestas recibidas y señalando las que faltaron. El plazo comienza cuando se persiste el inicio de la fase de validación, no al crear la orden: la generación, IPFS y blockchain tienen tiempos y fallos distintos. El cierre no cancela trabajos ya enviados a Kafka, proveedores o blockchain; sus respuestas tardías no modifican la instantánea final.

## Evidencia de la cadena actual

- News Handler guarda `validators`, `validations` y `validators_pending` en MongoDB. Las ramas LIGHT y BLOCKCHAIN de `process_kafka_message` cierran la orden cuando el contador llega a cero: `VALIDATED_WITH_ERRORS` si alguna respuesta tiene `execution_status=ERROR`, `VALIDATED` en caso contrario.
- Gateway autentica y hace proxy de la publicación; no guarda las validaciones ni recibe necesariamente todas sus respuestas. Un temporizador de navegador o de Gateway no cerraría órdenes si esos procesos se reinician.
- La GUI ya considera terminal cualquier estado que empiece por `VALIDATED`, pero `buildVerificationSummary` trata como pendiente cualquier orden en que las respuestas recibidas sean menos que las esperadas. Esto debe distinguirse del cierre por plazo.
- News Handler tiene un consumidor Kafka en segundo plano y actualmente un único pod. El diseño debe seguir siendo seguro si se aumenta el número de réplicas.

## Configuración y propietario del cierre

La propiedad `ORDER_VALIDATION_DEADLINE_MINUTES` en `gateway-config` vale `30` por defecto y admite `0..1440`; `0` deja las órdenes nuevas sin plazo. Gateway elimina cualquier cabecera homónima recibida del cliente y añade `X-Order-Validation-Deadline-Minutes` al reenviar `/orders/publishNew` y `/orders/publishWithAssertions`. News Handler valida y persiste el valor en la orden. Así no hay dependencia entre los ConfigMaps ni se modifica el modelo público de publicación. Los plazos ya persistidos siguen vigentes si después se configura `0`. El cierre se ejecuta exclusivamente en News Handler, donde está el estado persistido.

La orden guarda `validation_started_at`, `validation_deadline_at` (fecha UTC consultable en MongoDB) y el límite efectivo usado. El plazo se fija una sola vez en la transición a `VALIDATION_PENDING`, tanto en LIGHT como en BLOCKCHAIN. Cambiar la propiedad no acorta ni alarga órdenes existentes. Los modelos de entrada de GUI/API no necesitan un nuevo campo; la respuesta de publicación incluye el límite efectivo para que la GUI mantenga el seguimiento antes de que aparezca la fecha de vencimiento en el detalle.

## Motor de vencimiento y transición

1. Un reconciliador periódico de News Handler, por ejemplo cada 30 segundos, consulta por índice `{status: 1, validation_deadline_at: 1}` las órdenes con `status=VALIDATION_PENDING` y plazo vencido. Procesa lotes limitados; tras un reinicio retoma desde MongoDB. La precisión del cierre es el plazo más un ciclo de sondeo.
2. Para cada orden calcula las parejas esperadas `(idAssertion, idValidator)` desde `validators` y resta las respuestas persistidas en `validations`; no confía solo en `validators_pending`, que puede estar desactualizado. Si ya llegaron todas, usa la misma regla de cierre normal. Si faltan respuestas, cierra `VALIDATED_AUTOMATICALLY` con `closure_reason=VALIDATION_DEADLINE_EXCEEDED`, `closed_at`, `unanswered_validations_count` y las parejas ausentes. Conserva las validaciones reales; no inventa resultados `ERROR` ni votos.
3. La transición se hace con una operación condicional atómica sobre la orden. La persistencia de cada respuesta y el cierre normal comparten un único motor de transición y comprueban el estado y una versión de la orden. Ante conflicto se relee y reintenta. Una respuesta que llega tras el cierre se registra como tardía en la auditoría, pero no altera `validations`, cuotas, consenso ni estado. Los efectos secundarios de una respuesta aceptada se ejecutan solo después de confirmar su escritura.
4. El evento de auditoría `validation_deadline_exceeded` registra el límite aplicado, las respuestas recibidas y ausentes y el estado final. Un identificador determinista o índice único evita duplicar el evento si el proceso cae entre el cambio de estado y el registro del evento. No se publica un nuevo resultado de validador.

La regla de cierre normal de LIGHT y BLOCKCHAIN debe extraerse a un único helper; no añadir una tercera implementación independiente del recuento o del estado terminal. Los bloqueos `asyncio.Lock` actuales sirven solo dentro de un proceso y no sustituyen la condición atómica de MongoDB.

## Lectura y presentación

- La API de detalle conserva las respuestas reales y expone la razón del cierre, la hora y el número de respuestas ausentes. `validators_pending` pasa a cero porque la orden ya no espera más respuestas; la diferencia entre esperadas y recibidas queda en `unanswered_validations_count`.
- La GUI muestra un estado final con incidencias y el aviso «Cerrada por plazo; N validaciones no respondieron». Presenta los votos disponibles como resultado parcial e inconcluso cuando corresponda. No muestra «pendiente» ni un consenso completo solo porque el estado empiece por `VALIDATED`.
- Las métricas distinguen `completed`, `error` y `unanswered`; el vencimiento no se cuenta como una respuesta emitida por un validador.

## Órdenes anteriores al cambio

Las órdenes sin `validation_deadline_at` no entran en el reconciliador ordinario. `scripts/operations/backfill_validation_deadlines.py` ofrece una vista previa sin escrituras y un modo `--apply`: deriva el inicio del evento `light_validation_request` o `blockchain_registered`, asigna el plazo con una actualización condicional y deja que el reconciliador cierre las vencidas. Las órdenes sin evento fiable se omiten y se cuentan; no se usa `updated_at` ni `created_at` como sustitutos silenciosos. La migración no se ha ejecutado.

## Verificación de aceptación

1. LIGHT y BLOCKCHAIN: todas las respuestas llegan antes del límite y conservan `VALIDATED` o `VALIDATED_WITH_ERRORS` según los errores reales.
2. Una o varias respuestas faltan: cierre `VALIDATED_AUTOMATICALLY` con resultado parcial, causa y recuentos correctos; sin validaciones sintéticas ni votos inventados.
3. Carrera entre última respuesta y reconciliador: un único estado final estable, un único evento de cierre y cuota cobrada solo por respuestas aceptadas.
4. Respuesta tardía, evento Kafka duplicado, reinicio y dos réplicas: sin reapertura ni doble cargo.
5. GUI: `VALIDATED_AUTOMATICALLY` se traduce como «Completada automáticamente» y «Completed automatically»; `VALIDATED_WITH_ERRORS` como «Completada con errores» y «Completed with errors». Las ausencias son visibles y las órdenes activas siguen mostrando progreso.
6. Vista previa y posterior ejecución controlada de la migración sobre datos históricos antes de afirmar que las órdenes antiguas están cubiertas.
