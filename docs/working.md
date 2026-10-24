# Plan priorizado de estabilización E2E y Evidence Search

**Campaña de referencia:** `e2e-20261024-093320` (24 de octubre de 2026).

**Estado:** el código del antiguo punto 1 está implementado localmente; faltan homologación del gold y campañas publicadas. El resto son propuestas pendientes.

**Criterio de orden:** impacto observado, urgencia, coste de implementación y riesgo. La puntuación es una decisión de prioridad (sobre 10), no una predicción estadística.

## Línea base y significado de los porcentajes

El [informe de la campaña](../tests/data/evaluation/artifacts/e2e-20261024-093320/report.md) registra **21/33 unidades E2E correctas (63,6 %)**, **100 ejecuciones**, de las que **97 son puntuables**, y **tres errores técnicos en Source Router**. La revisión del consenso da 30/33 decisiones correctas (90,9 %), pero esa cifra y la puntuación E2E miden cosas distintas. Evidence Search obtuvo al menos una fuente citable en las 97 ejecuciones completadas; **293/435 fuentes seleccionadas tuvieron descarga `ok` (67,4 %)** y **44/94 referencias fueron citables (46,8 %)**.

Los porcentajes de cada punto son **objetivos de verificación**, salvo cuando se indica expresamente un máximo aritmético. No se suman: un mismo caso puede verse afectado por varios cambios. Usaremos puntos porcentuales (pp) para diferencias entre tasas, y reducción relativa (%) para intentos, latencia o coste. Una mejora de clasificación del informe nunca se presentará como mejora de exactitud factual.

Se calcularán siempre los denominadores por unidad E2E, validador, intento, recurso, fuente y referencia; no se intercambiarán. Para atribuir cambios, se compararán campañas con mismos casos y hashes, configuración efectiva, estrategia, modelos y condiciones de caché, variando un componente por vez cuando sea posible. Con solo 33 unidades, los umbrales de aceptación son señales operativas y se acompañarán de los conteos brutos y de revisión de casos.

### Orden de inversión

| Orden | Trabajo | Prioridad | Mejora que se verificará |
| ---: | --- | ---: | --- |
| 1 | Homologar y publicar el evaluador corregido | 10/10 | 7/33 (21,2 %) dejan de figurar falsamente como error de extracción; sin prometer más aciertos |
| 2 | Resolver los timeouts de Source Router | 9/10 | errores técnicos 3/33 → 0/33; hasta 9,1 pp de unidades dejan de fallar por esta causa |
| 3 | Medir el embudo de Evidence Search | 9/10 | 100 % de ejecuciones con contadores, denominadores y motivo de parada reconstruibles |
| 4 | Aclarar el contrato de citas | 8,5/10 | 2/97 errores de cita observados → 0 en repetición comparable; atribuir la causa de cada uno |
| 5 | Recuperación genérica mínima | 8/10 | descargas útiles 67,4 % → ≥ 75 % (+7,6 pp); ≥ 80 % como objetivo posterior |
| 6 | Caché negativa compartida | 7,5/10 | ≥ 30 % menos intentos repetidos sobre fallos persistentes, sin pérdida de fuentes citables |
| 7 | Coherencia explícita del veredicto | 7/10 | 100 % de contradicciones inequívocas del conjunto de prueba detectadas; falso positivo ≤ 1 % |
| 8 | Suficiencia de evidencia en observación | 6/10 | +15 pp de búsquedas con dos fuentes independientes entre las que tienen candidatos viables, antes de activarla |
| 9 | Experimento Ollama con evidencia congelada | 6/10 como experimento | medir paridad: diferencia de decisión ≤ 5 pp e invalidez JSON ≤ 2 %; sin mejora presupuesta |
| 10 | Circuit breaker distribuido | 5/10, condicionado | ≥ 50 % menos intentos durante degradaciones demostradas, sin bloquear recursos sanos |
| 11 | Aritmética declarada y configuración avanzada | 5/10, condicionado | 100 % de cálculos declarados erróneos detectados en fixtures; coste/beneficio por medir |
| 12 | Autoconfiguración de políticas | 2/10 ahora | ninguna activación automática; medir propuestas útiles antes de invertir |

