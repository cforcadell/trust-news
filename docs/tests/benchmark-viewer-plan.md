# Plan de implementación: visor local de órdenes de evaluación

**Actualizado:** 2026-10-01

**Estado global:** fases 0–6 implementadas; verificación integral con servicios externos aún pendiente.

**Siguiente paso operativo:** generar una campaña nueva con servicios externos y captura COLD para revisar datos reales; las anotaciones humanas siguen pendientes de decisión.

## Objetivo y decisiones cerradas

Construir un frontend independiente de `web_classic` para diagnosticar visualmente **órdenes ya guardadas** por la evaluación de `llm_benchmark`/`evaluation.pipeline`. Navegación: campaña → repetición/orden → Generate Assertions → afirmación → validador → Source Router → Evidence Search → entrega de evidencias → LLM/citas → consenso. Cada módulo abre una tabla y permite llegar a la observación original.

- Solo se admitirán artefactos nuevos que cumplan el contrato definido en la fase 0. No se migrarán los lotes históricos ni el índice SQLite.
- El visor será de lectura de órdenes finalizadas o guardadas, sin seguimiento en vivo, publicación de órdenes ni llamadas a proveedores.
- Las futuras trazas de evaluación guardarán el texto de **todos** los chunks, incluidos los descartados. Se limitará esta captura al modo de evaluación y se versionará el formato.
- Sin autenticación ni gestión de usuarios para este visor local/por túnel.
- Las comprobaciones automáticas nunca presentarán una inferencia como hecho: `PASS`, `FAIL`, `PARTIAL`, `NOT_EVALUATED` y `SKIPPED` deben conservar significados distintos. Cita válida significa identidad/elegibilidad, no apoyo semántico.
- Una orden puede tener varias afirmaciones y validadores; Generate Assertions es una etapa **por orden**. Router y las etapas posteriores se representan por afirmación/validador, según lo observado.

**Arquitectura elegida:** frontend independiente con HTML/CSS y módulos JavaScript nativos, servido por un pequeño servidor Python local de solo lectura para indexar campañas y entregar vistas por orden. Se evita una instalación de dependencias frontend y el visor funciona sin red. El servidor leerá archivos bajo una raíz de artefactos configurada, sin alterar manifest, órdenes o resultados. `analysis.json` se podrá usar como resumen derivado, pero el detalle se construirá a partir de los artefactos versionados. Cualquier anotación humana, si se incorpora, se guardará aparte de los artefactos originales.

## Contrato visual y reglas comunes

La cadena debe mostrar estado, recuento de hallazgos y causa observada de cada nodo. Colores: verde `PASS`; rojo `FAIL`; ámbar `PARTIAL`; gris `NOT_EVALUATED`/`SKIPPED`. El color irá acompañado de texto e icono. Un fallo de una etapa no colorea automáticamente como fallo todas las etapas posteriores: se muestra la dependencia y el estado propio de cada una.

Los enlaces entre vistas utilizarán identificadores de campaña, orden, afirmación, validador, `run_id`, consulta, URL, `source_id`, `chunk_id` y `context_id`. Los IDs de fuentes son locales a cada respuesta: nunca se unirán fuentes de validaciones diferentes solo por coincidir en `source-1`.

Una búsqueda servida desde caché mostrará el plan y el resultado cacheado con etiqueta **no ejecutada en esta orden**. Router `FRESH`, `STALE` y `MISSING`, ruta reutilizada, rutas inyectadas y búsqueda omitida deben distinguirse. La vista no reconstruirá resultados ausentes a partir de logs ni inventará consultas ejecutadas.

## Fases y criterios de cierre

### Fase 0 — Contrato y caso de referencia · Completada

- [x] Definir un esquema versionado para la traza de diagnóstico por orden, enlazado al `evaluation-result-v1` existente o a su sucesor. Incluir identidad, procedencia, etapas, estado, observaciones y `missing_reason`.
- [x] Definir la relación campaña/repetición/orden/afirmación/validador y cómo se representan órdenes incompletas o con errores.
- [x] Separar observación, comprobación automática y anotación humana. Especificar qué campos son obligatorios, opcionales y `NOT_EVALUATED`.
- [x] Preparar una fixture pequeña de orden con dos afirmaciones, dos validadores, una ruta cacheada, un fallo de descarga, chunks seleccionados/descartados y una cita inválida.
- [x] Documentar el contrato y actualizar este plan con rutas finales, versión y decisiones adoptadas.

