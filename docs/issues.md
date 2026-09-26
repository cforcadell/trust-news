# Incidencias de Assermetry

Revisión: **2026-09-20**. Inventario acumulativo de hallazgos y criterios de
cierre de [v0.0.13](version.md). La revisión contrasta el código en
`d7b4308`, las pruebas focalizadas y una ejecución LIGHT local; no equivale a
validación completa en el entorno objetivo.
011, 012 y 018 están solucionadas y desplegadas en Hetzner. Evidencia de código
local no implica comportamiento demostrado en el despliegue.

## Gestión

Estados: **Abierto → En curso → Pendiente de validación → Resuelto**.
**Mitigado** conserva la causa; una validación fallida reabre la incidencia.
**Descartado** requiere justificación. Cada cambio registra commit, caso,
entorno y evidencia; no se guardan credenciales ni datos personales.

Gravedad: **P0** compromiso crítico/pérdida de datos/indisponibilidad;
**P1** seguridad, flujo o resultado esencial incorrecto; **P2** degradación con
alternativa; **P3** cosmética. Orden de trabajo y bloqueo se deciden aparte.
005–008 pasan de P0 histórico a P1 por impacto funcional: siguen bloqueando el
cierre de 13, salvo la validación pendiente de 008. No se reduce su urgencia.

| ID | Gravedad | Estado / evidencia actual | Objetivo |
| --- | --- | --- | --- |
| 001 | P1 | Mitigado; concurrencia pendiente | 13 |
| 002 | — | Resuelto el 2026-08-19 | Histórico |
| 003–004 | P1 | Abiertos; configuración confirmada | 16; decisión de aplazamiento pendiente para cerrar 13 |
| 005 | P1 | Abierto; reproducido en GUI y funciones | 13 |
| 006 | P1 | Abierto; contradicción confirmada en renderizado | 13 |
| 007 | P1 | Solucionada y validada localmente el 2026-09-07; pendiente de despliegue | 13 |
| 008 | P1 | Pendiente de validación; exclusión de errores ya implementada | 13 |
| 009 | P1 | Abierto; edición opcional ya existe | 14 |
| 010 | P1 | Abierto; evidencia detallada ya existe | 14 |
| 011 | P1 | Solucionada y desplegada en Hetzner | 13 |
| 012 | P1 | Solucionada y desplegada en Hetzner | 13 |
| 013 | P1 | Solución reforzada; E2E Blockchain local correcto el 2026-09-20, objetivo pendiente | 13 |
| 014 | P1 | Abierta; confirmada en código/sondas locales | 13 |
| 015 | P1 | Solucionada localmente; E2E LIGHT con proveedor externo correcto, despliegue objetivo pendiente | 13 |
| 016 | P1 | Abierto; falsos positivos y diagnóstico incompleto | 13 |
| 017 | P1 | Abierto; carencia de evaluación factual | 13, ampliar en 14 |
| 018 | P1 | Solucionada y desplegada en Hetzner | 13 |
| 019 | P1 | Solución local de polling/contadores; falta validar parciales, duplicados y ambos modos | 13 |
| 020 | P2 | Abierto; desbordamiento y mezcla de idiomas | 13 |
| 021 | P1 | Parcialmente resuelta; grounding canónico y filtro oficial aplicados, PDF/independencia pendiente | 13 |
| 022 | P2 | Abierto; taxonomía libre fragmenta y contamina rutas cacheadas | 13 |
| 023 | P1 | Solucionada y validada localmente con E2E GUI BLOCKCHAIN el 2026-09-20 | 13 |

Los P1 de objetivo 13 bloquean su cierre. 009–010 bloquean la experiencia de
revisión/evidencia de 14. 020 debe corregirse antes de acreditar móvil. 022 debe
cerrarse antes de considerar estable la caché de rutas; cualquier aceptación
temporal debe limitar explícitamente el alcance de demo.

## Incidencias previas, revisadas

### ISSUE-001 - Carrera de inicializacion en la cache de validadores LIGHT

- **Hallazgo:** un arranque conjunto seleccionó uno de tres validadores. El
  refresco manual recuperó nueve validaciones para tres aserciones.
- **Revisión:** `load_validators_cache_from_chain` sustituye la caché incluso
  por una lista vacía; no acredita frescura acotada ni coordinación con eventos.
  El LIGHT actual 3×3 pasa, pero no prueba un reinicio concurrente.