**Regla de arquitectura:** la configuración funcional y la persistencia operativa de Evidence Search viven en MongoDB. El repositorio contiene código, esquemas, migraciones y fixtures, pero no políticas efectivas por dominio; ConfigMaps y variables de entorno solo aportan el bootstrap técnico y los secretos siguen en el mecanismo de secretos de la plataforma. Una réplica nueva necesita configuración activa válida en MongoDB para estar ready. Los pods en ejecución pueden conservar temporalmente el último snapshot válido durante una incidencia de MongoDB.

Los dominios de la campaña son casos de prueba. El motor y sus evaluadores deben seguir siendo genéricos: incorporar una fuente nueva equivale a registrar datos validados en MongoDB, no a introducir condicionales por host.

## 1. Homologar el evaluador y la línea base — 10/10

Queremos que el informe distinga identidad de la aserción, taxonomía, decisión y salud operativa. El código de este punto ya está preparado localmente; su valor se materializa al revisar el gold y publicar una campaña comparable, porque una métrica corregida no demuestra por sí misma que el producto haya mejorado.

### Diseño de implementación

1. Conservar cuatro resultados independientes: `assertion_match`, `taxonomy`, `decision` y `operational`. Publicar `decision_correct` y `strict_pipeline_pass` con reglas explícitas y esquema versionado.
2. Revisar el matcher de `tests/evaluation/core/common_metrics.py`: fechas, años, cifras normalizadas, unidades, identificadores legales, negaciones y cuantificadores absolutos son anclas críticas. Un conflicto produce `INCOMPATIBLE` y deja la aserción sin emparejar aunque el texto restante sea parecido.
3. En `tests/evaluation/core/orders.py`, separar `TAXONOMY_MISMATCH` de `EXTRACTION_ERROR`. Un desacuerdo de categoría seguirá fallando la puerta estricta, pero no convertirá un consenso correcto en decisión incorrecta.
4. En reporting y viewer, expresar retrieval como `NO_CITABLE_EVIDENCE`, `PARTIAL`, `REFERENCE_CITABLE` o `AVAILABLE`; mantener la cobertura léxica como métrica continua. Comprobar que se leen artefactos antiguos.
5. Homologar humanamente los once JSON de `official-gold-v0`, en especial el falso GDPR de 2020 frente a la aserción de 2018. Documentar procedencia y fecha efectiva antes de regenerar hashes; no cambiar un gold para hacerlo coincidir con el sistema.
6. Reconstruir offline la campaña histórica y después publicar casos dirigidos y una campaña completa sobre el mismo despliegue. Registrar el estado Git sucio existente y no mezclarlo con cambios nuevos de otro punto.

### Comprobación y mejora

- Pruebas de anclas: 2020/2018, 42,5 %/45 %, 705/720, negación, unidades e identificadores. Prueba de quorum degradado con dos votos válidos.
- Objetivo: reclasificar los **siete falsos `EXTRACTION_ERROR`** como `TAXONOMY_MISMATCH` cuando el texto realmente coincida: **7/33 = 21,2 %** de unidades cambian de diagnóstico, **0 pp de mejora factual atribuible**.
- La reconstrucción debe mostrar por separado 30/33 decisiones correctas y 21/33 pases estrictos históricos, o explicar cada diferencia con el artefacto correspondiente. Ningún contexto citable puede producir `Retrieval=FAIL` solo por cobertura léxica incompleta.

## 2. Corregir los timeouts de Source Router — 9/10

Queremos que una ruta lenta no convierta una orden con evidencia y quorum posibles en un fallo técnico. Primero necesitamos saber en qué fase se consume el tiempo y si cliente y servidor aplican límites incompatibles; luego corregiremos la causa que indiquen las trazas.

### Diseño de implementación

1. Persistir por invocación `started_at`, fase (`cache`, descubrimiento, clasificación, MongoDB, proveedor), duración, timeout configurado, resultado y excepción sanitizada en el artefacto de la orden.
2. Instrumentar p50/p95/p99 y ratio de timeout por fase, estrategia, proveedor y estado de caché, con etiquetas de baja cardinalidad.
3. Trazar el presupuesto extremo a extremo desde `validate-asertions` hasta Source Router. Asegurar que el timeout del cliente deja margen para la respuesta y que los reintentos consumen un presupuesto total, con máximo de intentos.
4. Reintentar solo errores clasificados como transitorios. Si MongoDB contiene una ruta anterior todavía válida bajo una política activa, permitir su uso como `stale_route_used` con versión y antigüedad registradas; nunca usarla sin condiciones de validez.
5. Distinguir `quorum_degraded` de ausencia de consenso cuando falle un validador. Añadir prueba de timeout inyectado y recuperación sin doble publicación ni bucle de reintentos.

