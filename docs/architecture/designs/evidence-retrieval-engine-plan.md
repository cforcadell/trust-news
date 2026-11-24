# Motor de obtención de evidencias: plan y bitácora

Estado: **en implementación**. Rama de trabajo: `postTFM`.

## Objetivo y principios

Convertir la obtención de documentos de Evidence Search en un motor genérico que
pueda usar texto completo devuelto por un buscador, descarga HTTP propia o un
extractor externo de una URL conocida, según una política explícita. Toda ruta
debe desembocar en el chunker, ranker, contextos citables, validador RAG,
auditoría de citas, viewers y evaluadores existentes.

- Un snippet/highlight orienta la selección; no se presume documento completo.
- `citation_eligible` significa contexto recuperado, íntegro y permitido por la
  política. No significa autenticidad de la web ni apoyo semántico a la aserción.
- El instante de recepción local no se presenta como fecha de rastreo del
  proveedor. Vigencia desconocida sigue siendo desconocida.
- Un fallo de HTTP local no invalida automáticamente una copia válida obtenida
  por otro método; cada intento mantiene su propio diagnóstico.
- La búsqueda escala por insuficiencia de candidatos útiles; un fallo de
  extracción de una URL se recupera primero en la capa de extracción.
- La implementación debe ser un motor de ejecución configurable, sin lógica
  especializada para aserciones, dominios ni proveedores concretos.

## Flujo objetivo

1. Search Provider descubre candidatos y devuelve contenido tipado, metadatos
   de procedencia y `provider_call_id`.
2. El planificador selecciona una tanda pequeña y diversa. Conserva una reserva
   de candidatos sin hacer HTTP adicional al buscador.
3. `DocumentAcquisitionEngine` aplica `ExtractionPolicy` a cada candidato:
   texto completo incluido en Search, HTTP directo y, cuando exista adaptador,
   extracción externa por URL. Registra intentos y decisión.
4. Un `AcquiredDocument` común entrega texto al chunker y ranker existentes.
5. Contextos citables guardan procedencia y hash de documento; la auditoría
   mantiene IDs y hash del contenido entregado al validador.
6. Los viewers muestran procedencia, vigencia y ruta de recuperación. Evaluadores
   calculan calidad, coste, cobertura y trazabilidad por método.

## Contratos propuestos

`AcquiredDocument`: `requested_url`, `resolved_url`, `method`, `provider`,
`provider_call_ids`, `text`, `text_sha256`, `received_at`,
`source_fetched_at` (opcional), `freshness_status`, `content_type`,
`attempts`, `status`, `failure`. El texto completo no se incluye en trazas de
coste; se conserva en un almacén de documentos si se implementa replay por URL.

`ExtractionPolicy`: `mode` (`DIRECT`, `PROVIDER`, `SMART`),
`min_document_chars`, `require_known_freshness`, `max_content_age_seconds`,
`allow_provider_extract`, `initial_batch_size`, límites de tiempo y coste.
Las opciones se versionan en la clave de caché. `DIRECT` conserva la conducta
actual; `SMART` usa texto completo del proveedor cuando la política lo admite.

La respuesta `evidence-search-response-v2` se amplía de forma aditiva. Cada
evidencia conserva campos legacy de HTTP y añade `document_provenance` y
`acquisition_attempts`. Cada contexto conserva `source_id`, `context_id`,
`text_sha256`, `citation_eligible` y añade referencia al documento. El hash de
bundle v1 sigue legible para replay histórico; una versión v2 incorporará la
procedencia y el hash del documento para nuevas ejecuciones.

## Fases y criterios de aceptación

### Fase 1. Motor y procedencia

- [x] Normalizar correctamente texto completo frente a snippets/highlights en
      los adaptadores de búsqueda.
- [x] Motor genérico con política `DIRECT`/`PROVIDER`/`SMART`, clasificación de
      calidad y vigencia, y diagnósticos por intento.
- [x] Usar el mismo chunker/ranker/ventanas con cualquier método.
- [x] Preservar la extracción directa como modo por defecto y activar SMART
      mediante configuración versionada; la planificación inicial sí cambia
      al tamaño progresivo configurado.
- [x] Pruebas de texto válido, snippet insuficiente, bloqueo HTTP, vigencia
      desconocida y trazabilidad.