- **Cierre:** refresco compartido, conservación de última caché válida, eventos
  concurrentes sin pérdidas y arranque escalonado 3×3 sin intervención en Kind
  y Hetzner. Fuente: `api/news-handler/main.py`.

### ISSUE-002 - Secret OIDC no vacio como valor por defecto en tests

- **Resuelto:** eliminado el valor por defecto; el operador confirmó que no era
  el secreto productivo. No se requiere rotación productiva por este hallazgo.
- **Seguimiento:** comprobar por vía segura si la credencial histórica de test
  sigue activa; la fixture aún debe fallar pronto si falta configuración (016).

### ISSUE-003 - CI no autentica el API de K3s con su CA

- **Confirmado:** `.gitlab-ci.yml` conserva `--insecure-skip-tls-verify=true`.
- **Cierre:** CA y nombre TLS verificados; pruebas negativas con CA/nombre
  incorrectos. Objetivo 16 no equivale a aceptación del riesgo para cerrar 13.

### ISSUE-004 - CI no fija la clave SSH del servidor

- **Confirmado:** `.gitlab-ci.yml` alimenta `known_hosts` desde `ssh-keyscan`.
- **Cierre:** clave aprobada por canal independiente, verificación estricta y
  rechazo de clave ausente/cambiada; procedimiento de rotación documentado.

### ISSUE-005 - Fechas, zonas horarias y estados temporales inconsistentes en la GUI de resultados

- **Reproducido:** actividad de Blockchain a las 19:16 y última actualización a
  las 21:16. `parseEventTimestamp` interpreta `04/09` como abril; el parser de
  órdenes lo interpreta como septiembre.
- **Cierre:** API UTC ISO 8601 con zona; un único parser y presentación local
  ES/EN, con pruebas de zona, cambio horario y eventos. La decisión va en 006.

### ISSUE-006 - Estado provisional/final mezclado en la pantalla de proceso

- **Confirmado:** `renderOrderProcess` mantiene la tarjeta provisional sin
  condición de finalización; otras partes muestran resultado definitivo para
  cualquier estado que empiece por `VALIDATED`, incluidos errores.
- **Cierre:** distinguir proceso, suficiencia de evidencia y decisión; mensajes
  coherentes al finalizar, con errores, sin evidencia y sin consenso.

### ISSUE-007 - Veredicto global y calculo de consenso no explican empates ni decisiones

- **Estado:** solucionada y validada localmente (2026-09-07). Pendiente de
  desplegar y comprobar con recorridos reales LIGHT/BLOCKCHAIN en navegador.
- **Causa:** `calculate_assertion_result` normalizaba el acumulado por número de
  respuestas y seleccionaba con `max` entre TRUE/FALSE/UNKNOWN. Los empates se
  resolvían por orden de claves, UNKNOWN competía como afirmación factual y la
  GUI reutilizaba los scores como porcentajes sin explicar la decisión.
- **Política implementada:** `consensus-v2`, centralizada en
  `api/common/utils/scoring.py`, con cobertura decisiva mínima `0.5` (se exige
  que sea estrictamente superior) y `tie_epsilon=1e-9`. Distingue `CONSENSUS`,
  `WEIGHTED_MAJORITY`, `NO_CONSENSUS`, `INSUFFICIENT_EVIDENCE` y
  `NO_VALID_RESPONSES`; UNKNOWN es abstención y ERROR queda excluido.
- **Contrato:** añade `verdict`, `decision_status`, `reason_code`, pesos brutos,
  cuota de peso decisivo, cobertura, abstención, margen, conteos y versión de
  política. `winner` y `scores` se conservan como aliases legacy: `winner` es
  nulo sin decisión factual y `scores` representa ahora pesos brutos, no
  probabilidades ni el promedio anterior.
- **Reproducibilidad:** las nuevas respuestas LIGHT y BLOCKCHAIN guardan tipo,
  peso de tipo, reputación, peso efectivo y `validator-weights-v1`. Los registros
  anteriores mantienen el fallback a caché/configuración actual y se identifican
  mediante `legacy_dynamic_weight=true`; no se reescribe Blockchain ni MongoDB.
- **GUI:** presenta motivo, votos decisivos, abstenciones, errores y peso
  TRUE/FALSE/UNKNOWN en ES/EN. Los porcentajes se etiquetan como cuota de peso
  decisivo/completado. El estado documental es conservador (`SUPPORTED`,
  `CONTRADICTED`, `MIXED`, `PARTIALLY_VERIFIED`, `INCONCLUSIVE`); FALSE+UNKNOWN
  es parcial y no «Desmentida».
