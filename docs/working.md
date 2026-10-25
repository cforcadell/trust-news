# Plan de mejora de Evidence Search

## Objetivo

Este documento organiza la mejora del tratamiento de descargas incompletas, respuestas HTTP `202` sin cuerpo, bloqueos de acceso y trabajo duplicado en Evidence Search.

La solución debe ser genérica. Ningún bloque puede introducir excepciones, listas de URLs o ramas de código específicas para uno o varios dominios. Los dominios observados en las campañas sirven como casos de regresión, no como configuración funcional embebida en el código.

El trabajo se divide en cuatro bloques con límites funcionales claros:

| Bloque | Estado | Resultado principal |
| --- | --- | --- |
| 1. Clasificación y observabilidad | Implementado y probado | Saber qué ocurrió en cada intento y calcular tasas con denominadores inequívocos |
| 2. Reintentos y sustitución de candidatos | Implementado y medido; cierre condicionado | Menos solicitudes y mejor extracción por intento; falta alcanzar el umbral agregado y cerrar DNS rebinding |
| 3. Historial compartido y caché por resultado | Parcial: primitivas existentes; evolución pendiente | Evitar repetir fallos conocidos entre validadores, procesos y réplicas |
| 4. Singleflight y visualización | Pendiente | Evitar descargas concurrentes duplicadas y hacer visible el embudo completo en el viewer |

La secuencia recomendada es `1 → 2 → 3 → 4`. Cada bloque tendrá pruebas unitarias e integración durante el desarrollo y terminará con una campaña E2E completa comparable. No se ejecutará una campaña completa después de cada cambio pequeño dentro de un bloque.

## Qué obtendremos al completar los cuatro bloques

Al final del plan tendremos:

- Una taxonomía estable que diferencia transporte, respuesta HTTP, extracción y citabilidad.
- Reintentos limitados y dirigidos por la clase de fallo, con presupuesto total y sin bucles.
- Sustitución de candidatos fallidos usando resultados ya descubiertos antes de realizar nuevas búsquedas.
- Memoria compartida y temporal de resultados positivos y negativos, con TTL apropiado para cada clase.
- Supresión de trabajo concurrente duplicado para una misma identidad documental.
- Métricas de intentos, respuestas, documentos extraídos y documentos citables reconstruibles desde los artefactos.
- Un viewer que permita comparar campañas y localizar dónde se pierde cada fuente.
- Una implementación independiente del dominio, gobernada por clases de resultado y límites operativos.

Estos bloques mejoran recuperación, coste y capacidad de diagnóstico. No garantizan por sí solos una mejora del veredicto: la generación de aserciones, Source Router, los modelos validadores y el consenso continúan siendo componentes separados.

## Reglas comunes de diseño

1. No implementar lógica por dominio, host o proveedor de contenido.
2. Clasificar antes de decidir si se reintenta, sustituye, recuerda o bloquea una operación.
3. Aplicar límites de intentos, tiempo, bytes y candidatos a toda operación.
4. Mantener TLS, protección SSRF y validación de redirecciones en todas las variantes.
5. Separar siempre estos conceptos:
   - Solicitud HTTP realizada.
   - Respuesta HTTP recibida.
   - Respuesta HTTP 2xx.
   - Documento con contenido extraído.
   - Documento con al menos un contexto citable.
6. Conservar compatibilidad con artefactos y respuestas anteriores mediante campos aditivos y valores por defecto.
7. No interpretar un `202` vacío como una descarga útil: es una respuesta aceptada o pendiente, no un documento recuperado.
8. No reintentar ciegamente un acceso denegado sobre la misma URL. Se debe avanzar a otro candidato o acción permitida.

## Estrategia de pruebas por bloque

Cada bloque se valida en tres niveles:

1. **Pruebas unitarias e integración:** se ejecutan durante la implementación y cubren las ramas nuevas, compatibilidad y límites.
2. **Prueba E2E dirigida:** usa fixtures o casos que ejercitan explícitamente las clases afectadas.
3. **Campaña E2E completa:** se ejecuta al terminar el bloque con los mismos casos, repetición, configuración y condiciones de caché que la línea base.