### Fase 2. Planificación y recuperación

- [x] Obtener candidatos en tandas progresivas; detener al alcanzar el objetivo
      citable sin procesar toda la primera reserva.
- [x] Adaptador opcional para extraer por URL con el proveedor, sujeto a límites.
- [x] La escalada Lite→Auto responde a falta de fuentes útiles tras agotar
      obtención de candidatos, no solo a fallos del HTTP propio.
- [x] Caché documental por URL, versión de contenido y método; historial
      negativo de HTTP directo separado de resultados del proveedor.
      Compatibilidad con caché de aserciones.

### Fase 3. Cadena de auditoría y observabilidad

- [x] Bundle hash v2, handoff y replay con procedencia; lectura de v1.
- [x] `retrieval_summary` separa HTTP local, textos de Search y extracción por URL.
- [x] Coste estimado por llamada y coste observado por fuente citable, sin
      confundir tarifa configurada con factura del proveedor.
- [x] Viewer web y viewer diagnóstico muestran método y vigencia; el objeto
      público `evidence_used` transporta la procedencia canónica del servidor.
- [x] Evaluadores miden cobertura, vigencia, citas, fallos, latencia y coste por
      método; pruebas de contrato y replay.

### Fase 4. Despliegue y comparación

- [x] Ejecución en sombra o bandera de configuración, sin cambiar por sorpresa
      las evidencias de producción.
- [ ] Comparar DIRECT y SMART sobre el mismo corpus representativo: fuentes
      citables y vigentes, calidad del veredicto, citas válidas, latencia y coste.
- [ ] Activar SMART solo tras revisar resultados y documentación operativa.

## Bitácora de avance

### 2026-10-29 — Corrección de lectura HTTP comprimida

- El descargador reconstruye la respuesta a partir de bytes que HTTPX ya ha
  descomprimido. Elimina `Content-Encoding`, `Content-Length` y
  `Transfer-Encoding` de esa copia para evitar una segunda descompresión y el
  `DecodingError` observado en la orden `98e5b32b-f47a-41ea-b27f-37277e0b0375`.
  El límite de tamaño sigue midiéndose sobre los bytes descomprimidos.
- Pruebas nuevas cubren gzip y deflate tras una redirección, y el rechazo de
  contenido comprimido cuyo tamaño descomprimido supera el límite. Pasan las
  5 pruebas dirigidas de streaming; la suite afectada registra **177 pasadas y
  17 excluidas** por las divergencias previas del descargador. `git diff --check`
  pasa. Falta desplegar y repetir la campaña para medir el efecto en veredictos.

### 2026-10-29 — Protección de documentos y concurrencia acotada

- El descargador HTTP lee en streaming y detiene respuestas no PDF al superar
  `EVIDENCE_MAX_DOCUMENT_BYTES` (4 MiB por defecto); PDF conserva su límite
  de 15 MiB. Las respuestas con `Content-Length` excesivo se rechazan antes
  de leer el cuerpo. El rechazo `DOCUMENT_TOO_LARGE` queda en los intentos y
  permite probar otra fuente. Los dobles HTTP sin streaming conservan además
  un control después de la descarga.
- `EVIDENCE_MAX_DOCUMENT_CHARS` (1 millón por defecto) limita cualquier texto
  que entre al chunker, también el procedente de Search, extracción por URL o
  caché. Ambos límites forman parte de la clave de caché de respuesta.
- El troceado de frases extensas avanza por índice, sin copiar repetidamente el
  resto del documento; chunking y ranking pasan a un hilo auxiliar para no
  bloquear las sondas ni otras peticiones del servidor.
- El consumidor Kafka del validador acepta `LIGHT_VALIDATION_MAX_IN_FLIGHT`;
  por defecto sigue en 1 y el overlay LOCAL configura 3. Las tareas se esperan
  durante el cierre. El comportamiento previo de auto-commit de Kafka no se
  ha cambiado; antes de usar concurrencia alta con varios consumidores se
  debe revisar la semántica de reintentos y entrega.
- El segundo intento del clasificador de Source Router envía solo los dominios
  aún pendientes, conservando la firma de ruta y el feedback de validación.
