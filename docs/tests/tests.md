# Estrategia y catálogo de pruebas

Este documento ordena las comprobaciones actuales desde las que recorren más
capas del sistema hasta las más locales. Un test situado más arriba aporta más
cobertura de integración, pero suele ser más lento, variable y dependiente del
entorno. Las pruebas locales aíslan mejor una causa y deben ejecutarse antes de
la regresión desplegada.

## Organización

Todas las fuentes de prueba, sus recursos y sus salidas viven bajo `tests/`:

```text
tests/
├── api/                         # suite Python y requisitos
├── frontend/
│   ├── unit/                    # node:test
│   └── e2e/
│       ├── resources/           # casos e identidades
│       └── artifacts/           # informes y capturas de E2E
├── llm-benchmark/
│   ├── resources/               # caso y perfiles versionados
│   └── artifacts/               # SQLite, planes e informes
├── contracts/
│   ├── mocha/                   # pruebas cargadas por Hardhat
│   └── manual/                  # comprobaciones ejecutables con hardhat run
├── operations/                  # sondas operativas de prueba
├── resources/historical-stats/  # muestras históricas de métricas
└── artifacts/                   # caché de pytest y salidas de métricas
```

Los directorios de artefactos se ignoran en Git. Cada ejecutor usa su subcarpeta predeterminada; `ASSERMETRY_ARTIFACTS_DIR` permite sustituirla explícitamente para el E2E.

## Matriz de pruebas

| Nivel | Suite | Alcance real | Dependencias | Entrada principal | Ejecución |
| --- | --- | --- | --- | --- | --- |
| 1 | Regresión GUI LIGHT + BLOCKCHAIN | Chrome, Keycloak, frontend, Gateway, APIs, Kafka, MongoDB, validadores y, en BLOCKCHAIN, IPFS/Ethereum | Despliegue local/Kind completo, Chrome y dos identidades | Noticia sintética multiafirmación sobre Suecia, Alemania, Italia y España | `node tests/frontend/e2e/run-regression.js` |
| 2 | Flujo backend de orden | News Handler y dependencias desplegadas hasta `VALIDATED` | Keycloak, cuotas y backend completo | Noticia sintética de población de Catalunya | `PYTHONPATH=api pytest tests/api/test_news-handler.py` |
| 3 | Integraciones HTTP por servicio | APIs reales de generación, cuotas, IPFS, news-chain y validador | Servicios seleccionados desplegados | Payloads sintéticos específicos | Véase “Integraciones HTTP” |
| 4 | Integración en proceso | Varias capas Python conectadas mediante ASGI, repositorios o dependencias simuladas | Sin despliegue; dependencias Python | Fixtures controladas | Suite local de `pytest` |
| 5 | Contratos y unidades backend | Modelos, routing, evidencia, consenso, seguridad, LLM, URLs y logging | Sólo proceso Python | Fixtures y proveedores simulados | Suite local de `pytest` |
| 6 | Unidades frontend | Funciones de presentación y navegación extraídas de `app.js` | Node.js | Objetos JavaScript controlados | `node --test tests/frontend/unit/*.test.js` |
| 7 | Consistencia estática | Catálogo backend frente a semillas Blockchain y uso de capas compartidas | Sólo repositorio | Archivos versionados | Incluida en la suite local |
| Operación | Persistencia de Loki | Ingesta, consulta y persistencia tras reiniciar Loki | Kubernetes local configurado | Sonda HTTP identificable | `tests/operations/verify-loki-persistence.sh --execute` |

La suite E2E comprueba el recorrido y las invariantes operativas. No usa un
oráculo factual estable: llegar a `VALIDATED` significa que el procesamiento
terminó, no que el veredicto de la noticia sea correcto.

## Benchmark histórico de configuraciones OpenRouter

El batch [llm-benchmark.md](llm-benchmark.md) compara perfiles completos de
generación, routing y validadores mediante una noticia sintética con oráculo
factual. Ejecuta exclusivamente en modo LIGHT, conserva resultados JSON e
indexa calidad, coste y duración en SQLite. Se valida localmente con:

    python3 tests/llm-benchmark/llm-benchmark.py validate-profiles

A diferencia de la regresión E2E, este batch sí puntúa la calidad de extracción
y de los veredictos. Requiere un entorno exclusivo porque cambia temporalmente
la configuración LLM efectiva y la restaura al terminar.

## 1. Regresión E2E desde la GUI

[`tests/frontend/e2e/run-regression.js`](../../tests/frontend/e2e/run-regression.js)
ejecuta secuencialmente dos escenarios mediante Chrome DevTools Protocol:

- [`light.json`](../../tests/frontend/e2e/resources/cases/light.json): exige una orden LIGHT
  terminal, aserciones, validaciones y la pestaña IPFS deshabilitada.
- [`blockchain.json`](../../tests/frontend/e2e/resources/cases/blockchain.json): exige una
  orden BLOCKCHAIN terminal, `cid`, `post_id`, `tx_hash` y la pestaña IPFS.