**Cierre:** un artefacto de ejemplo se valida contra el contrato y permite recorrer toda la cadena, incluidos huecos de datos, sin consultar servicios.

### Fase 1 — Índice local y primera navegación · Completada

- [x] Crear el proyecto separado del frontend y su servidor local de lectura de artefactos.
- [x] Listar campañas, órdenes guardadas y repeticiones; mostrar estado, fecha, dataset, número de afirmaciones, validaciones y errores.
- [x] Abrir orden → afirmación → validador y dibujar la cadena de módulos con estados existentes; abrir el JSON de cada etapa desde su panel.
- [x] Leer archivos bajo demanda; mostrar errores de formato o referencias rotas sin tumbar toda la campaña.

**Cierre:** la fixture de fase 0 montada como campaña nueva se recorre por HTTP sin servicios externos. El visor no modifica artefactos.

**Implementado:** `tests/evaluation/viewer/server.py` indexa carpetas de campaña y sirve diagnósticos y artefactos bajo demanda; `static/index.html`, `app.js` y `style.css` permiten seleccionar campaña, orden, afirmación, validador y etapa, ver estados, comprobaciones y JSON. Un archivo de diagnóstico mal formado aparece como error sin ocultar las demás órdenes. Una referencia a un artefacto ausente muestra error al abrirla.

**Verificado:** 9 pruebas de contrato/servidor pasan; `node --check` y compilación sintáctica Python pasan. Limitación actual: la interfaz no se ha probado aún en navegador real y el runner todavía no emite diagnósticos `order-diagnostic-v1`; la fase 2 empezará esa integración. Comando local: `PYTHONPATH=tests python3 -m evaluation.viewer.server --artifacts-root tests/evaluation/artifacts`.

### Fase 2 — Diagnóstico de Generate Assertions · Completada

- [x] Capturar en la traza de evaluación, por orden, texto original, configuración efectiva del generador, tiempos, número de intentos, reparaciones de esquema, resultado estructurado y errores resumidos; no guardar respuesta cruda del proveedor.
- [x] Representar todas las afirmaciones esperadas y generadas, incluidas omisiones, duplicados y afirmaciones extra. Registrar emparejamiento y puntuación como *heurística*.
- [x] Extender las anotaciones revisadas del dataset para permitir fragmento de origen y, si existen, categoría, tema, tipo de evidencia y contexto esperado.
- [x] Vista dividida texto original/tabla de afirmaciones. Detalle de texto, `categoryId`, `topic_code`, `evidence_kind`, entidades, lugares, jurisdicción, tiempo, `origin`, confianza y `search_hints`.
- [x] Comprobaciones deterministas de presencia de fechas/cifras/negaciones/entidades y correspondencia de campos anotados. La fidelidad semántica queda `NOT_EVALUATED` sin revisión humana.

**Cierre:** se detectan una afirmación omitida, otra extra y una pérdida de contexto temporal en la fixture de pruebas, y cada hallazgo enlaza a su observación. La etapa se muestra una sola vez por orden.

**Implementado:** `tests/evaluation/viewer/build.py` crea `<parent_run_id>-viewer.json` para `--publish` y `--order`; este último copia la orden al directorio de campaña. El builder conserva todas las afirmaciones generadas, empareja con una heurística explícita y compara cifras, fechas, negaciones, categoría, tema, tipo de evidencia y contexto anotado. `api/generate-asertions/main.py` adjunta metadatos de modelo, temperatura, intentos estructurados, reparación, duración y error tipado cuando `EVALUATION_CAPTURE_GENERATION=true`; `api/news-handler/main.py` los guarda fuera del documento publicado. `datasets.py` admite `source_excerpt`, `expected_topic_code`, `expected_evidence_kind` y `expected_context`. La interfaz añade tabla esperada/generada y detalle de contexto/consultas.