- `/extraer` registra duración de lectura/actualización de cuota, construcción
  de petición, llamada estructurada y parseo, además de uso y reparación, sin
  registrar el texto del usuario. Es observabilidad: el modelo y el prompt
  siguen iguales hasta contar con una comparación de calidad/latencia.
- Evidence Search se declara con 2 réplicas, recursos y sondas explícitas en
  el manifiesto base. No se ha desplegado esta tanda ni repetido un E2E; no
  hay mejora de latencia medida todavía.
- Verificación: 174 pruebas afectadas pasan y 17 pruebas previas del
  descargador permanecen excluidas por las divergencias ya documentadas;
  39 pruebas del Router pasan y 2 pruebas HTTP del Router se excluyen porque
  se quedan bloqueadas en este entorno (no se contabilizan como aprobadas).
  Las 20 pruebas JS del viewer, `git diff --check`, compilación Python y YAML
  de los manifiestos modificados: correctos.


### 2026-10-29 — Diagnóstico de la campaña DIRECT y timeout de Router

- La campaña `e2e-20261029-185623` terminó con 33 errores técnicos: la primera
  orden perdió la conexión TLS durante el sondeo y las 32 restantes no pudieron
  conectar con Keycloak al desaparecer el port-forward 7443. No produjo una
  comparación válida con SMART.
- El worker LOCAL sí recibió órdenes, pero `resolve_local_sources` esperaba solo
  30 s. Source Router completó la búsqueda y clasificación de una ruta después
  de ese plazo; el worker respondió con `SOURCE_ROUTER`/`ReadTimeout` antes de
  invocar Evidence Search.
- El plazo es ahora configurable mediante `SOURCE_ROUTER_TIMEOUT_SECONDS` (180 s
  por defecto y en el ConfigMap). La prueba de orquestación comprueba que el
  valor configurado llega a la petición HTTP: **30 pruebas pasan**.
- La captura fría se había aplicado solo al worker 1. Para repetir la campaña,
  `EVALUATION_CAPTURE_COLD=true` debe estar en los tres ConfigMaps de validación
  y `EVALUATION_ALLOW_COLD=true` en Router y Evidence Search. Las banderas
  temporales de esta tentativa se restauraron al terminar; falta desplegar la
  imagen del validador con el nuevo timeout y mantener un túnel 7443 estable.

### 2026-10-28 — Subfase 2A: capacidad de extracción por URL

- `SearchProvider.extract(url)` es una capacidad opcional con resultado tipado;
  el motor invoca el adaptador mediante `extract_with_provider`, sin ramas de
  negocio específicas por proveedor.
- Exa Contents solicita texto completo y, si se exige lectura en vivo,
  `maxAgeHours=0`. Se inspecciona `statuses` por URL; una respuesta HTTP 200
  con estado fallido no produce documento. En política estricta solo se admite
  `source=live`; una procedencia ausente o en caché queda sin garantía de frescura.
- Tavily Extract solicita formato texto y uso en créditos; se inspeccionan
  `results` y `failed_results` por URL. La política de lectura en vivo se
  declara no soportada antes de llamar a la API porque el endpoint no aporta
  la garantía requerida.
- Pruebas de contrato de ambos adaptadores: **17 pasan** en
  `tests/api/test_common_search.py`, incluidos fallos por URL con HTTP 200.
- La conexión, presupuesto y validación se completaron en la subfase 2B.

### 2026-10-28 — Subfase 2B: integración y diagnóstico por método

- SMART prueba texto completo de Search, luego HTTP directo y, solo tras fallo
  directo, extracción por URL si `EVIDENCE_ALLOW_PROVIDER_EXTRACT=true`.
  PROVIDER puede utilizar Search y extracción por URL sin intentar HTTP propio.
  El ConfigMap conserva DIRECT y la nueva ruta desactivada.
- `EVIDENCE_MAX_PROVIDER_EXTRACT_CALLS=2` limita las llamadas externas de
  extracción por petición, compartiendo presupuesto entre tanda inicial,
  reserva y escaladas. Antes de enviar la URL al proveedor se exige URL HTTP
  pública mediante el validador del descargador.
- El resultado externo pasa por los mismos controles de longitud, página de
  bloqueo, chunker, ranker y contexto citable. Las llamadas registran duración,
  ID, coste USD si el proveedor lo informa y uso si lo informa. La traza de
  Search sigue separada de la traza de extracción.