- **Pruebas:** 38 pruebas focalizadas Python y las suites Node de consenso,
  estado y evidencias pasan. Regresión Python: **181 PASS, 2 FAIL**; permanecen
  exactamente los fallos conocidos de 015 y 016. Sintaxis JS correcta.
- **Pendiente para ISSUE-017:** calibración con corpus de evaluación,
  `min_winner_share` u otros umbrales estadísticos, y revisión del peso
  `HUMAN=0.1`. Ese valor no expresa autoridad epistemológica automática.

### ISSUE-008 - Validadores con timeout tratados como resultado valido

- **Avance confirmado:** backend, modelos y GUI distinguen `ERROR`; los tests
  de scoring excluyen errores y no asignan ganador cuando todas las respuestas
  fallan. El diagnóstico original ya no describe todo el código actual.
- **Pendiente:** inducir timeout real en LIGHT/BLOCKCHAIN y validar mensaje,
  conteo, estado final y ausencia de voto/evidencia; probar reintento individual
  sin duplicados. La presentación final se coordina con 006 y 019.

### ISSUE-009 - Flujo de extraccion y clasificacion de afirmaciones no revisable

- **Avance:** `renderEditableAssertionsTable` permite editar texto/categoría,
  añadir y eliminar. Sigue disponible publicar directamente; el recorrido de
  revisión humana no está garantizado ni cubierto por la regresión.
- **Cierre en 14:** recorrido humano texto → extracción → revisión → confirmación
  → validación; API automática explícita. Probar unidades, fechas, negación,
  afirmaciones compuestas y contexto; no confundir categoría con veracidad.

### ISSUE-010 - Resultado no presenta evidencia principal ni informe reutilizable

- **Avance:** existen pestaña Evidencias, fragmentos y enlaces por validador.
  Falta acreditar el resumen principal por afirmación y el informe reutilizable.
- **Cierre en 14:** texto original, veredicto, fuente, fecha, fragmento y
  limitaciones visibles y exportables. Diferenciar trazabilidad Blockchain de
  evidencia factual; usar «Verificar contenido» de forma consistente.

## Hallazgos nuevos — 2026-09-05

### ISSUE-011 - Consulta de validaciones sin aislamiento efectivo

- **Estado:** solucionada y desplegada en Hetzner (2026-09-06).

- **Causa:** Gateway omitía identidad en `/validators/cache/{hash}/validations`;
  News Handler asumía `admin=True` y podía devolver órdenes ajenas.
- **Implementado:** Gateway deriva el propietario del token y codifica los
  filtros; News Handler exige identidad y filtra validaciones, textos, enlaces
  y estadísticas. El parámetro `admin` no amplía acceso, tampoco `trust-admin`.
- **Validación local:** 15 pruebas HTTP Gateway → News Handler con dos
  propietarios y colecciones simuladas; incluyen suplantación por parámetros,
  identidad ausente, ámbito vacío y órdenes huérfanas.
- **Pendiente:** desplegar Gateway y News Handler en Hetzner y repetir con dos identidades
  reales. Este endpoint interno confía en la identidad transmitida por Gateway;
  no debe exponerse directamente. Las organizaciones son uniusuarias; no se acredita aislamiento de todas las rutas.

### ISSUE-012 - JWT sin validación de audiencia ni cliente presentador

- **Estado:** solucionada y desplegada en Hetzner (2026-09-06).

- **Causa original:** `get_current_user` desactivaba la validación de `aud` y
  no exigía una lista de `azp/client_id`. Fuente: `api/gateway/main.py`.
- **Implementado:** audiencia obligatoria `TrustNewsGateway` y lista de clientes
  permitidos. Verificación local: 6 pruebas de helpers y 11 sondas con JWT
  firmados correctas; estas últimas aún no están incorporadas a la suite.
- **Despliegue:** configurar Keycloak y comprobar tokens nuevos de ambos clientes
  en Hetzner. Revisar la compatibilidad de `sh` con `<<<` en el script de
  reconciliación; la comprobación local con `sh -n` falla.
- **Cierre:** audiencia `TrustNewsGateway`, presentadores permitidos
  (`TrustNewsWeb` y `TrustNewsApi`) y pruebas negativas de token válido para
  otra API/cliente. Las organizaciones son uniusuarias; no se introduce un
  modelo adicional de roles organizativos.