**Verificado:** pruebas focalizadas de builder y worker pasan; importación offline de una orden guardada emitió un diagnóstico válido con 3 afirmaciones y 9 validaciones. El runner terminó con código 1 por errores técnicos presentes en esa orden, no por el visor. **Límite:** los intentos registrados cuentan llamadas estructuradas inicial/reparación; los reintentos internos de transporte no se exponen. Sin la variable de captura, modelo procede del documento y los tiempos/intentos quedan `null`. La fidelidad semántica requiere revisión.

### Fase 3 — Diagnóstico de Source Router · Completada

- [x] Instrumentar el modo evaluación para guardar consulta de descubrimiento, proveedor, URLs devueltas, dominios deduplicados, candidatos clasificados, rechazados y seleccionados, con motivo individual de cada descarte.
- [x] Guardar estado y procedencia de caché, ruta anterior/recalculada y desglose de puntuación de clasificación/ranking para cada candidato. En caché, distinguir decisión actual de diagnóstico histórico almacenado.
- [x] Tabla por dominio con tipo, autoridad, jurisdicción, puntuación, posición, motivo y comparación con `acceptable_domains` cuando existan.
- [x] Presentar `NOT_EVALUATED` para corrección de dominio sin anotación revisada; mostrar por separado la ausencia de dominios y los fallos de clasificación.

**Cierre:** una orden permite explicar qué se buscó, qué dominio se recuperó, por qué entró o salió y si se reutilizó una ruta.

**Implementado:** tras la autorización del usuario, `api/source-router/app/service.py` añade observación opcional sin sustituir el algoritmo: cada búsqueda registra consulta, proveedor, URLs y descarte por URL vacía, dominio inválido o duplicado; la clasificación conserva sus campos, elegibilidad, motivos individuales y términos de puntuación. `evaluation_trace.py` calcula explicaciones de solo lectura de elegibilidad y ranking (base, bonificación de idioma, límite y ausencia de perfil). El fallback informa si el perfil falta, caducó, no encaja en tema/tipo o no supera elegibilidad; se registran candidatos preservados de una ruta anterior y el tipo de error de refresco. `source_routes.py` solo adjunta esa traza con `X-Evaluation-Run-ID` y distingue consulta planificada, ejecutada, ruta fresca, refresco fallido y origen histórico de diagnósticos. El visor muestra tablas de URLs, clasificaciones, componentes y ranking, además de los dominios anotados como aceptables. Si una función de observación falla, Router conserva la decisión y registra `trace_error_type`.

**Verificado:** 30 pruebas de Router pasan, incluidas búsqueda/deduplicación, rechazo por jurisdicción, puntuación, caché fresca, límite de ranking, perfil ausente, fallback y fallo del observador. 17 pruebas del validador pasan, incluida cabecera de evaluación solo en LIGHT. La suite integrada de Router, validador, Evidence Search y visor suma 83 pruebas aprobadas; `node --check` y `git diff --check` pasan. Chrome headless abrió el panel de Router con seis tablas, URL y decisión `SELECTED`, sin error de renderizado. Se instalaron en la `.venv` las versiones fijadas de `pycountry`, `web3` y `base58` para ejecutar las pruebas; `hexbytes` llegó como dependencia de `web3`.

**Límites:** una ruta `FRESH` no ejecuta descubrimiento nuevo y el documento cacheado no conserva URLs ni motivos históricos por candidato; la interfaz muestra `NOT_EXECUTED_CACHE` y solo el ranking recalculado sobre los perfiles actuales. Un dominio sin clasificación válida tiene motivo `NO_VALID_CLASSIFICATION`, sin causa semántica individual del LLM. No se ha lanzado una campaña nueva contra proveedores externos desde este entorno.

### Fase 4 — Diagnóstico de Evidence Search y chunks · Completada