### Comprobación y mejora

- Base: **3/33 unidades (9,1 %) afectadas por fallo técnico en Source Router**. Objetivo: **0/33** en dos campañas completas comparables; 9,1 pp es el máximo de unidades que podrían dejar de fallar por esta causa, no una predicción de exactitud.
- Se aceptará solo si el p95, los reintentos y los usos de ruta stale quedan dentro del presupuesto registrado, sin introducir rutas incorrectas nuevas.

## 3. Reconstruir el embudo de Evidence Search — 9/10

Queremos saber exactamente dónde se pierden las fuentes: descubrimiento, programación, descarga, extracción, citabilidad o selección de referencia. Esta instrumentación debe permitir decidir si los puntos 5, 6 y 8 compensan su coste y comparar modelos sin confundir calidad del LLM con calidad del corpus.

### Diseño de implementación

1. Definir un evento/registro por ejecución con `execution_id`, versión de esquema, estrategia, política activa de MongoDB y contadores para `provider_calls`, `urls_returned`, `candidates_retained`, `documents_scheduled`, `fetch_attempts`, `downloads_nonempty`, `documents_extracted`, `documents_citable`, `references_selected`, `references_citable` y `evidence_delivered`.
2. Registrar para cada intento clase de fallo, estado HTTP si existe, bytes, tiempo, URL normalizada en artefacto protegido, identidad canónica y decisión de caché. Las métricas agregadas usarán `policy_id`, clase y `scope_bucket` controlados; no URL ni host libre como etiqueta.
3. Versionar el contrato de `retrieval_summary` y persistir los contadores por assertion, orden y campaña. El informe offline recalculará los totales desde eventos y señalará discrepancias.
4. Definir tasas con denominador visible: descarga útil = `downloads_nonempty/fetch_attempts` para intentos; éxito de fuente seleccionada = fuentes `fetch_status=ok`/fuentes seleccionadas; referencia citable = referencias citables/referencias seleccionadas. No reutilizar un nombre para tasas distintas.
5. Crear un panel o informe compacto que muestre el embudo por estrategia y comparación frío/caliente, además de p50/p95, bytes y coste del proveedor cuando esté disponible.

### Comprobación y mejora

- Objetivo de cobertura: **100 % de ejecuciones** con contadores y `stop_reason`, y **100 % de totales** del informe reproducibles desde artefactos, admitiendo solo una diferencia documentada por redondeo.
- El beneficio directo esperado en tasa de descarga es **0 pp**: este punto mide y atribuye; no mejora el fetch por sí mismo.

## 4. Aclarar la relación de las citas con la aserción — 8,5/10

Queremos que `TRUE` cite apoyo y `FALSE` cite contradicción sin depender de un booleano ambiguo. La relación debe referirse siempre a la aserción, y el servidor debe validar los identificadores de fragmento sobre el corpus entregado.

### Diseño de implementación

1. Versionar `validator-response-v2` en `api/common/models/async_models.py`: cada cita declara `context_id`, `relation_to_assertion` (`SUPPORTS`, `CONTRADICTS`, `NEUTRAL`) y una razón breve.
2. Actualizar schema y prompt en `api/common/utils/validation_prompt.py` y `api/validate-asertions/main.py`. El modelo declara IDs y relaciones; URL, texto y origen se reconstruyen del corpus en el servidor.
3. En `api/common/utils/evidence.py`, exigir `SUPPORTS` para un `TRUE` concluyente y `CONTRADICTS` para un `FALSE` concluyente; preservar `UNKNOWN` cuando falte soporte suficiente. Registrar errores diferenciados.
4. Durante la transición aceptar v1 y v2, registrar `legacy_supports_converted`, y evitar inferir semántica de un `supports=false` ambiguo cuando no pueda saberse si significa contradicción o ausencia de apoyo: clasificarlo como legacy no concluyente.
5. Actualizar artefactos y viewer; retirar v1 cuando el contador de clientes legacy sea cero durante dos campañas completas.

### Comprobación y mejora