### ISSUE-013 - Veredictos sin evidencia comprobada y atribución automática

- **Validada localmente (2026-09-06):** RAG exige URL, fragmento y pertenencia
  al corpus recuperado por el servidor. Un veredicto documental TRUE/FALSE sin
  soporte se degrada a UNKNOWN; las citas inventadas, vacías o ajenas al corpus
  se rechazan. Se distinguen evidencia recuperada, `evidence_used` y
  `sources_declared`.
- **Tipos:** memoria y búsqueda delegada pueden emitir una señal sin fuentes,
  identificada respectivamente como `MODEL_KNOWLEDGE` y
  `PROVIDER_SEARCH_UNVERIFIED`; no se presentan como evidencia documental. RAG
  conserva únicamente evidencia comprobada.
- **Evidencia:** pruebas de grounding, contratos y UI; orden LIGHT
  `943346a6-1071-45f2-b97c-f10d746c150a` ejecutada con tres validadores RAG y
  persistencia de evidencias verificadas/rechazadas en MongoDB.
- **Refuerzo implementado (2026-09-19, `d7b4308`):** la referencia del modelo
  debe incluir un `context_id` único, citable y creado por el servidor. URL,
  título, texto, hash y chunk público se reconstruyen exclusivamente desde ese
  contexto canónico. Se rechazan identificadores ambiguos/no recuperados, texto
  no citable y fuentes que sean el documento original; los snippets del
  proveedor quedan como diagnóstico, nunca como cita.
- **Validación local nueva:** 27 pruebas de grounding y Evidence Search pasan;
  cubren contexto inventado, ambiguo, no citable, URL/texto inyectados y fuente
  original. La caché incorpora `citation_contract=retrieved-context-id-v1` para
  no reutilizar respuestas incompatibles.
- **Pendiente de cierre formal:** E2E de los tres tipos y de los recorridos
  Kafka/IPFS/MongoDB/navegador, especialmente BLOCKCHAIN y el entorno objetivo.
  La comprobación de implicación semántica entre afirmación y cita se mantiene
  como alcance de ISSUE-017.
- **Límite descubierto:** comprobar que una cita pertenece al corpus no acredita
  independencia ni calidad de la fuente. La autoconfirmación y la elegibilidad
  documental se separan en ISSUE-021 para no reabrir el alcance ya implementado.

### ISSUE-014 - Resumen rompe al faltar resultados ponderados

- **Reproducido:** `buildVerificationSummary` declara el número
  `completedValidations` y después intenta llamarlo como función; una orden con
  validaciones sin resultado ponderado lanza `TypeError`.
- **Cierre:** corregir la colisión y renderizar órdenes antiguas, parciales y con
  solo errores sin excepción. Fuente: `web_classic/app/js/app.js`.

### ISSUE-015 - Selección local de fuentes sin pertinencia regional acreditada

- **Estado:** solucionada y validada localmente; MongoDB se realineó en
  `kind-trust-news`. Pendiente de desplegar y ejecutar con proveedores externos.
- **Causa eliminada:** `LOCAL` usaba una allowlist masiva estática sin
  pertinencia regional acreditada. Evidence Search mezclaba selección de
  dominios y recuperación, y podía fabricar placeholders sin proveedor.
- **Implementado:** microservicio interno `source-router`; discovery real por
  `common/search`, una clasificación batch por `common/llm`, rechazo de
  dominios inventados, eligibility geográfica estricta, ranking determinista y
  memoria `source_routes_v2` FRESH/STALE/MISSING. Los validators orquestan
  `source-router → evidence-search(preferred_sources)` solo para RAG+LOCAL.
- **Eliminado:** perfiles/seeds/generadores estáticos y colecciones
  `evidence_domain_profiles`/`evidence_normalization_configs`. El bootstrap las
  elimina explícitamente. Las estrategias RAG externas se mantienen como
  `EXT_OFFICIAL_FIRST` y `EXT_ONLY_OFFICIAL`; `NONE` se elimina.
- **Validación:** tests unitarios cubren rutas regionales, nacionales y UE,
  firma normalizada, caché FRESH, stale fallback, rechazo de dominios inventados
  y orden `router -> evidence-search`. El script se aplicó y verificó dos veces
  sobre MongoDB local. El E2E LIGHT del 2026-09-19 resolvió cuatro rutas `FRESH`
  y restringió la búsqueda a sus dominios antes de llamar a Evidence Search; los
  12 validadores terminaron y la orden quedó `VALIDATED`. Falta repetirlo en
  BLOCKCHAIN y en el entorno objetivo.