- Se conserva el estado de HTTP directo aunque el proveedor recupere el texto.
  El historial negativo de URL usa exclusivamente el resultado HTTP directo;
  un 403 no se borra por éxito del proveedor.
- `retrieval_summary` separa documentos por método, llamadas de extracción,
  coste informado, fallos HTTP recuperados y vigencia desconocida. Las nuevas
  claves están en el modelo de respuesta para mantener el contrato estricto.
- Pruebas de búsqueda y Evidence Search: **75 pasan, 17 excluidas** por los
  fallos preexistentes del descargador descritos más abajo. Dos pruebas nuevas
  cubren recuperación tras 403, presupuesto y URL insegura.
- Siguiente subfase: caché documental versionada y métricas de coste del
  viewer/evaluadores. Una copia de proveedor con vigencia `UNKNOWN` nunca se
  convertirá en `OBSERVED_NOW` por estar en caché.

### 2026-10-28 — Subfase 2C: instantáneas y reutilización controlada

- Añadida `evidence_document_snapshots_v1`: cada instantánea guarda texto
  íntegro, URL normalizada, método, proveedor, SHA-256 y fecha de recepción.
  Su ID depende de esos valores; una versión nueva de la misma URL conserva
  otro ID. TTL independiente de la caché de respuestas: 7 días por defecto.
  Se omiten documentos de más de 8 MiB para respetar el límite de MongoDB.
- La reutilización está desactivada (`EVIDENCE_DOCUMENT_REUSE_MAX_AGE_SECONDS=0`).
  Si se configura una edad máxima positiva, el motor lee una instantánea
  íntegra antes de repetir HTTP o extracción por URL. Una copia se marca
  `document_cache` y `CACHED_KNOWN_AGE`, con fecha de la lectura original;
  nunca se etiqueta como lectura actual. La política estricta solo acepta
  copias que inicialmente tenían observación en vivo y aún están dentro del
  plazo configurado. El historial negativo sigue separado por método.
- `document_provenance.snapshot_id` se vincula al bundle hash v2; el texto
  queda en Mongo para auditar el hash. Una lectura detecta alteración del
  contenido antes de reutilizarlo. Si Mongo falla, la búsqueda sigue por
  rutas de obtención normales y el fallo se registra.
- Pruebas dirigidas de instantáneas: **2 pasan**; de búsqueda, Evidence Search,
  grounding y replay: **106 pasan, 17 excluidas** por las divergencias del
  descargador ya registradas.
- Límite pendiente: una instantánea de >8 MiB conserva el hash en la respuesta
  pero no el texto completo; se debe exponer `snapshot_id=null` y tratarla
  como no auditable mediante almacén. La política de retención se debe ajustar
  a la duración real de los artefactos de evaluación.

### 2026-10-28 — Subfase 3A: evaluación y costes por ruta

- El evaluador de Retrieval expone documentos por método, copias con vigencia
  desconocida, llamadas de extracción y fallos HTTP recuperados por proveedor.
  Mantiene las métricas de cobertura lexical, citas y latencia ya existentes.
- El ledger del viewer genera un evento separado por llamada real de
  `provider_extract`; no carga de nuevo las llamadas históricas cuando la
  respuesta procede de caché. `costDollars.total` de Exa se etiqueta
  `PROVIDER_ESTIMATE` porque el propio contrato lo describe como estimado.
  Los créditos de Tavily solo se convierten en USD cuando la campaña declara
  `extract[].usd_per_credit`; si no, el coste queda desconocido. También se
  puede declarar `usd_per_call`. El agregado `search_cost_usd` suma búsqueda y
  extracción externa, y el desglose por componente conserva ambas rutas.
- Pruebas de costes y viewer: **33 pasan**, con un test previo excluido que
  espera dos validadores cuando el fixture contiene tres. Las pruebas nuevas
  cubren estimación de Exa, créditos de Tavily y lectura de caché.
- Pendiente: comparación DIRECT/SMART en corpus representativo y decisión de
  activación. No se ha cambiado la política de producción.

### 2026-10-28 — Subfase 4A: comparador de campañas