- Probar toda la matriz veredicto × relación, IDs inexistentes, duplicados, fragmentos no citables y compatibilidad v1. Base: **dos errores de cita entre 97 ejecuciones puntuables (2,1 %)**, sin atribuir ambos a la ambigüedad del contrato; objetivo: **0/97** en repetición comparable, sin aumentar citas aceptadas sin soporte real.
- Este cambio mejora el contrato y la auditabilidad. Un descenso de errores no se contará automáticamente como aumento de decisiones correctas.

## 5. Implementar la recuperación genérica mínima — 8/10

Queremos recuperar más documentos útiles mediante un conjunto pequeño de acciones reutilizables. Las fuentes institucionales observadas sirven para comprobar patrones de fallo; una fuente nueva se describirá con datos en MongoDB sin añadir lógica por dominio.

### Diseño de implementación

1. En `api/evidence-search/app/document_fetcher.py`, separar normalización, clasificación del resultado, plan de acciones y validación. Clases iniciales: `usable`, `empty`, `pending`, `rate_limited`, `forbidden`, `not_found`, `transient`, `tls_error` e `invalid_content`.
2. Implementar solo cuatro acciones al inicio: URL original, redirección HTTP permitida, enlace `canonical`/`alternate` presente en la respuesta y reintento transitorio con `Retry-After`, backoff y jitter. Añadir otras acciones cuando una métrica demuestre necesidad.
3. Crear en MongoDB `evidence_fetch_policies_v1` con política global, versión inmutable, selectores declarativos y límites. `evidence_config_activations_v1` apunta a la versión activa; el motor toma un snapshot validado al arrancar y refresca por versión. Los esquemas y fixtures viven en Git; la configuración funcional, en MongoDB.
4. Validar cada URL tras redirección o enlace contra SSRF, DNS y origen permitido. Mantener TLS. Una variante solo se acepta si la relación documental o un identificador canónico demuestra equivalencia; un parecido textual aislado no basta.
5. Acotar variantes, intentos, tiempo total, bytes y enlaces por documento. Registrar `requested_url`, `canonical_resource_id`, política, acciones, estados, URL final y motivo de rechazo en `resolution_trace` persistida con la ejecución.
6. Conservar el descargador actual como acción global. Añadir una fuente sintética por documento MongoDB y fixture para demostrar que no se modifica el motor.

### Comprobación y mejora

- Fixtures para 202 vacío, 403, 429, 5xx, timeout, PDF sin texto, redirección insegura y documento cambiado. Los casos EUR-Lex, Parlamento, Consejo y Red Eléctrica son regresiones, no implementaciones particulares.
- Base: **293/435 fuentes seleccionadas con descarga `ok` (67,4 %)**. Primera puerta: **≥ 75 % (+7,6 pp)** en campañas comparables, sin aceptar equivalencias falsas; **≥ 80 % (+12,6 pp)** queda como objetivo posterior condicionado a resultados. Se reportará también la tasa de contenido citable: descargar no implica citar.

## 6. Evitar reintentos inútiles con caché negativa — 7,5/10

Queremos que un fallo estable no consuma de nuevo tiempo y presupuesto en cada validador, sin bloquear otros documentos sanos. MongoDB compartirá el estado entre réplicas y cada penalización expirará o se invalidará tras un éxito.

### Diseño de implementación

1. Normalizar `resource_key` y `canonical_resource_id` sin fusionar documentos diferentes. Separar la caché positiva de contenido validado, la de consulta y el estado negativo; persistirlos en colecciones MongoDB con índices únicos y TTL.
2. Evolucionar `evidence_unusable_urls_v1` con alcance, clave, `failure_class`, intentos, `first_seen_at`, `last_seen_at`, `retry_after`, versión de política y resultado exitoso posterior.
3. Aplicar TTL por clase mediante política versionada en MongoDB. Como hipótesis inicial: minutos para transitorios/429/pendiente, más tiempo para fallo estable de recurso; respetar `Retry-After` y limitar siempre los máximos.
4. Hacer atómicas las actualizaciones; `positive cache` solo guardará contenido útil. Una variante distinta se podrá intentar cuando no esté penalizada por la misma identidad y la misma causa.
5. Si MongoDB falla durante una ejecución ya iniciada, continuar con la política activa cargada y sin penalización compartida, emitir `cache_degraded` y limitar los reintentos localmente. Un pod nuevo sin configuración válida no estará ready.

### Comprobación y mejora

