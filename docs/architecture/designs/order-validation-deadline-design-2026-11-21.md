# Diseño: cierre por plazo de órdenes con validaciones pendientes

Fecha: 2026-11-21. Estado: propuesta; sin implementación ni despliegue.

## Objetivo y alcance

Cerrar como `VALIDATED_WITH_ERRORS` una orden que permanece en `VALIDATION_PENDING` tras un plazo configurable, conservando las respuestas recibidas y señalando las que faltaron. El plazo comienza cuando se persiste el inicio de la fase de validación, no al crear la orden: la generación, IPFS y blockchain tienen tiempos y fallos distintos. El cierre no cancela trabajos ya enviados a Kafka, proveedores o blockchain; sus respuestas tardías no modifican la instantánea final.

## Evidencia de la cadena actual

- News Handler guarda `validators`, `validations` y `validators_pending` en MongoDB. Las ramas LIGHT y BLOCKCHAIN de `process_kafka_message` cierran la orden cuando el contador llega a cero: `VALIDATED_WITH_ERRORS` si alguna respuesta tiene `execution_status=ERROR`, `VALIDATED` en caso contrario.
- Gateway autentica y hace proxy de la publicación; no guarda las validaciones ni recibe necesariamente todas sus respuestas. Un temporizador de navegador o de Gateway no cerraría órdenes si esos procesos se reinician.
- La GUI ya considera terminal cualquier estado que empiece por `VALIDATED`, pero `buildVerificationSummary` trata como pendiente cualquier orden en que las respuestas recibidas sean menos que las esperadas. Esto debe distinguirse del cierre por plazo.
- News Handler tiene un consumidor Kafka en segundo plano y actualmente un único pod. El diseño debe seguir siendo seguro si se aumenta el número de réplicas.

## Configuración y propietario del cierre

Una sola propiedad `ORDER_VALIDATION_DEADLINE_MINUTES` en `gateway-config` define el límite para órdenes nuevas, por ejemplo `30` como valor inicial **provisional**. Se inyecta la misma clave en el pod de News Handler mediante `configMapKeyRef`; no se crea una segunda configuración ni se confía en un valor enviado por el cliente. La referencia debe usar un nombre de ConfigMap estable en todos los overlays: los manifiestos de Gateway y News Handler se construyen por separado y Kustomize no reescribe referencias entre ellos. News Handler valida un entero dentro de un rango operativo documentado; `0` detiene el reconciliador y evita asignar plazos nuevos, conservando los plazos ya persistidos para una reactivación. Un cambio de ConfigMap requiere desplegar los pods que leen la variable. El cierre se ejecuta exclusivamente en News Handler, donde está el estado persistido.

La orden guarda `validation_started_at`, `validation_deadline_at` (fecha UTC consultable en MongoDB) y el límite efectivo usado. El plazo se fija una sola vez en la transición a `VALIDATION_PENDING`, tanto en LIGHT como en BLOCKCHAIN. Cambiar la propiedad no acorta ni alarga órdenes existentes. El endpoint de publicación y los modelos de entrada de GUI/API no necesitan un nuevo campo.

## Motor de vencimiento y transición