Los dos escenarios usan actualmente el mismo texto sintético multiafirmación
([`light-news.txt`](../../tests/frontend/e2e/resources/cases/light-news.txt) y
[`blockchain-news.txt`](../../tests/frontend/e2e/resources/cases/blockchain-news.txt)). Es
una noticia con cuatro afirmaciones independientes, relativas a vacunación en
Suecia, transición energética en Alemania, acceso turístico en Italia y
enseñanza de lenguas extranjeras en España. Esos ficheros son la fuente de
verdad de la entrada; el texto documentado actualmente es:

```text
En 2025, Suecia reforzó sus programas públicos de vacunación infantil tras una
recomendación de su autoridad sanitaria. Alemania mantuvo su compromiso de
reducir las emisiones industriales mediante nuevas medidas de transición
energética. Italia prohibió por completo el acceso de turistas a todos sus
centros históricos para proteger el patrimonio cultural. España eliminó la
enseñanza obligatoria de lenguas extranjeras en la educación secundaria.
```

El E2E no fija el número de aserciones extraídas ni el veredicto de cada una:
ambos dependen de los componentes desplegados. Sólo exige los mínimos y los
metadatos de salida definidos por cada caso (`LIGHT` o `BLOCKCHAIN`).

El runner comprueba login, creación y seguimiento de la orden, estado terminal,
estructura de la respuesta, pestañas, errores HTTP/consola y vistas de escritorio
y móvil. La preparación, limpieza, identidades, variables y artefactos están
documentados en
[`tests/frontend/e2e/README.md`](../../tests/frontend/e2e/README.md).

Validar únicamente las definiciones de caso, sin abrir Chrome:

```bash
node tests/frontend/e2e/run-regression.js --validate
```

Ejecutar el E2E, una vez configuradas las credenciales descritas en su README:

```bash
node tests/frontend/e2e/run-regression.js
```

[`ui-smoke-test.js`](../../tests/frontend/e2e/ui-smoke-test.js) también puede
ejecutar un solo caso. Sin `ASSERMETRY_CASE_FILE` usa todo
[`docs/fake_news/news.txt`](../fake_news/news.txt); ese modo es exploratorio y
no sustituye la regresión versionada.

## 2. Flujo E2E del backend

[`test_news-handler.py`](../../tests/api/test_news-handler.py) llama al News
Handler desplegado, crea o restablece cuota, publica una noticia y consulta la
orden hasta `VALIDATED`. Como no envía `validation_mode`, usa el valor por
defecto `BLOCKCHAIN` del contrato actual.

Entrada:

```text
Catalunya tiene una población de más de 7 millones de habitantes de los que
2 millones son niños en edad escolar.
```

Requiere Keycloak, Admin, News Handler, Kafka, generación, validadores, MongoDB,
IPFS y Blockchain disponibles. Tiene un timeout corto y comparte el `order_id`
entre funciones, por lo que debe ejecutarse como fichero completo y en orden:

```bash
PYTHONPATH=api pytest tests/api/test_news-handler.py -q
```

## 3. Integraciones HTTP con servicios desplegados

Estas pruebas realizan tráfico real. No deben mezclarse con la suite local ni
ejecutarse contra producción.

| Fichero | Servicios | Qué comprueba | Entrada |
| --- | --- | --- | --- |
| `test_extraer_integration.py` | Keycloak, Admin y Generate Assertions | Cuotas, `/extraer`, generación y errores 429/cliente ausente | Texto de población y superficie de Catalunya |
| `test_quotas.py` | Keycloak, Admin y Gateway | Publicación dentro de cuota y rechazo al agotarla | Texto sintético de población de Catalunya |
| `test_ipfs_integration.py` | IPFS FastAPI e IPFS | Subida, recuperación por CID y CID inválido | JSON `Documento de prueba` |
| `test_news-chain_integration.py` | news-chain y Ethereum | Publicación/consultas directas con multihashes sintéticos | No usa una noticia; usa hashes de prueba |
| `test_validator_api.py` | validate-asertions y, según tipo, LLM/Blockchain | `/verificar` y registro de validador | `El sol sale por el este` |

Ejecución individual:

```bash
PYTHONPATH=api pytest tests/api/test_extraer_integration.py -q
PYTHONPATH=api pytest tests/api/test_quotas.py -q
PYTHONPATH=api pytest tests/api/test_ipfs_integration.py -q
PYTHONPATH=api pytest tests/api/test_news-chain_integration.py -q
PYTHONPATH=api pytest tests/api/test_validator_api.py -q
```

`test_extraer_integration.py`, `test_ipfs_integration.py`,
`test_news-chain_integration.py` y `test_validator_api.py` llevan el marcador
`integration`. `test_news-handler.py` y `test_quotas.py` también son
integraciones externas, aunque actualmente no están marcadas. Por ello,
`pytest -m "not integration"` no basta para obtener una suite aislada.

Algunas comprobaciones históricas de `test_news-chain_integration.py` aceptan
HTTP 500 cuando la cadena no está disponible. Son sondas de compatibilidad, no
una acreditación E2E ni un criterio fuerte de salud.