- Probar dos búsquedas y dos réplicas, expiración, invalidación tras éxito y ausencia temporal de MongoDB. Medir `attempts_saved` y tiempo ahorrado sin contarlo como descarga exitosa.
- Objetivo: **≥ 30 % menos intentos repetidos** sobre el conjunto de fallos persistentes en la segunda/tercera repetición; `documents_citable` no debe bajar. El dato histórico de cero cache hits no permite inferir aún el porcentaje de ahorro global.

## 7. Detectar contradicciones explícitas del veredicto — 7/10

Queremos impedir que un voto concluyente contradiga inequívocamente su propia explicación. La primera versión debe detectar únicamente señales claras y registrar una abstención auditada; ampliar la interpretación de lenguaje natural sin evidencia de precisión crearía falsos positivos.

### Diseño de implementación

1. Tras validar JSON y citas, identificar conclusiones explícitas del tipo «la afirmación es falsa/verdadera» referidas a la aserción. Mantener una lista pequeña de patrones y negaciones probados, con ámbito lingüístico declarado.
2. Si la conclusión contradice `resultado`, conservar la respuesta original, emitir `VERDICT_EXPLANATION_CONTRADICTION` y producir resultado efectivo `UNKNOWN`. Registrar el motivo en `excluded_validators` cuando altere el consenso.
3. Procesar la regla después del contrato de citas v2 para no confundir «la cita contradice la aserción» con una explicación contradictoria. Versionar la política de exclusión en MongoDB si se configura en tiempo de ejecución.
4. Dejar la verificación de cálculos y la semántica de agregados fuera de esta primera entrega. Revisar manualmente los casos de divergencia antes de ampliar patrones.

### Comprobación y mejora

- Corpus de fixtures positivos, negativos y frases citadas ajenas a la conclusión. Objetivo: **100 % de contradicciones inequívocas detectadas** en ese corpus y **≤ 1 % de falsos positivos** en respuestas históricas revisadas.
- Base observada: al menos un voto incoherente. No hay denominador suficiente para prometer una mejora porcentual de exactitud E2E; informar cuántos votos cambian a `UNKNOWN` y su efecto en quorum.

## 8. Evaluar suficiencia antes de exigir dos fuentes — 6/10

Queremos saber cuántas búsquedas podrían terminar con dos fuentes citables e independientes y cuánto tiempo adicional costaría. La exigencia empezará en observación; solo se activará cuando el corpus de candidatos y la latencia demuestren que ayuda.

### Diseño de implementación

1. Distinguir `search_candidates`, `attempted_resources`, `downloaded_sources`, `citable_sources` y `independent_groups` en el contrato de resultado.
2. Almacenar un perfil versionado en `evidence_quality_profiles_v1` de MongoDB. Requisitos iniciales: dos fuentes citables y dos grupos independientes **cuando haya al menos dos candidatos viables**; conservar el límite de tiempo, documentos, bytes y llamadas al proveedor.
3. Usar por defecto el dominio registrable para independencia. `evidence_source_catalog_v1` podrá agrupar organizaciones, espejos o fuentes sindicadas; el algoritmo leerá esos metadatos sin condicionales por dominio.
4. Tras cada resultado, estimar ganancia marginal de candidatos restantes por relevancia, autoridad declarada, cobertura, probabilidad de descarga útil, diversidad y coste. Seguir con candidatos locales antes de llamar de nuevo al proveedor; detener cuando se cumpla la política o no haya ganancia positiva.
5. Exponer `policy_id`, versión, requisitos cumplidos, candidatos viables, presupuesto y `stop_reason`. Diferenciar `complete`, `partial`, `insufficient` y `cancelled`.
6. Ejecutar primero el evaluador en observación sin variar el flujo. Activar luego para una fracción de órdenes y permitir revertir desde MongoDB al perfil previo.

### Comprobación y mejora

- Base de dos fuentes independientes: **no medida** en la campaña; no se inventará. Medirla primero por estrategia y sobre búsquedas con dos candidatos viables.
- Objetivo experimental: **+15 pp** en la tasa de búsquedas que entregan dos grupos independientes citables frente al control, sin subir p95 ni coste por orden más del **20 %**. Si no se cumple, conservar la política en observación y revisar el cuello de botella del punto 5.

## 9. Probar Ollama con evidencia congelada — 6/10 como experimento

Queremos medir si un modelo local aporta privacidad, independencia o menor coste manteniendo una calidad comparable. La comparación debe recibir las mismas aserciones y fragmentos que los validadores actuales; un cambio de recuperación de fuentes invalidaría la comparación de modelos.