- **Hallazgo de seguimiento:** la ruta italiana clasificó
  `gazzettaufficiale.biz` como `OFFICIAL_GAZETTE/NATIONAL_PRIMARY` al nivel de
  `gazzettaufficiale.it`. Debe corregirse el perfil o introducir una denegación
  de mirrors antes de considerar la elegibilidad documental estable.
- **Límite restante:** la extracción PDF y la clasificación documental fina se
  tratan en ISSUE-021; la estabilidad de la firma queda resuelta en ISSUE-022.

### ISSUE-016 - Regresión con falsos positivos y diagnóstico incompleto

- **Confirmado:** móvil solo comprueba viewport, aunque documento=847 y
  viewport=390; tests Blockchain antiguos aceptan HTTP 500. Una salida temprana
  evita agregar errores de red/consola: la ejecución interrumpida registra 400
  de autenticación y dos errores de consola, pero el resumen cuenta cero.
- **Además:** el test de logs se corrigió para usar `caplog` y vuelve a comprobar
  `search_request`. `tests/api/requirements.txt` no reúne las
  dependencias de la suite y la fixture no exige credenciales antes de conectar.
- **Comprobación 2026-09-19:** las pruebas aisladas de grounding/búsqueda (27),
  scoring (29) y GUI de polling (3) pasan, pero las 12 pruebas de
  `test_validator_source_orchestration.py` ni siquiera cargan porque
  el entorno virtual de pruebas no contiene `hexbytes`. Esto confirma el defecto de entorno
  reproducible; no se debe publicar una línea base global verde.
- **Cierre:** entorno de tests reproducible, `caplog`, fallos HTTP estrictos,
  comprobaciones de contenido/overflow y diagnóstico en `finally`; registrar
  identidad efectiva, revisión desplegada y metadatos, sin inferirlos del caso.

### ISSUE-017 - Falta evaluación de calidad factual y contenido adversarial

- **Carencia confirmada:** los dos casos sintéticos comprueban estados y mínimos
  de entidades; no evalúan si la afirmación, la evidencia y el veredicto son
  correctos. Ningún PASS actual demuestra calidad para noticias reales.
- **Cierre:** corpus versionado con referencia humana y fuentes congeladas:
  verdadero/falso/no verificable, contenido humano y generado, fechas/unidades,
  negación, citas inventadas y órdenes maliciosas dentro del texto o las fuentes.
  Medir extracción, soporte de citas, errores de veredicto y abstención; acordar
  umbrales antes de evaluar. No se afirma un ataque al LLM demostrado.

### ISSUE-018 - Enlaces de evidencia sin validar el esquema

- **Estado:** solucionada y desplegada en Hetzner (2026-09-06).

- **Reproducido en renderizado aislado:** `renderEvidenceLinks` conserva
  `href="javascript:void(0)"`; `safeText` escapa HTML, pero no valida protocolos.
  El modelo acepta fuentes como diccionarios libres. No se ha ejecutado un
  payload en el navegador ni probado explotación con la CSP desplegada.
- **Cierre:** aceptar solo HTTP(S) en servidor y cliente; texto inerte para URLs
  inválidas; pruebas con esquemas peligrosos y enlaces malformados.
- **Implementado (2026-09-06):** saneamiento en los modelos de evidencia y
  validación de enlaces en el renderizado. URLs malformadas no invalidan el
  objeto completo; se conservan en `url_text`/`source_url_text`, solo para
  mostrar texto escapado. Se rechazan hosts ausentes o inválidos, puertos
  inválidos, esquemas peligrosos y caracteres ambiguos.
- **Validación local:** 38 pruebas Python de URLs/modelos y 15 pruebas de las
  funciones reales de renderizado correctas. Regresión: 134 PASS y los dos
  fallos conocidos de 015/016. El despliegue en Hetzner está realizado; queda
  registrar la comprobación funcional en navegador si se requiere para el cierre.

### ISSUE-019 - Total de validaciones contradictorio durante el proceso

- **Observado en Blockchain:** dos afirmaciones, seis pendientes y tarjeta
  «0/4». `buildVerificationSummary` prioriza solicitudes parciales sobre otros
  recuentos. Puede producir porcentajes o mensajes prematuros.