La comparación de campañas debe conservar:

- Los mismos 11 casos gold y sus hashes.
- Una repetición por caso mientras la campaña base siga usando una repetición.
- Los mismos tres validadores y configuración de modelos.
- El mismo modo `FULL_PIPELINE` publicado.
- Caché de Evidence Search vacía al inicio.
- El mismo commit o una relación de cambios documentada.
- Ausencia de despliegues mientras la campaña está en curso.

En desarrollo local se debe ejecutar el evaluador con `PYTHONDONTWRITEBYTECODE=1`. De lo contrario, la creación de `__pycache__` dentro de `api/` puede activar el watcher de Skaffold y provocar un rollout durante la campaña.

---

## Bloque 1. Clasificación y observabilidad

**Estado:** implementado, desplegado y probado el 24 de octubre de 2026.

### Propósito

Convertir los estados históricos del descargador en resultados operativos estables y separar los contadores del embudo. Este bloque no cambia la política de reintentos, el orden de candidatos ni la selección de fuentes.

Su beneficio funcional directo es poder responder sin ambigüedad a preguntas como:

- ¿Cuántos documentos se intentaron descargar?
- ¿Cuántas solicitudes recibieron respuesta HTTP?
- ¿Cuántas respuestas fueron 2xx pero no contenían un documento utilizable?
- ¿Cuántos documentos se extrajeron correctamente?
- ¿Cuántos terminaron siendo citables?
- ¿Qué proporción falló por acceso denegado, pendiente, red, extracción o recurso inexistente?

### Taxonomía implementada

| Resultado | Significado |
| --- | --- |
| `EXTRACTED` | El documento se descargó y se extrajo |
| `PENDING` | La respuesta indica procesamiento pendiente; incluye `202` sin cuerpo |
| `ACCESS_DENIED` | Acceso denegado o página de bloqueo |
| `NOT_FOUND` | El recurso no existe o ya no está disponible |
| `RATE_LIMITED` | El origen ha limitado temporalmente las solicitudes |
| `SERVER_FAILURE` | Error 5xx del servidor remoto |
| `NETWORK_FAILURE` | Timeout, error de red o problema TLS clasificado |
| `EMPTY_CONTENT` | Hubo respuesta, pero no se extrajo contenido suficiente |
| `UNSUPPORTED_CONTENT` | El formato no está soportado |
| `EXTRACTION_FAILURE` | El extractor falló o el documento excedió límites |
| `CLIENT_FAILURE` | Otro error HTTP 4xx |
| `FETCH_FAILURE` | Fallo residual que todavía no puede clasificarse mejor |

### Cambios implementados

- `api/evidence-search/app/document_fetcher.py`
  - Añade `FetchResult.outcome` y `FetchResult.diagnostics`.
  - Centraliza la clasificación estable del resultado y de cada intento.
- `api/evidence-search/main.py`
  - Persiste `fetch_outcome` y `fetch_diagnostics` en cada evidencia intentada.
  - Añade `classification` a cada elemento de `fetch_attempts`.
  - Marca por separado si hubo respuesta, si fue HTTP 2xx, si se extrajo contenido y si terminó siendo citable.
  - Amplía `retrieval_summary` con `http_requests`, `http_responses`, `http_successes`, `documents_attempted` y `outcome_counts`.
- `api/common/models/evidence_models.py`
  - Amplía el contrato de `EvidenceRetrievalSummary` con campos aditivos y valores compatibles con respuestas antiguas.
- `tests/evaluation/pipeline/metrics.py`
  - Calcula métricas desde el resumen nuevo y mantiene un fallback para artefactos históricos.
  - Distingue si existió realmente una respuesta de recuperación.
- `tests/evaluation/core/reporting.py`
  - Agrega el embudo de descarga y sus porcentajes al informe de campaña.

### Contrato de métricas

Las principales tasas quedan definidas así:

```text
descarga útil (%) = documents_extracted / documents_attempted × 100
respuesta HTTP (%) = http_responses / http_requests × 100
éxito HTTP (%) = http_successes / http_requests × 100
documento citable (%) = documents_citable / documents_attempted × 100
```

Una respuesta `202` cuenta como respuesta HTTP y como HTTP 2xx, pero no como documento extraído ni citable. Esta separación evita presentar un `202 Empty Body` como éxito de descarga.

### Pruebas del bloque 1

Se añadieron pruebas para:

- Clasificación de `202`, `403`, `404`, `429`, `5xx`, errores de red, contenido vacío, formato no soportado y error de extracción.
- Separación entre solicitudes, respuestas HTTP, éxitos HTTP, documentos intentados, extraídos y citables.
- Compatibilidad con mocks y adaptadores antiguos que no exponen las propiedades nuevas.
- Agregación de métricas en el informe E2E.
- Exclusión de ejecuciones que no llegaron a producir una respuesta de Evidence Search.

Resultado de la regresión:

```text
186 passed, 2 warnings
```

También se verificó dentro del pod desplegado que `HTTP_202_EMPTY_BODY` se clasifica como `PENDING`.

### Campañas utilizadas

| Campaña | Uso | Estado |
| --- | --- | --- |
| `e2e-20261024-191753` | Línea base anterior | Válida |
| `e2e-20261024-200452` | Primer intento del bloque 1 | Excluida: Skaffold redesplegó los servicios durante la ejecución y produjo 32 fallos 502 |
| `e2e-20261024-200711` | Segundo intento | Excluida: comenzó antes de que los validadores se registrasen tras el rollout |
| `e2e-20261024-200925` | Campaña final del bloque 1 | Comparable, terminada con errores funcionales registrados |

Las dos campañas excluidas se conservan como evidencia del incidente, pero no se usan para calcular cambios de calidad.

### Resultados de recuperación

La comparación se limita a las ejecuciones gold; las aserciones adicionales generadas se excluyen del denominador.

| Métrica | `e2e-20261024-191753` | `e2e-20261024-200925` | Variación |
| --- | ---: | ---: | ---: |
| Respuestas de Evidence Search | 33 | 28 | −5 |
| Documentos intentados | 149 | 124 | −25 |
| Documentos extraídos | 94 | 90 | −4 |
| Documentos citables | 94 | 90 | −4 |
| Descarga útil | 63,09 % | 72,58 % | +9,49 pp |
| Respuestas HTTP recibidas | 142 | 121 | — |
| Respuestas HTTP 2xx | 113 | 101 | — |
| Éxito HTTP sobre intentos | 75,84 % | 81,45 % | +5,61 pp |

El porcentaje de descargas exitosas de la primera fase es, por tanto, **72,58 %: 90 documentos extraídos de 124 intentados**.

El desglose normalizado por la taxonomía nueva es:

| Resultado | Campaña anterior | Bloque 1 |
| --- | ---: | ---: |
| `EXTRACTED` | 94 | 90 |
| `ACCESS_DENIED` | 25 | 19 |
| `PENDING` | 18 | 9 |
| `NETWORK_FAILURE` | 6 | 3 |
| `NOT_FOUND` | 3 | 1 |
| `EMPTY_CONTENT` | 1 | 2 |
| `RATE_LIMITED` | 1 | 0 |
| `FETCH_FAILURE` | 1 | 0 |

En la campaña nueva, `ACCESS_DENIED` y `PENDING` representan 28 de los 34 documentos no extraídos. Son, por tanto, las dos clases principales que debe abordar el bloque 2.

La subida de 63,09 % a 72,58 % no se atribuye al bloque 1: este bloque mide, pero no cambia el comportamiento del fetch. La diferencia puede proceder de variación en consultas, candidatos y servicios externos. La métrica sí queda ahora calculada directamente por el informe, sin reconstrucción manual.

### Cobertura de la instrumentación

La campaña final produjo:

- 124/124 documentos intentados con `fetch_outcome`.
- 124/124 documentos intentados con `fetch_diagnostics`.
- 124/124 intentos HTTP con `classification`.
- 28/28 respuestas reales de Evidence Search con los contadores nuevos.
- 0 respuestas recuperadas desde caché durante la medición.

El objetivo principal del bloque 1 —clasificación y denominadores reconstruibles— queda cumplido.

### Resultados globales de la campaña

La campaña final terminó como `COMPLETED_WITH_ERRORS`. Esto no invalida la instrumentación, pero impide considerarla una mejora global de calidad:

| Métrica de pipeline | Campaña anterior | Bloque 1 |
| --- | ---: | ---: |
| Casos gold | 11 | 11 |
| Ejecuciones puntuables | 33 | 31 |
| Ejecuciones de observación | 0 | 6 |
| Pase E2E estricto | 11/11 | 6/11 |
| Decisión de caso correcta | 11/11 | 8 correctas, 2 incorrectas y 1 no evaluada |
| Validaciones individuales | 29 correctas de 33 | 25 correctas, 3 incorrectas y 3 no evaluadas |
| Quorum degradado | 0 | 2 |

Problemas observados:

- Dos timeouts de Source Router afectaron a `ES_RENEWABLE_GENERATION_2024_TRUE` y `EU_RENEWABLE_TARGET_2030_TRUE`.
- `EU_RENEWABLE_TARGET_2030_FALSE` terminó con consenso incorrecto.
- `EU_GDPR_APPLICATION_FALSE` no produjo una aserción emparejable y quedó como error de extracción.
- `EU_RENEWABLE_SHARE_2023_TRUE` produjo un `TAXONOMY_MISMATCH`.
- El generador produjo dos aserciones adicionales no gold, que originaron seis ejecuciones `OBSERVATION_ONLY`.

Estos problemas pertenecen a Source Router, generación, taxonomía o consenso; no fueron introducidos por la clasificación de descargas. Deben seguirse por separado y no mezclarse con la tasa de descarga útil.

### Criterio de cierre del bloque 1

El bloque se considera implementado porque:

- La taxonomía está centralizada y cubierta por pruebas.
- Las métricas distinguen correctamente HTTP, extracción y citabilidad.
- Los artefactos nuevos contienen los diagnósticos necesarios.
- El informe calcula automáticamente la tasa de descarga útil.
- La regresión afectada está verde.
- Se ejecutó y analizó una campaña E2E completa comparable.

No se considera cumplida todavía ninguna meta de mejora de descarga, porque el bloque no modifica la recuperación.

---

## Bloque 2. Reintentos y sustitución de candidatos

**Estado:** implementado y medido en `e2e-20261025-102837`; mejora la eficiencia por documento y corrige la selección del Source Router en el caso energético. **No cerrar todavía:** la descarga útil agregada queda en 68,04 % (por debajo del objetivo inicial del 75 %) y la defensa ante DNS rebinding de las redirecciones aún necesita una barrera de conexión o de egreso.

### Propósito

Usar la clasificación del bloque 1 para actuar de forma diferente según el fallo y aumentar el número de documentos extraídos sin lógica específica por dominio.

### Cambios previstos

1. Definir una matriz genérica `outcome → action`:
   - `PENDING`: reintento diferido y limitado; respetar `Retry-After` cuando exista.
   - `RATE_LIMITED`: espera con backoff y jitter dentro del presupuesto total.
   - `SERVER_FAILURE` y `NETWORK_FAILURE`: reintento transitorio acotado.
   - `ACCESS_DENIED`, `NOT_FOUND`, `UNSUPPORTED_CONTENT` y fallos estables: no repetir ciegamente la misma URL.
2. Consumir primero candidatos adicionales ya devueltos por la búsqueda cuando un documento no sea utilizable.
3. Realizar una nueva búsqueda solamente cuando el lote actual no pueda alcanzar el objetivo de fuentes citables.
4. Mantener límites globales de intentos, tiempo, bytes y candidatos por ejecución.
5. Registrar en la traza la acción elegida, su motivo, espera aplicada, candidato sustituido y resultado final.
6. Conservar el mismo modelo de seguridad para todas las URLs, incluidas redirecciones y variantes.