### Diseño de implementación

1. Añadir un proveedor `ollama` a `api/common/llm`, reutilizando la interfaz existente y el endpoint compatible con OpenAI. Validar localmente el JSON contra el modelo Pydantic aunque el servidor anuncie salida estructurada.
2. Mantener URL y nombre de modelo en la configuración funcional de modelos de MongoDB; el secreto o mecanismo de acceso al servidor se gestionará como secreto de plataforma. Registrar versión exacta, cuantización, contexto y recursos del servidor.
3. Empezar por clasificación de Source Router o extracción acotada. Para RAG, usar `gold-evidence`/replay con corpus congelado y comparar decisiones, `UNKNOWN`, citas verificadas, JSON inválido, p50/p95, memoria y coste de infraestructura.
4. Ejecutar el experimento en un host con recursos suficientes. La máquina inspeccionada tiene cuatro CPU, 10 GiB de RAM total, aproximadamente 2,9 GiB disponibles y ninguna GPU NVIDIA visible; aquí una prueba de rendimiento RAG sería poco representativa.
5. Mantener la prueba aislada de las campañas de aceptación hasta que pase el mismo contrato de citas y los umbrales de calidad.

### Comprobación y mejora

- Umbrales de exploración, **no mejoras esperadas**: diferencia de acierto de decisión **≤ 5 pp** respecto al control con el mismo corpus; respuestas JSON inválidas **≤ 2 %**; ninguna cita falsa adicional; p95 dentro del presupuesto del servicio.
- El ahorro en euros o dólares queda **sin porcentaje previo**: calcular coste total de hardware, energía y operación frente a la factura de API después de medir throughput. Si falla calidad o latencia, cerrar el experimento sin sustituir el proveedor.

## 10. Añadir circuit breaker distribuido solo si se justifica — 5/10

Queremos reducir tráfico durante degradaciones reales de un origen compartido sin convertir un fallo de documento en bloqueo de todo el origen. La caché negativa del punto 6 cubre primero los fallos de recurso; el circuit breaker se justifica cuando las métricas muestren incidentes agregados y costosos.

### Diseño de implementación

1. Definir en una política MongoDB cuándo varios `failure_class` de transporte abren un circuito para `origin_key` o `authority_group`. Errores de extracción y `404` individuales no abrirán circuitos de origen.
2. Persistir contadores, ventana, estado `CLOSED`/`OPEN`/`HALF_OPEN` y lease de sonda en `evidence_circuit_state_v1`; usar operaciones atómicas e índice TTL.
3. Permitir una sonda exclusiva al expirar la apertura. Un éxito cierra el circuito; un fallo lo reabre con límite y jitter. Registrar cada transición, alcance y versión de política.
4. Probar con dos réplicas y fallos inyectados. Medir bloqueo injustificado de recursos sanos por separado del ahorro de intentos.

### Comprobación y mejora

- Condición de entrada: la observabilidad debe acreditar degradaciones repetidas de origen y al menos **10 % del presupuesto de fetch** perdido en ellas. Si no ocurre, no implementar.
- En incidencias simuladas equivalentes a las reales, objetivo **≥ 50 % menos intentos fallidos** mientras el circuito esté abierto y **0 fuentes sanas** bloqueadas fuera del alcance configurado.

## 11. Validar aritmética declarada y ampliar gobierno de configuración — 5/10

Queremos detectar cálculos explícitos erróneos cuando esos cálculos influyan en el veredicto. La infraestructura avanzada de políticas solo merece trabajo adicional si las políticas MongoDB reales ya exigen activación frecuente, auditoría más profunda o rollback operativo.

### Diseño de implementación

1. Ofrecer un campo opcional `calculations` con expresión, resultado, unidad y `context_ids`. Evaluar únicamente una gramática segura de números, `+`, `-`, `*`, `/` y paréntesis, sin `eval`; comprobar operandos en los fragmentos citados.
2. Si el cálculo decisivo falla, registrar `CALCULATION_MISMATCH` y producir `UNKNOWN`; no corregir automáticamente el número ni introducir ontologías por temática.
3. Medir cuántos validadores emiten cálculos y cuántos casos de error real se capturan antes de exigir ese campo a todos.
4. Para configuración, añadir activación atómica, historial de actor/motivo, snapshots y rollback únicamente sobre las colecciones del punto 5 cuando haya varias versiones reales. Las versiones publicadas serán inmutables y las inválidas no reemplazarán la última válida.