- **Cierre:** una fuente autoritativa para esperadas/recibidas/error/pendientes;
  siempre total=recibidas+pendientes, sin superar 100 %. Probar llegada parcial,
  duplicados y reintentos en ambos modos.
- **Implementado localmente (2026-09-19, `d7b4308`):** el resumen prioriza las
  solicitudes de validación completas, calcula pendientes como el máximo entre
  el campo persistido y la diferencia contra las completadas, y el polling
  conserva la pestaña Proceso hasta tener un render terminal limpio. Las tres
  pruebas Node de estado/polling pasan. Falta la matriz de cierre: llegada
  parcial, duplicados, reintentos, error inducido y ambos modos.

### ISSUE-020 - Desbordamiento móvil y lenguaje de interfaz inconsistente

- **Reproducido:** documento de 847 px con viewport de 390 px en LIGHT y
  BLOCKCHAIN; navegación ocupa gran parte de la pantalla y el aviso sale del
  ancho visible. En castellano aparecen «valid», «errors» y «Publicar Noticia».
- **Cierre:** sin scroll horizontal de página a 390 px, navegación compacta,
  avisos contenidos y resultado accesible; ES/EN completos y acciones coherentes.
  Validar teclado y foco, no solo tamaño del viewport.

## Hallazgos nuevos — 2026-09-11

### ISSUE-021 - Una fuente recuperada puede autoconfirmar la noticia y eludir la política documental

- **Estado:** parcialmente solucionada. Reproducida en la orden LIGHT
  `355f6090-cec0-4ed3-a29a-46763fe66cc6`, primera aserción.
- **Impacto:** los tres validadores RAG emitieron TRUE usando como evidencia la
  noticia de Libertad Digital que originó el texto. La cita es literal y supera
  el grounding de ISSUE-013, pero no es corroboración independiente.
- **Causas originales:** la URL original se pierde tras importar el texto; Source Router
  permite medios si cumplen jurisdicción; `EXT_ONLY_OFFICIAL` orienta al
  proveedor pero no filtra su respuesta; el validator pasa solo dominios a
  Evidence Search y pierde metadatos; el recuperador rechaza PDF, por lo que el
  informe primario de IEA localizado no aportó contexto utilizable.
- **Cierre:** propagar URL/dominio de origen; clasificar fuente primaria,
  secundaria, copia y relación con el documento sometido; aplicar la política
  tras recuperar resultados; conservar metadatos del router; extraer PDF con
  página y error auditable. Una fuente sometida o copia no puede ser la única
  evidencia decisiva. Para una afirmación atribuible a un estudio se exige el
  documento primario recuperado o el veredicto efectivo es UNKNOWN.
- **Implementado:** URL/dominio de origen viajan en los contratos `v2`; Evidence
  Search conserva tipo, autoridad, puntuación, versión de perfil y relación con
  el origen; `EXT_ONLY_OFFICIAL` filtra después de recuperar; el grounding
  rechaza `relationship_to_origin=ORIGINAL`. Desde `d7b4308` esa exclusión se
  aplica contra el `context_id` canónico y no puede ser eludida aportando una
  URL, texto o hash libres desde el modelo. Sigue pendiente la extracción PDF,
  una clasificación documental más fina que `UNKNOWN` y la garantía de que una
  fuente secundaria no sea la única base decisiva de una afirmación atribuida.
- **Regresión:** la orden indicada debe priorizar y citar el informe de IEA. Si
  este no puede recuperarse, Libertad Digital puede conservarse como contexto o
  pista, sin producir por sí sola TRUE/FALSE documental.
- **Relación:** amplía la calidad factual de 017; no invalida el grounding
  sintáctico de 013 ni la elegibilidad geográfica resuelta por 015.

### ISSUE-022 - Subcategorías y tipos libres generan rutas duplicadas o demasiado amplias

- **Estado:** solucionada en código y realineada en el clúster local
  `kind-trust-news`; pendiente de despliegue en producción.
  Mongo contenía rutas distintas para combinaciones próximas y la generación
  permitía `subcategory` libre.
- **Impacto:** sinónimos, tildes, traducciones o elecciones variables crean
  nuevas entradas; a la vez, una ruta temática amplia puede reutilizar fuentes
  descubiertas para un estudio concreto. Aumenta coste y puede degradar la
  pertinencia sin producir un fallo explícito.