### Implementación realizada

- `document_fetcher.fetch_main_text` reintenta timeouts, errores 5xx y límites 429 dentro del presupuesto. Solo reintenta `PENDING` si existe `Retry-After` y cabe íntegro en el máximo configurado. Los fallos de conexión y TLS avanzan a otro candidato.
- `ACCESS_DENIED`, `NOT_FOUND`, contenido no compatible y fallos de extracción no se repiten sobre la misma URL.
- Evidence Search reserva hasta dos posiciones de `max_results` para sustituciones. La programación inicial, las sustituciones y el fallback comparten ese máximo. Cada sustitución queda en `recovery_trace`; el informe cuenta acciones, recuperaciones y agotamientos.
- La configuración desplegable declara explícitamente los límites de reintento (`EVIDENCE_FETCH_*`).
- Las pruebas cubren `202 → 200` con espera indicada por el servidor, `429 → 200`, `403` sin reintento, espera superior al presupuesto, sustitución dentro del lote y límite total de documentos.

El presupuesto temporal de reintento es por documento. `max_results` limita los documentos intentados en toda la solicitud; el multiplicador de candidatos solo limita lo que se retiene del proveedor. El límite de tamaño existente se aplica a PDF. Sigue pendiente un límite agregado de bytes y tiempo para toda la solicitud.

### Comparación de campañas `e2e-20261025-093335` y `e2e-20261025-102837`

Ambos manifiestos tienen los mismos 11 casos y hashes gold, el mismo commit (`c92c20184430de7764b1c7fb0d567e80d9acc2fd`), `git_dirty=true` y cero respuestas de Evidence Search servidas desde caché. La campaña de las 10:28 registra `routing-taxonomy-v2`; por tanto, la corrección genérica del Source Router estaba activa. Como los manifiestos no incluyen un snapshot del diff dirty, la atribución del resto de cambios locales al descargador es menos exacta.

| Métrica de Evidence Search | `09:33` | `10:28` | Variación |
| --- | ---: | ---: | ---: |
| Respuestas | 32 | 33 | +1 |
| Documentos intentados | 156 | 97 | −37,8 % |
| Documentos extraídos/citables | 83 | 66 | −20,5 % |
| Extracción por documento intentado | 53,21 % | 68,04 % | +14,84 pp |
| Solicitudes HTTP | 195 | 158 | −19,0 % |
| Respuestas HTTP | 147 (75,38 % de solicitudes) | 155 (98,10 %) | +8 respuestas; +22,72 pp en tasa de respuesta |
| Respuestas HTTP exitosas | 116 (59,49 % de solicitudes) | 80 (50,63 %) | −36; −8,86 pp |
| Acciones de retry | 39 | 1 | −97,4 % |
| Sustituciones de candidatos | 13 | 2 | −84,6 % |
| Recuperaciones por retry / sustitución | No registradas como recuperadas | 0 / 0 | Sin recuperación medida |

La tasa de extracción por intento sube mientras baja el volumen total (83 → 66). Es compatible con la selección de un conjunto menor de candidatos más recuperables, pero las campañas no aíslan una sola variable y los manifiestos no fijan el diff dirty; no debe tratarse como estimación causal del efecto del retry. Además, cae la tasa de HTTP 2xx, aunque casi todas las solicitudes de la campaña nueva reciben alguna respuesta. Son métricas distintas: no presentar la mayor tasa de respuesta como mayor tasa de HTTP exitoso. El umbral de descarga útil del 75 % todavía no se alcanza.

### Resultado de Source Router