- `evaluation.pipeline.compare_modes` acepta dos campañas guardadas y empareja
  ejecuciones por dataset, caso, texto de aserción, validador, configuración y
  estrategia. Rechaza como `INCOMPLETE` una comparación con aserciones
  distintas, repeticiones desiguales, caché de respuesta, tarifas diferentes
  o modos no declarados. La respuesta de Evidence Search ahora incluye
  `extraction_policy`, de modo que el comparador exige DIRECT en la campaña
  base y SMART en la candidata.
- Presenta por modo y diferencia SMART−DIRECT: fuentes citables, cobertura de
  referencia, corrección de veredicto, citas verificadas/rechazadas, latencia
  de Retrieval si existe, HTTP, llamadas Search/Extract, coste informado de
  extracción, vigencia desconocida y fallos HTTP recuperados. Incluye los
  costes de campaña del viewer con su desglose, sin extrapolar los datos que
  no existen en artefactos antiguos.
- El resumen de Retrieval deja el coste de extracción en `null` si una
  llamada no informa precio; calcula coste informado por fuente citable solo
  cuando todas las llamadas de extracción tienen coste conocido. El ledger
  marca errores de proveedor como facturación desconocida, incluso si existe
  una tarifa por llamada.
- El viewer web muestra explícitamente `provider_extract` y `document_cache`,
  incluyendo la marca de copia con antigüedad conocida. No confunde esa copia
  con una respuesta observada en el instante actual.
- Prueba sintética del comparador: **1 pasa**. Falta ejecutar dos campañas
  reales con el mismo corpus y configuraciones de servicio DIRECT y SMART;
  la bandera SMART continúa desactivada en el ConfigMap.

Ejemplo de comparación, tras guardar dos campañas completas de respuesta fría:

```bash
PYTHONPATH=api:tests .venv/bin/python -m evaluation.pipeline.compare_modes \
  tests/data/evaluation/artifacts/<campana-direct> \
  tests/data/evaluation/artifacts/<campana-smart> \
  --output tests/data/evaluation/artifacts/evidence-mode-comparison.json
```

### 2026-10-28 — Intento de E2E solicitado

- Se ejecutó `bash launch_e2e.sh` después de completar la implementación
  local. Terminó con código 1: el manifiesto de
  `tests/data/evaluation/artifacts/e2e-20261028-201350` indica
  `COMPLETED_WITH_ERRORS`, 33 ejecuciones y 33 fallos técnicos en
  `AUTHENTICATION` con `AUTHENTICATION_ERROR`. El informe está en `report.md`.
- Ninguna ejecución alcanzó Retrieval; este E2E no verifica el motor nuevo.
  El script prueba los servicios desplegados, que además deben incorporar
  estos cambios antes de que la comparación DIRECT/SMART sea representativa.
  No se registra ningún resultado de calidad como si fuese una validación.
- Investigación posterior con llamadas locales: el motivo real de las 33
  ejecuciones fue `[Errno 1] Operation not permitted` al abrir el socket
  desde el sandbox; no fue una respuesta HTTP 401 ni 403. Fuera del sandbox,
  8074 y 8075 aceptaban TCP, pero 7443 devolvía `Connection refused` porque
  no había port-forward activo. Se abrió un túnel temporal `7443:443` hacia
  Traefik: OIDC, gateway, Evidence Search y Source Router respondieron HTTP
  200 en sus metadatos/OpenAPI. El `TokenProvider` real obtuvo un token con
  validez de 300 s; un GET autenticado a una orden inexistente pasó la
  autenticación y devolvió 404. El túnel se cerró después.
- Para repetir el E2E se necesita el port-forward 7443 y ejecutar las
  llamadas fuera del sandbox con acceso a red local. Las credenciales
  existentes funcionaron en la prueba localizada. Después de desplegar el
  código nuevo, ejecutar dos campañas frías y el comparador.

### 2026-10-28 — Verificación local final de esta tanda

- Suite Python afectada: **165 pasan, 18 excluidas**. Las exclusiones son las
  17 pruebas preexistentes del descargador y la expectativa legacy de costes
  detalladas antes; no se presentaron como pruebas superadas.
- Viewer web: **20 pasan**. `node --check` en `app.js` e `i18n.js`, compilación
  Python de los módulos nuevos y `git diff --check`: correctos.