### Comprobación y mejora

- Objetivo de cálculo: **100 % de expresiones erróneas declaradas** detectadas en fixtures y **0 ejecuciones de código** desde el campo. La mejora en veredictos E2E permanece sin estimación por falta de frecuencia base.
- Condición de entrada para el gobierno avanzado: al menos dos políticas activas con cambios operativos repetidos o un rollback manual que haya resultado inseguro. Medir tiempo de cambio y recuperación; buscar **≥ 50 % menos tiempo de rollback**, sin afectar exactitud.

## 12. Proponer políticas a partir de fallos, sin autoactivación — 2/10 ahora

Queremos aprovechar patrones repetidos para sugerir ajustes sin dejar que contenido externo cambie las reglas de recuperación. Este trabajo será útil cuando existan trazas suficientes y un proceso de revisión; en esta campaña aún no sabemos cuántas sugerencias serían correctas.

### Diseño de implementación

1. Agrupar en MongoDB fallos por `failure_class`, acción, alcance y resultado, con límites de cardinalidad y retención.
2. Generar propuestas `DRAFT` con casos afectados, regla sugerida, beneficio estimado y contraejemplos; no activarlas automáticamente.
3. Reproducir cada propuesta contra fixtures y trazas históricas, después ejecutarla en modo observación. Registrar tasa de acierto, falsos positivos y coste.
4. La aprobación y activación seguirá el mismo mecanismo versionado de MongoDB. TLS, SSRF, identidad documental y agrupación de autoridades no serán variables aprendidas del contenido descargado.

### Comprobación y mejora

- Condición de entrada: al menos **20 incidentes repetidos** del mismo patrón y trazas suficientes para replay. Objetivo exploratorio: **≥ 70 % de propuestas útiles** según revisión humana y **0 activaciones automáticas**; no prometer mejora de descarga antes de medirlas.

## Campañas, despliegue y cierre

1. Cerrar puntos 1–4 con pruebas unitarias y casos dirigidos. Publicar una campaña completa antes de cambiar el fetch, de modo que la nueva línea base refleje la medición corregida.
2. Activar el punto 5 sobre políticas MongoDB versionadas, probar hosts sintéticos y los casos afectados, y repetir la campaña. Activar el punto 6 por separado para atribuir el ahorro de intentos.
3. Ejecutar los puntos 7 y 8 en observación, revisar falsos positivos y costes, y activar solo la política que cumpla su puerta. El punto 9 transcurre como benchmark aislado sobre evidencia congelada.
4. Ejecutar dos campañas gold completas consecutivas con mismo commit desplegado, hashes de casos, modelos, políticas MongoDB y estrategia fijados. Primera campaña con caché fría y segunda con estado documentado; reportar por separado las tasas para evitar atribución falsa.
5. Guardar `manifest.json`, `report.json`, `report.md`, órdenes, eventos y viewer sin sobrescribir campañas. Registrar versión y hash de cada política activa, así como su actor de activación; nunca secretos.

### Puertas de aceptación del ciclo

| Dimensión | Base observada | Puerta después de los puntos prioritarios |
| --- | ---: | ---: |
| Decisión correcta | 30/33 | ≥ 30/33, con cada desacierto restante explicado; 33/33 es aspiración, no supuesto |
| Pase E2E estricto | 21/33 | ≥ 31/33 tras homologación del gold y sin falsos fallos de medición |
| Errores técnicos de Source Router | 3/33 | 0/33 en dos campañas |
| Descarga `ok` de fuentes seleccionadas | 293/435 = 67,4 % | ≥ 75 % en primera iteración; ≥ 80 % condicionado |
| Referencia citable | 44/94 = 46,8 % | ≥ 70 %, atribuyendo por separado selección, descarga y citabilidad |
| Handoff de evidencia | 100 % de ejecuciones completadas | 100 % |
| Errores de contrato de cita | 2/97 | 0 en campañas comparables |
| Contadores reconstruibles | No contractualmente garantizado | 100 % de ejecuciones |

Ninguna puerta porcentual se considerará pasada si el denominador es insuficiente, cambian los casos sin anotarlo o aumenta el número de fuentes incorrectas aceptadas. Los puntos 10–12 quedan fuera de la ruta crítica hasta cumplir sus condiciones de entrada.