| Métrica del router | `09:33` (taxonomía v1) | `10:28` (taxonomía v2) |
| --- | ---: | ---: |
| Ejecuciones con router | 10 | 11 |
| Evaluación `PASS` / `PARTIAL` | 8 / 2 | 10 / 1 |
| Coincidencia con dominio esperado | 8/10 (80 %) | 10/11 (90,9 %) |
| Coincidencia en los 10 casos comunes | 8/10 | 9/10 |
| Dominios descubiertos / clasificados | 77 / 74 | 78 / 78 |
| Fuentes seleccionadas acumuladas | 45 | 42 |

La mejora más clara se da en `ES_RENEWABLE_GENERATION_2024_TRUE`: en la primera campaña el router descartó `ree.es` por `SOURCE_TYPE_INELIGIBLE`, seleccionó `comercio.gob.es` y la ruta quedó `PARTIAL`. En la segunda, clasificó `ree.es` como `INFRASTRUCTURE_OPERATOR`, la seleccionó en primer lugar (puntuación 0,975), mantuvo `libreria.miteco.gob.es` como segunda fuente y obtuvo `PASS`. Es una corrección de taxonomía y elegibilidad genérica, no una regla por dominio.

El efecto aguas abajo es visible en esa misma ruta local: `17` documentos intentados, `0` extraídos y `34` solicitudes HTTP en `09:33`; frente a `3` intentados, `3` extraídos/citables y `5` solicitudes en `10:28`. Es un avance muy fuerte en eficiencia para el caso afectado, aunque no explica por sí solo los totales de toda la campaña.

El resultado E2E global pasa de 10/11 a 9/11 casos correctos. La campaña nueva registra errores de retrieval/citación, consenso y casos indeterminados. Por tanto, se confirma la mejora del router y de la recuperación local del caso energético, pero no una mejora global del veredicto.

Informes: [campaña `e2e-20261025-093335`](../tests/data/evaluation/artifacts/e2e-20261025-093335/report.md) y [campaña `e2e-20261025-102837`](../tests/data/evaluation/artifacts/e2e-20261025-102837/report.md).

### Qué obtendremos

- Menos `202` vacíos tratados como resultado final.
- Sustitución de accesos denegados por candidatos alternativos sin insistir en el mismo recurso.
- Mejor aprovechamiento de los resultados ya pagados al proveedor de búsqueda.
- Una política reproducible y comprobable por clase de fallo.

### Pruebas realizadas y pendiente de cierre

- Cubiertas en unitarios: secuencias `202 → 200` con `Retry-After`, `429 → 200`, `403` sin reintento, omisión de `202` sin espera y error de conexión, agotamiento del presupuesto, sustitución desde el mismo lote y máximo global de documentos.
- Implementado: seguimiento manual de redirecciones con validación de cada destino, límite de saltos, rechazo de bucles, destinos no públicos y degradación HTTPS→HTTP; las pruebas unitarias de estas reglas son simuladas.
- Pendiente de seguridad: la comprobación DNS y la conexión HTTP no están fijadas a la misma IP, por lo que aún existe riesgo de DNS rebinding. Antes de cerrar la auditoría hay que fijar la IP validada a la conexión o aplicar una política de egreso que bloquee destinos internos, y validar esa barrera en el despliegue.
- Campaña completa ya ejecutada: `e2e-20261025-102837`. No alcanza el objetivo agregado de descarga útil del 75 % y no sustituye la validación de seguridad de redirecciones.

### Puerta de aceptación

- Ningún bucle ni exceso del presupuesto configurado.
- Ningún descenso de documentos citables por sustituciones incorrectas.
- Mantener límites de intentos y documentos, sin regresión en documentos citables en una comparación controlada.
- Objetivo inicial de descarga útil: **al menos 75 %**, acompañado siempre de conteos brutos; resultado actual **68,04 %**.
- Cerrar la mitigación de DNS rebinding antes de aprobar la puerta de seguridad.

---

## Bloque 3. Historial compartido y caché por resultado

**Estado:** implementación parcial en curso; el historial negativo compartido ya tiene identidad estable, TTL por clase, contadores/fechas, recuperación e instrumentación. Falta la caché positiva de contenido extraído, cobertura de pruebas de persistencia multi-réplica y medir la aceptación con campañas fría/caliente.