- La implementación de código y contratos queda terminada; la decisión de
  activar SMART permanece pendiente de las dos campañas comparables y de un
  E2E con autenticación operativa.

### 2026-10-28 — Inicio

- Revisados `api/evidence-search/main.py`, adaptadores de Exa/Tavily,
  `api/common/utils/evidence.py`, bundle hash, viewer web y evaluadores.
- Diagnóstico: la búsqueda ya puede traer texto, pero `build_evidences_with_optional_contexts`
  siempre llama a `fetch_main_text` cuando se habilita texto completo. El límite
  de proveedor es 10 resultados; el presupuesto interno puede ser 30.
- Diagnóstico adicional: con `max_results=10` y objetivo citable 1 se pueden
  programar hasta 8 candidatos al inicio. La métrica de costes del viewer ya
  estima llamadas a partir de `provider_trace`, con tarifas configuradas.
- Próximo paso: implementar Fase 1 sin modificar todavía la política activa.

### 2026-10-28 — Primer corte funcional

- Añadido `app/acquisition.py`: política genérica `DIRECT`/`PROVIDER`/`SMART`,
  decisión entre texto completo de Search y HTTP directo, diagnóstico de intentos,
  hash de documento y estado de vigencia. `DIRECT` queda como modo por defecto
  y en el ConfigMap; `SMART` se activa mediante `EVIDENCE_EXTRACTION_MODE`.
- Exa conserva `raw_content` aunque coincida con el excerpt. `content` y
  `highlights` solos nunca se consideran documento completo.
- `build_evidences_with_optional_contexts` procesa ambos métodos con el mismo
  chunker, ranker y ventanas; añade `document_provenance`, origen del contexto
  y hash del documento. `retrieval_summary` incorpora contadores por método.
- El historial negativo por URL no interpreta una copia del proveedor como
  éxito o fallo de acceso HTTP directo.
- Pruebas dirigidas: 4 pasan (`smart_acquisition`, igualdad de texto Exa y
  compatibilidad de contexto directo).
- Al ejecutar las dos suites API completas: 63 pasan y 17 fallan en pruebas
  preexistentes del descargador. Los fallos observados usan dobles `Client.get`
  sin el argumento `follow_redirects=False`, o esperan otra validación de URL.
  No se ha modificado `document_fetcher.py`; conviene resolver esa divergencia
  por separado antes de usar la suite completa como puerta de despliegue.
- Pendiente inmediato: ampliar pruebas de snippet y bloqueo, ajustar el
  planificador progresivo y propagar procedencia al objeto público de citas.

### 2026-10-28 — Tanda progresiva y handoff de procedencia

- `EVIDENCE_INITIAL_BATCH_SIZE=2` limita la primera tanda; la reserva existente
  sigue suministrando candidatos hasta alcanzar el objetivo o el presupuesto.
  Cuando se desactiva el enriquecimiento de texto, se siguen entregando hasta
  `max_results` URLs porque no habrá reposición por citabilidad.
  Se incluye en la clave de caché para no reutilizar respuestas previas.
- El bundle v1 se mantiene. Un hash v2 adicional vincula IDs, texto entregado,
  origen del contexto y metadatos de procedencia. **El hash v2 vincula la
  declaración de hash de documento, pero no sustituye conservar/verificar el
  texto completo original**, todavía pendiente en la caché documental.
- El validador persiste ambos hashes de handoff. Los evaluadores comprueban
  ambos cuando existen y pueden leer artefactos legacy con solo v1. Replay
  rechaza alteraciones de procedencia incluso si el texto citado no cambia.
- `evidence_used` copia la procedencia canónica del servidor. El viewer web
  presenta método y vigencia; el viewer diagnóstico la incorpora en cada
  contexto observado. Métricas de evaluación incluyen documentos de Search,
  directos y textos rechazados.
- Pruebas dirigidas de búsqueda/grounding/evaluación: 123 pasan con 17 pruebas
  del descargador excluidas por la divergencia previa. Otras suites de
  reporting/orquestación: 59 pasan y falla un test de costes que espera dos
  validadores cuando `order_costs` devuelve tres; `viewer/costs.py` no fue
  modificado en este trabajo. Sintaxis JS y `git diff --check`: correctos.