## 4. Integración local en proceso

Estas pruebas conectan componentes reales en el mismo proceso y sustituyen los
límites externos por dobles controlados:

- `test_validator_validation_isolation.py`: Gateway → News Handler mediante
  transporte ASGI, con colecciones Mongo simuladas; verifica aislamiento por
  propietario.
- `test_news_handler_document_shape.py`: documento canónico, flujo LIGHT y
  persistencia de pesos congelados.
- `test_validator_source_orchestration.py`: decisiones del validador entre
  Source Router, Evidence Search y estrategias externas.
- `test_source_router.py`: repositorio, discovery simulado, clasificación,
  elegibilidad, perfiles, caché, degradación y ranking.
- `test_evidence_search_units.py`: endpoint de búsqueda con proveedor simulado,
  estrategias, metadata, caché y filtro de fuentes oficiales.

Estas pruebas no acreditan red, DNS, credenciales, Kafka, MongoDB, buscadores o
LLM reales.

## 5. Pruebas locales de backend

El resto de `tests/api` se distribuye así:

| Área | Ficheros |
| --- | --- |
| LLM y extracción | `test_common_llm.py`, `test_llm_json.py`, `test_generate_assertions_units.py` |
| Evidencia | `test_evidence_grounding.py`, `test_evidence_urls.py`, `test_common_search.py` |
| Protocolo y modelos | `test_protocol_v2_models.py`, `test_validation_mode_models.py`, `test_news_handler_document_shape.py` |
| Routing y orquestación | `test_source_router.py`, `test_evidence_search_units.py`, `test_validator_source_orchestration.py` |
| Consenso y validadores | `test_validation_scoring.py`, `test_validator_types_and_scores.py` |
| Seguridad y aislamiento | `test_gateway_jwt_claims.py`, `test_gateway_security.py`, `test_validator_validation_isolation.py` |
| Operación y consistencia | `test_single_line_logging.py`, `test_category_catalog_sync.py` |

Desde la raíz del repositorio, esta selección excluye todos los ficheros que
hacen llamadas a servicios desplegados:

```bash
PYTHONPATH=api pytest tests/api -q \
  --ignore=tests/api/test_extraer_integration.py \
  --ignore=tests/api/test_ipfs_integration.py \
  --ignore=tests/api/test_news-chain_integration.py \
  --ignore=tests/api/test_validator_api.py \
  --ignore=tests/api/test_news-handler.py \
  --ignore=tests/api/test_quotas.py
```

Las dependencias de `tests/api/requirements.txt` cubren pytest y Kafka, pero la
colección importa código de varios servicios. El entorno de pruebas debe incluir
también las dependencias de los servicios afectados. Ejecutar simplemente
`pytest tests/api` implica además disponer de las integraciones externas
anteriores.

## 6. Pruebas unitarias del frontend

Los tests `node:test` no abren navegador ni llaman a APIs:

| Fichero | Responsabilidad |
| --- | --- |
| `assertion-dedup.test.js` | Deduplicación de aserciones en la proyección UI |
| `assertion-status.test.js` | Estado visual de TRUE/FALSE/UNKNOWN |
| `consensus-ui.test.js` | Mensajes de consenso, mayoría e inconclusión en ES/EN |
| `evidence-links.test.js` | Enlaces seguros y separación entre evidencia recuperada/usada/declarada |
| `model-opinion.test.js` | Presentación y escape de opiniones documentales no verificadas |
| `pending-navigation.test.js` | Estados pendientes, polling y conservación de navegación |

Ejecución:

```bash
node --test tests/frontend/unit/*.test.js
```

## 7. Smart contracts y comprobaciones operativas

`npx hardhat compile`, desde `smart-contracts`, comprueba que
`TrustNews.sol` compila. No existe actualmente una suite funcional vigente del
contrato TrustNews. `tests/contracts/mocha/Token.js` es el ejemplo inicial de
Hardhat y referencia un contrato `Token` que ya no existe; no debe usarse como
prueba del sistema ni incluirse en una regresión.

La persistencia de Loki tiene una sonda operativa separada:

```bash
tests/operations/verify-loki-persistence.sh --execute
```

La sonda genera una petición, confirma su ingestión, reinicia Loki y verifica
que el evento permanece. El reinicio es deliberado y el script exige
`--execute`; no forma parte de la suite local habitual.

## Orden recomendado

Para una modificación normal:

1. Ejecutar las unidades del frontend si se tocó `web_classic`.
2. Ejecutar la suite local de backend excluyendo integraciones externas.
3. Ejecutar las integraciones HTTP de los servicios afectados.
4. Validar las definiciones E2E con `run-regression.js --validate`.
5. Ejecutar la regresión GUI LIGHT + BLOCKCHAIN sobre el despliegue.
6. Usar sondas operativas sólo cuando cambie la infraestructura correspondiente.

Un resultado debe indicar siempre qué nivel se ejecutó. “Tests en verde” sin la
suite y el entorno no distingue unidades locales de una validación E2E.