### Propósito

Evitar que distintos validadores o réplicas repitan inmediatamente una descarga que ya produjo un resultado conocido, sin convertir un fallo temporal en un bloqueo permanente.

El repositorio ya contiene primitivas de caché y memoria de URLs no utilizables. Este bloque debe auditarlas y evolucionarlas sobre la taxonomía del bloque 1; no debe crear un segundo mecanismo incompatible.

### Cambios previstos

1. Definir una identidad documental canónica que no fusione recursos distintos accidentalmente.
2. Separar:
   - Caché positiva de contenido extraído y validado.
   - Historial negativo o pendiente por identidad documental.
   - Caché de respuesta de búsqueda.
3. Persistir en MongoDB clase, primer y último intento, contador, expiración, política aplicada y éxito posterior.
4. Aplicar TTL por clase:
   - Corto para `PENDING`, `RATE_LIMITED`, red y errores 5xx.
   - Intermedio para accesos denegados y contenido vacío.
   - Positivo según frescura del documento y política activa.
5. Invalidar o rebajar el historial negativo cuando exista un éxito posterior.
6. Permitir continuar de forma degradada y limitada cuando MongoDB no esté disponible.
7. Registrar `cache_hit`, `negative_history_hit`, intentos evitados y antigüedad de la entrada.

### Qué obtendremos

- Menos intentos repetidos sobre el mismo fallo.
- Menor latencia y consumo de proveedor en validadores sucesivos.
- Comportamiento compartido entre pods y reinicios.
- Expiración explícita que permite volver a probar recursos recuperables.

### Pruebas previstas

- Dos validadores secuenciales sobre la misma identidad.
- Dos réplicas compartiendo historial.
- Expiración por TTL y reintento posterior.
- Invalidación tras éxito.
- MongoDB temporalmente no disponible.
- Campaña E2E fría seguida de una campaña caliente documentada.

### Puerta de aceptación

- Al menos **30 % menos intentos repetidos** sobre fallos persistentes en la campaña caliente.
- Sin reducción de `documents_citable` respecto a la campaña fría.
- Cero reutilizaciones de contenido no validado como caché positiva.
- Todos los ahorros de intentos reconstruibles desde artefactos.

### Implementación aplicada (2026-10-25)

- Se amplió la colección existente `evidence_unusable_urls_v1`; no se creó una caché negativa paralela.
- La identidad compartida es SHA-256 de la URL normalizada (incluida su query), y se conservan lecturas de registros legacy sin `active_failure`.
- Las clases `ACCESS_DENIED`, `RATE_LIMITED`, `SERVER_FAILURE`, `NETWORK_FAILURE`, `EMPTY_CONTENT` y `NOT_FOUND` tienen TTL configurables; Mongo guarda clase, política, primer/último intento, número acumulado de intentos, expiración y último éxito. Un éxito desactiva la penalización, sin borrar el historial inmediatamente.
- La selección sigue siendo operativa si Mongo no está disponible: el historial local está acotado por TTL y máximo de entradas. La respuesta expone `negative_history_hits` e `negative_history_attempts_avoided`.
- Pendiente: caché positiva del texto extraído (separada de historial y caché de respuesta), pruebas de persistencia/expiración/recuperación contra colección simulada o Mongo y campaña E2E fría/caliente. Por ello, el bloque no supera todavía su puerta de aceptación.

---

## Bloque 4. Singleflight y viewer del embudo

**Estado:** pendiente.

### Propósito

Evitar que peticiones concurrentes descarguen el mismo recurso al mismo tiempo y presentar las métricas de los bloques anteriores de forma operable.

### Cambios previstos: singleflight

1. Coordinar por identidad documental las descargas simultáneas.
2. La primera petición adquiere un lease y ejecuta el fetch; las demás esperan el resultado dentro de su presupuesto.
3. Persistir el lease o usar un mecanismo compartido que funcione entre réplicas, no solo dentro de un proceso.
4. Añadir expiración y recuperación del lease si el propietario muere.
5. No compartir resultados entre políticas o identidades documentales incompatibles.
6. Medir `leader_fetches`, `joined_requests`, tiempo esperado, leases expirados y fetches evitados.