- [x] Guardar por consulta **realmente realizada** proveedor, modo, filtros, URLs recibidas, duplicados, descartes por política/límite y error o resultado vacío. Señalar planes no ejecutados por límite o caché.
- [x] Guardar por URL descarga, `fetch_status`, longitud, tipo de documento, relación con origen, número de chunks y contextos; conservar URL aun si falla la descarga.
- [x] Guardar en artefactos de evaluación el texto de todos los chunks y el desglose de puntuación (valor léxico y cada bonificación), posición, señales, selección, motivo de descarte y contexto resultante. Conservar la relación chunk → contexto → fuente.
- [x] Tabla de URLs; al abrir una URL, tabla ordenable de chunks con texto expandible y resaltado de los seleccionados. Indicar límites por fuente/global, ventanas solapadas y fragmentos no citables.
- [x] Mostrar la evidencia de referencia del dataset junto a lo recuperado cuando exista; no declarar apoyo semántico a partir de coincidencia léxica.

**Cierre:** para cualquier fuente recuperada se puede explicar qué consultas y filtros la trajeron, cuántos chunks produjo y por qué se seleccionaron los contextos entregados.

**Implementado:** `api/evidence-search/main.py` registra en evaluación las consultas realmente ejecutadas, proveedor/filtros, URLs devueltas, deduplicación/límite, descartes de política, errores tipados, resultados vacíos, estado de caché, límites efectivos, descarga, tipo de contenido y fallo. `chunk_ranker.py` conserva puntuación léxica y bonificaciones por señal; `chunker.py` registra la decisión de cada ventana (selección, solape, longitud mínima, límite). Cada `evaluation_chunks` incluye texto completo, índice, rango, señales, desglose, selección y `context_ids`. El validador propaga el ID de evaluación a Evidence Search con `EVALUATION_CAPTURE_PIPELINE=true`. La UI presenta consultas/URLs, descargas, tabla ordenable de chunks y texto/contextos expandibles; muestra las referencias anotadas en el dataset.

**Verificado:** 16 pruebas de Evidence Search pasan, incluidas captura de chunks seleccionados y descartados, relación con contextos, cabecera de evaluación, resultado cacheado y exclusión del texto extra de la caché compartida; 10 pruebas del visor pasan y una se omite por falta de `jsonschema` en `.venv`; sintaxis JS validada. **Límites:** una respuesta cacheada no puede reconstruir chunks descartados, por lo que indica `NOT_RECORDED_ON_CACHE_HIT`; para analizarlos hay que activar `EVALUATION_CAPTURE_COLD=true` en el validador y `EVALUATION_ALLOW_COLD=true` en Router y Evidence Search. Los chunks de páginas cuya descarga falla o está desactivada no existen; se conserva URL y causa. Las bonificaciones explican ranking, no pertinencia semántica.

### Fase 5 — Entrega, LLM, citas y consenso · Completada

- [x] Comparar hashes registrados de recuperación y entrada del validador; representar ausencia de hash como `NOT_EVALUATED`.
- [x] Unir citas a la evidencia **de esa validación** por (`source_id`, `context_id`), mostrando contextos entregados, citados y rechazados. Distinguir ID inexistente, contexto no citable, ninguna cita y cita válida.
- [x] Mostrar modelo, versión, veredicto original/efectivo, errores, tiempo, grounding y motivo de degradación a `UNKNOWN`.
- [x] Mostrar votos, abstenciones, errores, pesos y motivo del consenso frente al resultado esperado.
- [x] Añadir filtros por etapa, código de hallazgo, caso, repetición y validador; comparación entre repeticiones de la misma afirmación.

**Cierre:** una cita inválida se localiza en el texto/contexto correcto y se puede seguir su efecto hasta el veredicto y el consenso.

**Implementado:** `build.py` compara hashes de recuperación/entrega y solo emite `PASS` cuando ambos existen y coinciden. El diagnóstico de citas usa únicamente los contextos entregados en esa validación; distingue fuente inexistente, contexto inexistente, contexto no citable y cita elegible, y conserva los motivos de la auditoría. Con `EVALUATION_CAPTURE_PIPELINE=true`, `validate-asertions` envía por Kafka los IDs originales declarados por el LLM como `evaluation_citation_trace`; `news-handler` los guarda en la orden y `orders.py` los pasa al snapshot. Esta traza no cambia grounding ni el documento público. La vista LLM muestra proveedor/modelo, configuración, tiempo, veredicto original/efectivo, grounding y errores. Consenso se resume desde `assertion_results`: voto, peso, abstenciones, errores, razón y distribución; no duplica en el snapshot los textos largos de `details`. Filtros de caso, repetición, validador, módulo y código; comparación bajo demanda del mismo caso/validador entre órdenes de la campaña.