- **Causas:** la firma solo normaliza espacios y mayúsculas; no hay catálogo ni
  aliases de subcategorías; `claim_type_for_assertion` puede elegir el primer
  `preferred_source_type` por orden alfabético; autores y título influyen en el
  descubrimiento, pero no se separan de la memoria temática.
- **Implementado:** se elimina `subcategory` y se sustituyen los valores libres
  por `topic_code`, `evidence_kind`, `source_type`, `authority_level` y
  jurisdicción de `routing-taxonomy-v1`. Pydantic y el JSON Schema rechazan
  valores inventados y combinaciones tema/categoría incompatibles. La firma es
  `route-v2|taxonomy|topic|evidence|jurisdiction`; texto, entidad y fecha quedan
  fuera de la caché temática y se usan en la búsqueda documental concreta.
- **Realineamiento:** colecciones nuevas `source_routes_v2`,
  `domain_profiles_v1` y `evidence_search_cache_v2`. El script idempotente
  `scripts/k8s/realign-source-routing-mongodb.sh` elimina datos obsoletos,
  asegura índices y registra la versión; CI ejecuta `--apply` y `--check`.
- **Regresión y métricas:** aliases equivalentes producen la misma clave;
  conceptos relacionados pero distintos permanecen separados. Registrar tasa
  de rutas nuevas, reutilización, colisiones y candidatos `OTHER` para revisar y
  repriorizar la taxonomía.

### ISSUE-023 - El registro BLOCKCHAIN pierde los campos del contrato de aserciones v2

- **Reproducido (2026-09-19):** el E2E GUI Blockchain publicó la orden
  `11ea41f6-c315-4c13-9ab8-00fbbcc686f0`, generó cuatro aserciones y subió el
  documento a IPFS (`QmQrPwqsPZafEvCuZ1xvoTk5XwNk2Z4bQJ3QkoAd4eedBo`). La orden
  quedó en `BLOCKCHAIN_PENDING`, sin `post_id` ni `tx_hash`.
- **Causa:** tras `ipfs_uploaded`, `news-handler` convierte el documento v2 con
  `to_chain_assertion()` y lo entrega a `RegisterBlockchainRequest`. Esa
  conversión conserva solo `idAssertion`, `text` y `categoryId`, mientras que
  el modelo `RegisterBlockchainPayload` exige además `topic_code`,
  `evidence_kind` y `context`. La validación Pydantic rechaza las cuatro
  aserciones y `handle_blockchain_request` captura el error; el flujo continúa
  marcando la orden como pendiente aunque nunca publica `register_blockchain`.
- **Impacto:** no se crea el post ni la transacción y no se solicitan ni reciben
  validaciones Blockchain. El caso GUI no puede satisfacer CID/post/tx/IPFS ni
  alcanzar `VALIDATED`.
- **Solución (2026-09-20):** `register_blockchain` usa ahora
  `register-blockchain-v2` y transporta solo CID y publicador. `news-chain`
  recupera y valida el `AssertionsDocumentV2` de IPFS, deriva sus categorías y
  envía únicamente estas al contrato existente. La respuesta usa asignaciones
  compactas y `news-handler` las combina con el documento canónico MongoDB.
  Los fallos de petición o registro se persisten como `BLOCKCHAIN_ERROR` con
  etapa, código y capacidad de reintento; no se anuncia un pendiente ficticio.
- **Corrección asociada:** los listeners de `news-chain` y
  `validate-asertions` desempaquetan la respuesta `{cid, content}` de IPFS antes
  de validar V2; un evento inválido ya no termina el listener de un validador.
- **Validación de cierre:** 28 pruebas focalizadas pasan. El E2E GUI Blockchain
  `synthetic-blockchain-01` creó la orden
  `a237441b-f1aa-4c32-8468-fe79163f865c`, CID
  `QmNaWX2Ra7SKUzoswZERE7GGHwFpRxT3WZVwHaaWCbpXR3`, post `36` y transacción
  `0x019cff71a2bf46fea9a5840f7b1426ad1b0fa44eb740b779caea2e64861a051b`.
  Alcanzó `VALIDATED` con cuatro aserciones, doce validaciones y cero pendientes;
  comprobó pestaña IPFS, escritorio/móvil y ausencia de errores HTTP/consola
  inesperados. Artefactos: `/tmp/assermetry-e2e-blockchain-v2-retry-20260920`.
- **Límite:** esta evidencia es del clúster local, no del entorno objetivo.