### Cambios previstos: viewer

1. Mostrar el embudo:

```text
candidatos → documentos intentados → respuestas HTTP → HTTP 2xx
           → documentos extraídos → documentos citables
```

2. Mostrar distribución por `fetch_outcome` y evolución entre campañas.
3. Separar campañas frías y calientes.
4. Señalar respuestas de caché, historial negativo y peticiones unidas por singleflight.
5. Mostrar denominadores y conteos junto a cada porcentaje.
6. Permitir inspeccionar la traza de una evidencia sin presentar URLs como etiquetas métricas agregadas.

### Qué obtendremos

- Una única descarga efectiva cuando varios validadores soliciten el mismo recurso simultáneamente.
- Menor carga sobre servicios remotos y menor probabilidad de rate limiting provocado por el propio sistema.
- Diagnóstico visual de dónde se pierde cada candidato.
- Comparación directa entre campañas y entre estado frío/caliente.

### Pruebas previstas

- Varias coroutines y varias réplicas solicitando la misma identidad.
- Fallo del líder y recuperación tras expirar el lease.
- Espera que excede el presupuesto del consumidor.
- Identidades y políticas distintas que no deben agruparse.
- Contrato y snapshot del viewer.
- Campaña E2E completa y prueba concurrente dirigida.

### Puerta de aceptación

- Una sola descarga remota para solicitudes concurrentes equivalentes.
- Cero deadlocks y recuperación demostrada de leases abandonados.
- Ninguna mezcla de documentos o políticas incompatibles.
- El viewer reproduce exactamente los totales de `report.json`.
- Reducción medible de solicitudes HTTP sin pérdida de documentos citables.

---

## Orden de ejecución y campañas

| Hito | Implementación | Campaña de cierre | Decisión posterior |
| --- | --- | --- | --- |
| Línea base | Estado anterior | `e2e-20261024-191753` | Medir el problema |
| Bloque 1 | Clasificación y métricas | `e2e-20261024-200925` | Taxonomía disponible; pasar a acciones |
| Bloque 2 | Reintentos, sustitución y validación manual de redirecciones | `e2e-20261025-102837` | 68,04 % de descarga útil; Source Router ya recupera `ree.es`; cerrar DNS rebinding y revisar la tasa HTTP 2xx |
| Bloque 3 | Historial y caché | Una fría y otra caliente | Medir intentos evitados y ausencia de regresión |
| Bloque 4 | Singleflight y viewer | Campaña completa más prueba concurrente | Cerrar el ciclo y fijar nueva línea base |

No se deben agrupar los bloques 1 y 2 en una única medición, porque perderíamos la línea base observada antes de cambiar el comportamiento. Los bloques 3 y 4 pueden desarrollarse en proximidad, pero deben mantener pruebas y métricas separadas: el bloque 3 ahorra repeticiones temporales y el bloque 4 evita concurrencia duplicada.

## Métricas que se publicarán en todas las campañas siguientes

- Casos, ejecuciones puntuables y ejecuciones de observación.
- Decisión correcta, pase E2E estricto y quorum degradado.
- Respuestas reales de Evidence Search y cache hits.
- Llamadas al proveedor y candidatos retornados.
- Documentos programados e intentados.
- Solicitudes HTTP, respuestas y respuestas 2xx.
- Documentos extraídos y citables.
- Distribución completa de `fetch_outcome`.
- Reintentos, sustituciones y motivo de parada.
- Intentos evitados por historial, caché o singleflight.
- Latencia p50/p95 y presupuesto agotado cuando estén disponibles.

Cada porcentaje se acompañará de numerador y denominador. Ninguna mejora se atribuirá a un bloque si cambiaron simultáneamente los casos, modelos, políticas o condiciones de caché sin quedar documentado.