**Verificado:** 4 pruebas del builder cubren cita inválida por fuente/contexto, contexto no citable, degradación a `UNKNOWN`, IDs originales y resumen de votos. La importación offline de una orden real emitió 9 validaciones y tres votos para un consenso; terminó `COMPLETED_WITH_ERRORS` por errores de validación existentes (código CLI 1). Sintaxis JS/Python validada. **Límites:** las órdenes previas o sin la opción de captura pueden carecer de IDs originales rechazados; el visor usa la auditoría disponible y declara el hueco. Identidad de cita no demuestra apoyo semántico. La comparación usa el caso emparejado heurísticamente y no agrupa afirmaciones sin pareja.

### Fase 6 — Revisión final y operación · Completada (alcance disponible)

- [x] Validar una campaña completa recién generada y una orden con fallos técnicos; revisar estados `SKIPPED`, `NOT_EVALUATED`, caché y resultados parciales.
- [x] Documentar comando de arranque, estructura de artefactos, límites del diagnóstico y cómo regenerar una campaña con trazas detalladas.
- [x] Comprobar tablas extensas, navegación con teclado, contraste de estados y visualización de texto largo.
- [x] Decidir sobre anotaciones humanas: se difiere su escritura hasta que el usuario la confirme; no se modifica ningún artefacto original. El formato propuesto mantiene orden, autor/fecha, etiqueta, nota y referencia exacta.
- [x] Actualizar este plan y `docs/tests/evaluation.md` con rutas, comprobaciones ejecutadas y limitaciones reales.

**Cierre:** el visor se arranca localmente con un comando documentado y permite terminar una revisión de orden sin acudir a logs de servicios.

**Revisión y operación:** `docs/tests/evaluation.md` documenta arranque, importación de orden, variables de captura y límites. Chrome headless abrió una campaña generada por importación offline de una orden real con 9 validaciones, navegó por Evidence Search, Citas y Consenso y cargó la comparación. Se comprobó la presencia de 3 votos resumidos y que el caso conserva fallos técnicos en el informe; el proceso de importación devuelve código 1 por `COMPLETED_WITH_ERRORS`, pero el snapshot se emitió y el visor lo abrió. La interfaz aplaza el volcado de observaciones y textos de chunks hasta expandirlos, añade símbolo y texto al color de estado y foco visible en controles.

**Verificado:** en el cierre inicial de esta fase pasaron 35 pruebas focalizadas y una se omitió por ausencia de `jsonschema`; `node --check` y Chrome headless confirmaron navegación sin errores. Después se instalaron las dependencias de Router/validador, se completó la fase 3 y la verificación integrada alcanzó 83 pruebas aprobadas. **Límites vigentes:** no se ha ejecutado una campaña nueva contra los servicios externos. La escritura de anotaciones humanas se difiere hasta contar con confirmación. No se ha probado manualmente el navegador con lector de pantalla.

## Decisión pendiente que no bloquea las fases 0–6

**Anotaciones manuales:** recomendadas para marcar extracción incorrecta, contexto inventado o evidencia irrelevante cuando faltan datos gold. No se ha confirmado aún si el usuario quiere escritura de estas anotaciones. La interfaz y el contrato distinguirán desde el principio observaciones automáticas y juicio humano; la escritura será una ampliación posterior si se aprueba.

## Registro de avance

Actualizar esta sección **al terminar cada fase o al cambiar una decisión**. No marcar una fase completa hasta cumplir su criterio de cierre. En cada actualización registrar fecha, archivos tocados, verificación ejecutada, límites y siguiente paso. Mantener los artefactos originales inmutables.