1. Un reconciliador periódico de News Handler, por ejemplo cada 30 segundos, consulta por índice `{status: 1, validation_deadline_at: 1}` las órdenes con `status=VALIDATION_PENDING` y plazo vencido. Procesa lotes limitados; tras un reinicio retoma desde MongoDB. La precisión del cierre es el plazo más un ciclo de sondeo.
2. Para cada orden calcula las parejas esperadas `(idAssertion, idValidator)` desde `validators` y resta las respuestas persistidas en `validations`; no confía solo en `validators_pending`, que puede estar desactualizado. Si ya llegaron todas, usa la misma regla de cierre normal. Si faltan respuestas, cierra `VALIDATED_WITH_ERRORS` con `closure_reason=VALIDATION_DEADLINE_EXCEEDED`, `closed_at`, `unanswered_validations_count` y las parejas ausentes. Conserva las validaciones reales; no inventa resultados `ERROR` ni votos.
3. La transición se hace con una operación condicional atómica sobre la orden. La persistencia de cada respuesta y el cierre normal comparten un único motor de transición y comprueban el estado y una versión de la orden. Ante conflicto se relee y reintenta. Una respuesta que llega tras el cierre se registra como tardía en la auditoría, pero no altera `validations`, cuotas, consenso ni estado. Los efectos secundarios de una respuesta aceptada se ejecutan solo después de confirmar su escritura.
4. El evento de auditoría `validation_deadline_exceeded` registra el límite aplicado, las respuestas recibidas y ausentes y el estado final. Un identificador determinista o índice único evita duplicar el evento si el proceso cae entre el cambio de estado y el registro del evento. No se publica un nuevo resultado de validador.

La regla de cierre normal de LIGHT y BLOCKCHAIN debe extraerse a un único helper; no añadir una tercera implementación independiente del recuento o del estado terminal. Los bloqueos `asyncio.Lock` actuales sirven solo dentro de un proceso y no sustituyen la condición atómica de MongoDB.

## Lectura y presentación

- La API de detalle conserva las respuestas reales y expone la razón del cierre, la hora y el número de respuestas ausentes. `validators_pending` pasa a cero porque la orden ya no espera más respuestas; la diferencia entre esperadas y recibidas queda en `unanswered_validations_count`.
- La GUI muestra un estado final con incidencias y el aviso «Cerrada por plazo; N validaciones no respondieron». Presenta los votos disponibles como resultado parcial e inconcluso cuando corresponda. No muestra «pendiente» ni un consenso completo solo porque el estado empiece por `VALIDATED`.
- Las métricas distinguen `completed`, `error` y `unanswered`; el vencimiento no se cuenta como una respuesta emitida por un validador.

## Órdenes anteriores al cambio

Las órdenes sin `validation_deadline_at` no entran en el reconciliador ordinario. Una migración de una sola ejecución, con vista previa de IDs y recuentos, deriva `validation_started_at` del evento de entrada en validación cuando exista y usa `created_at` solo como último recurso documentado. Aplica el mismo motor de cierre a las órdenes vencidas. No utilizar `updated_at` como inicio: cambia al recibir respuestas y podría prolongar indefinidamente el plazo. La migración debe ser reanudable e idempotente.

## Alternativa complementaria recomendada

El plazo global es una red de seguridad. Para reducir esperas y obtener una causa precisa, cada validador debería tener timeout y reintentos acotados y publicar `execution_status=ERROR` cuando agote su presupuesto. Entonces la orden se cierra por la ruta normal. Mantener ambos niveles: timeout por ejecución y deadline global. Los bloqueos previos a `VALIDATION_PENDING` (generación, IPFS, blockchain) necesitan plazos de fase separados; no deben etiquetarse como validación finalizada.

## Verificación de aceptación

1. LIGHT y BLOCKCHAIN: todas las respuestas llegan antes del límite y conservan `VALIDATED` o `VALIDATED_WITH_ERRORS` según los errores reales.
2. Una o varias respuestas faltan: cierre con resultado parcial, causa y recuentos correctos; sin validaciones sintéticas ni votos inventados.
3. Carrera entre última respuesta y reconciliador: un único estado final estable, un único evento de cierre y cuota cobrada solo por respuestas aceptadas.
4. Respuesta tardía, evento Kafka duplicado, reinicio y dos réplicas: sin reapertura ni doble cargo.
5. GUI: estado final y ausencias visibles en ambos idiomas; las órdenes activas siguen mostrando progreso; los clientes API conservan su contrato de publicación.
6. Prueba de migración sobre copia de datos históricos y despliegue controlado con la propiedad inicialmente desactivada, seguido de activación con el valor de X acordado.
