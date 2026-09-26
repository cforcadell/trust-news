# Collection of historical metrics

`api/stats` contains manual tools for capturing commands and calculating statistics. It is not a test suite, it has no acceptance assertions and is not part of the regression described in [tests.md](tests.md).

## Current status

The scripts retain the historic contract of News Handler:

- URL fija `http://127.0.0.1:8072`;
- calls to `/publishNew`, `/orders/{order_id}` and
`/news/{order_id}/events` without authentication or `client_id`;
- `VALIDATED` status only;
- timestamps with `%m/%d/%Y %H:%M:%S` format and events
  `request_validation`/`validation_completed`.

The current API requires identity and client scope, and its event and date contracts have evolved. That's why `collector.py` and `refetch_orders.py` should not be used against the current deployment without first adapting them. JSONs present in `tests/artifacts/historical-stats` and `tests/resources/historical-stats` are historical samples, not reproducible results of the current version.

## Conserved components

| Script | Historical function | Entrada/salida |
| --- | --- | --- |
| `collector.py` | Post the same text several times and wait `VALIDATED` | Type `tests/artifacts/historical-stats/orders.csv` and a JSON directory in order |
| `refetch_orders.py` | Re-downloading already listed commands | Read `tests/artifacts/historical-stats/orders.csv` and replace `order.json`/`events.json` |
| `stats_report.py` | Calculate aggregates of assertions, votes and times | Read captured JSONs and print tables with `tabulate` |

Before reactivating these tools, authentication, propagation of `client_id`, explicit selection of LIGHT/BLOCKCHAIN, current terminal states, parsing ISO-8601 and support for current events must be added. Then you must work on a new running directory, without overwriting historical samples.

Until such adaptation is made, the valid regression metrics are the dated artifacts produced by `tests/frontend/e2e/run-regression.js`; they record scenario, duration, checks, created commands and errors without being confused with a factual quality test.