- Próximo paso: adaptadores de extracción por URL y caché documental. La
  política SMART sigue desactivada en el ConfigMap (`DIRECT`).

### 2026-10-28 — Comprobación y punto de reanudación

- El motor rechaza una URL inválida y páginas de bloqueo devueltas como
  `raw_content`, aplicando el mismo detector de bloqueo del descargador.
  Pruebas nuevas cubren snippet sin documento, bloqueo, política estricta de
  frescura y 403 directo. La secuencia no convierte una copia de vigencia
  desconocida en citable cuando se exige frescura conocida.
- Pruebas de las rutas modificadas: 123 pasaron con 17 pruebas del descargador
  excluidas; `test_evidence_grounding`, `test_execution`, `test_viewer_build` y
  `test_viewer_contract` pasaron (54). `test_reporting` y orquestación del
  validador pasaron tras verificar simultáneamente los hashes v1 y v2.
- `node --check` de `app.js` e `i18n.js` y `git diff --check`: sin errores.
- Otros límites observados: un test de costes no modificado falla por esperar
  dos grupos de validadores donde `order_costs` devuelve tres. Un test del
  servidor HTTP del viewer no puede abrir un socket local en este sandbox
  (`PermissionError`); sus pruebas de construcción y contrato sí pasan.
- El test real de renderizado `node tests/frontend/unit/evidence-links.test.js`
  pasa (19 pruebas), incluida la nueva comprobación de procedencia y vigencia
  para una evidencia recuperada no usada. Su harness se actualizó para cargar
  la nueva función de la interfaz.
- Verificación final de las suites Python afectadas, excluyendo las 17 pruebas
  del descargador ya descritas: **176 pasaron**. `git diff --check` y la sintaxis
  de ambos ficheros JS siguen correctos.
- El modo SMART **todavía no debe activarse por defecto**: falta extracción
  gestionada por URL, caché documental, medición de uso real y comparación
  en corpus representativo. El ConfigMap conserva DIRECT.

#### Continuación concreta

1. Leer `git status --short` y esta bitácora. No restaurar cambios ajenos.
2. Ejecutar la suite Python afectada, los 19 tests JS y `git diff --check`.
   Última ejecución: 164 pasaron, 18 excluidos (17 del descargador y 1 coste
   legacy); después se corrigió una expectativa del resumen y pasaron sus 2
   pruebas dirigidas. Comprobar también el E2E si los servicios están accesibles.
3. Guardar dos campañas frías del mismo corpus y configuración de validador,
   una con DIRECT y otra con SMART y extracción externa habilitada. Comparar
   con `evaluation.pipeline.compare_modes`; revisar calidad, vigencia, latencia
   y costes antes de activar SMART por defecto.
4. Confirmar la retención de instantáneas frente a la de artefactos; cuando
   `snapshot_id=null` por documento >8 MiB, el texto íntegro no queda en Mongo.
   Verificar el contrato real de `statuses.source` de Exa en un entorno con
   credenciales: el modo estricto admite solo `live` y se cierra ante valores
   desconocidos.

Comandos útiles de verificación en este entorno:

```bash
PYTHONPATH=api:tests .venv/bin/python -m pytest tests/api/test_common_search.py tests/api/test_evidence_search_units.py tests/api/test_evidence_grounding.py tests/evaluation/test_execution.py tests/evaluation/test_viewer_build.py tests/evaluation/test_viewer_contract.py -q -k 'not fetch_url_validation and not redirect_ and not html_article_body and not http_202_empty_body and not retry_after_pending and not rate_limited_response and not access_denied_is_not_retried and not retry_is_skipped and not pdf_content_is_extracted and not document_format_uses_payload and not pdf_extraction_is_offloaded and not plain_text_payload and not fetch_failure_exposes and not tls_hostname_mismatch and not connect_errors_do_not'
node --check web_classic/app/js/app.js
node --check web_classic/app/js/i18n.js
git diff --check
```

## Notas de reanudación

Antes de continuar, leer esta bitácora y `git status --short`. No descartar
cambios de otros autores. Ejecutar pruebas dirigidas de Evidence Search y de
contrato de citas antes de ampliar el alcance. Registrar aquí cada cambio,
prueba y riesgo residual para permitir reanudar la implementación más tarde.
