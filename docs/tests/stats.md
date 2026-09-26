# Recogida de métricas históricas

`api/stats` contiene herramientas manuales para capturar órdenes y calcular
estadísticas. No es una suite de tests, no tiene aserciones de aceptación y no
forma parte de la regresión descrita en [tests.md](tests.md).

## Estado actual

Los scripts conservan el contrato histórico de News Handler:

- URL fija `http://127.0.0.1:8072`;
- llamadas a `/publishNew`, `/orders/{order_id}` y
  `/news/{order_id}/events` sin autenticación ni `client_id`;
- finalización exclusivamente en estado `VALIDATED`;
- timestamps con formato `%m/%d/%Y %H:%M:%S` y eventos
  `request_validation`/`validation_completed`.

El API actual exige identidad y ámbito de cliente, y sus contratos de eventos y
fechas han evolucionado. Por ello `collector.py` y `refetch_orders.py` no deben
usarse contra el despliegue actual sin adaptarlos primero. Los JSON presentes en
`tests/artifacts/historical-stats` y `tests/resources/historical-stats` son muestras históricas, no
resultados reproducibles de la versión actual.

## Componentes conservados

| Script | Función histórica | Entrada/salida |
| --- | --- | --- |
| `collector.py` | Publicar el mismo texto varias veces y esperar `VALIDATED` | Escribe `tests/artifacts/historical-stats/orders.csv` y un directorio JSON por orden |
| `refetch_orders.py` | Volver a descargar órdenes ya enumeradas | Lee `tests/artifacts/historical-stats/orders.csv` y reemplaza `order.json`/`events.json` |
| `stats_report.py` | Calcular agregados de aserciones, votos y tiempos | Lee los JSON capturados e imprime tablas con `tabulate` |

Antes de reactivar estas herramientas debe añadirse autenticación, propagación
del `client_id`, selección explícita de LIGHT/BLOCKCHAIN, estados terminales
actuales, parsing ISO-8601 y soporte para los eventos vigentes. Después deberán
trabajar sobre un directorio de ejecución nuevo, sin sobrescribir las muestras
históricas.

Hasta que se realice esa adaptación, las métricas válidas para regresión son los
artefactos fechados producidos por `tests/frontend/e2e/run-regression.js`; estos
registran escenario, duración, comprobaciones, órdenes creadas y errores sin
confundirse con un test de calidad factual.