| Fecha | Fase | Estado | Cambios y verificación | Siguiente paso |
| --- | --- | --- | --- | --- |
| 2026-10-01 | Plan | Completado | Propuesta dividida en fases; sin implementación. | Fase 0: contrato y fixture. |
| 2026-10-01 | 0 | Completada | `order-diagnostic-v1` documentado en `docs/tests/benchmark-viewer-contract.md`; esquema, validador de referencias y fixture en `tests/evaluation/viewer/`. 7 pruebas focalizadas pasan. El runner todavía no emite este artefacto. | Fase 1: servidor local e interfaz de navegación para diagnósticos guardados. |
| 2026-10-01 | 1 | Completada | Servidor Python y UI independiente sin dependencias frontend; navegación y JSON bajo demanda. 9 pruebas focalizadas y sintaxis JS/Python pasan. Sin prueba de navegador real todavía. | Fase 2: capturar y diagnosticar Generate Assertions. |
| 2026-10-01 | 2 | Completada | Snapshot emitido por `--order`/`--publish`; traza opcional del worker, anotaciones gold y tabla de generación. 10 pruebas focalizadas pasan; importación offline real generó snapshot válido (3 afirmaciones, 9 validaciones). | Fase 3: registrar y mostrar decisiones de Source Router. |
| 2026-10-01 | 3 | En progreso | Traza aditiva y tabla de dominios; falta instrumentación interna de descubrimiento/ranking. Revisión automática rechazó reemplazar `resolve`; tests del Router/validador bloqueados por `pycountry`/`hexbytes` ausentes en `.venv`. | Completar fases independientes y revisar alternativa concreta para Router. |
| 2026-10-01 | 4 | Completada | Captura optativa de consultas reales, URLs, descargas, todos los chunks y decisiones de ventana; UI con tabla ordenable y contexto expandible. 16 tests de Evidence Search y 10 del visor pasan; una prueba opcional omite `jsonschema`. | Fase 5: entrega, citas, LLM y consenso. |
| 2026-10-01 | 5 | Completada | Citas enlazadas por validación, traza optativa de IDs originales, hashes, LLM, consenso resumido, filtros y comparación entre repeticiones. 4 tests de builder y smoke offline real (9 validaciones, 3 votos) pasan; CLI devuelve 1 por errores previos de la orden. | Fase 6: operación y revisión final. |
| 2026-10-01 | 6 | Completada en alcance disponible | Guía en `docs/tests/evaluation.md`, foco y texto junto al color, render diferido de textos largos. 35 pruebas focalizadas pasan (1 omitida); Chrome headless navegó una campaña real importada y la comparación. Anotaciones humanas diferidas por falta de confirmación. | Resolver fase 3 de Router y verificar campaña fresca con servicios disponibles. |
| 2026-10-01 | 3 | Completada | Tras autorización: traza aditiva de consultas/URLs, clasificación, rechazo, ranking, caché y fallback. 30 pruebas Router, 17 validador y 83 integradas pasan; Chrome headless muestra nuevas tablas. | Generar campaña nueva con servicios externos y captura COLD; anotaciones manuales pendientes de decisión. |

## Puntos de partida en el repositorio

- `docs/tests/evaluation.md`: modos, artefactos, métricas y análisis offline existentes.
- `tests/evaluation/core/models.py`, `orders.py`, `artifacts.py`: envoltura por validación, importación de orden y persistencia.
- `tests/evaluation/pipeline/analyze.py`: comprobaciones y estados actuales.
- `api/generate-asertions/main.py`, `api/common/models/protocol_models.py`: generación y campos de afirmaciones.
- `api/source-router/app/service.py`, `ranking.py`, `models.py`: consultas, caché, clasificación y ranking.
- `api/evidence-search/main.py`, `app/chunk_ranker.py`, `app/chunker.py`: búsquedas, descargas, ranking, ventanas y metadatos de chunks.
- `docs/tests/benchmark-viewer-contract.md`, `tests/evaluation/viewer/order-diagnostic-v1.schema.json`, `tests/evaluation/viewer_contract.py`: contrato formal, reglas de referencias y fixture para el visor.
