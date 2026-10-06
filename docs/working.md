# Plan de trabajo para cerrar v0.0.13

**Propuesta operativa — 2026-09-29.** La versión sigue abierta. Este plan ordena trabajo y evidencia; el estado oficial y los criterios de salida están en [version.md](version.md), y la causa y el cierre de cada incidencia en [issues.md](issues.md). La propuesta se revisa al comienzo de cada iteración, especialmente si aparece un P0/P1 nuevo.

## Cómo se organiza la documentación

| Documento | Contiene | Cuándo se actualiza |
| --- | --- | --- |
| [version.md](version.md) | Estado de v0.0.13, hitos y condiciones globales de salida | Al cambiar el alcance, la evidencia acumulada o una decisión de cierre |
| [issues.md](issues.md) | Una ficha por incidencia: causa, estado, criterio de cierre y límites de la evidencia | Al reproducir, implementar, validar, reabrir o diferir una incidencia |
| `working.md` | Próximo incremento, dependencias, matriz de comprobación y decisiones pendientes | Al iniciar y terminar cada incremento |
| [Guía de evaluación](tests/evaluation.md) y [benchmark LLM](tests/llm-benchmark.md) | Comandos, esquemas y significado de las métricas | Al cambiar el runner o su contrato |
| Artefactos fechados | Entradas, revisión, configuración, órdenes, diagnósticos y resultados | En cada ejecución; no se sustituyen por un relato en estos tres documentos |

Los recursos y artefactos de pruebas se agrupan por tipo bajo `tests/data/`. Los artefactos de `tests/data/evaluation/artifacts/` y `tests/data/frontend-e2e/artifacts/` están ignorados por Git; antes de usarlos para cerrar una incidencia hay que conservar una copia privada, íntegra y fechada, sin credenciales ni datos personales, con commit, dataset/hash y entorno.

## Línea base: comportamiento observado

La evaluación local `eu-official-statistics-2025-v1` del 2026-09-29 publicó tres órdenes LIGHT y guardó 27 registros de validador: tres afirmaciones, tres repeticiones y tres validadores. El manifiesto quedó en `RUNNING` por un fallo local al calcular el informe (`pydantic` ausente); se recuperaron `report.json` y `analysis/analysis.md` desde los resultados persistidos de la campaña `a205b295-d243-44c1-b3a8-ea0183bd8733` bajo `tests/data/evaluation/artifacts/`. Son artefactos locales ignorados por Git, no una campaña cerrada de aceptación.

| Observación | Lectura operativa |
| --- | --- |
| 2/9 unidades afirmación × repetición correctas de extremo a extremo | El criterio del informe también falla una unidad si cualquier validador da error técnico o falla la extracción, aunque el consenso acierte. No equivale a una estimación de precisión poblacional. |
| España: consenso `TRUE` en 3/3; 2/3 unidades completas | Una repetición tuvo un HTTP 429. Se observaron recuperación y citas de `ine.es` en algunos registros, pero no hay anotación de dominio aceptable que acredite esa ruta. |
| Alemania: consenso `FALSE` en 1/3; 0/3 unidades completas | Dos repeticiones acabaron `UNKNOWN`; la repetición con consenso correcto tuvo categoría extraída distinta de la esperada. También hubo dos errores de proveedor y ausencia de contextos citables en registros. |
| Francia: consenso `FALSE` en 1/3; 0/3 unidades completas | Dos repeticiones acabaron `UNKNOWN` con fallos de recuperación. La repetición con consenso correcto tuvo dos errores de proveedor. |
| Cinco `HTTP 429` durante `LLM_REQUEST` | Limitación temporal del proveedor para el modelo Mistral usado por dos validadores. Medir fiabilidad y cuota por separado de la corrección factual; repetir sin diagnóstico no convierte el lote anterior en válido. |
| Extracción 24 PASS / 3 FAIL; recuperación 9 sin contexto citable y 13 parciales | Las tres fallas de extracción son registros de una misma afirmación/repetición. La recuperación parcial puede coexistir con evidencia suficiente; revisar URL, estado de descarga y contexto por caso. |
| Citas 15 PASS / 12 no evaluables; grounding 22 PASS / 5 no evaluables | La comprobación prueba identidad/elegibilidad del `context_id`, no que el texto respalde semánticamente la afirmación ni que sea independiente. |
| Routing y entrega de evidencia: 27/27 `NOT_EVALUATED` | El caso v1 no anota `acceptable_domains` ni fuentes de referencia, y las órdenes antiguas no registraron ambos hashes de frontera. No se puede afirmar que eligiera dominios correctos ni que se probara la integridad del traspaso. |

Las cuentas de `analysis.json` son **por validador**; `report.json` cuenta **afirmación × repetición** y sus causas pueden solaparse. El conjunto tiene solo tres afirmaciones sintéticas. Se usa para depurar el pipeline y el runner, no para concluir si Assermetry verifica noticias reales. Las métricas de recuperación léxica son aproximaciones y `--analyze` no juzga implicación semántica.

### Qué medir en la siguiente campaña

1. Versionar un dataset v2 revisado por personas con `acceptable_domains`, `reference_sources`, `reference_evidence`, hechos, veredicto y casos donde corresponda `UNKNOWN`. Guardar versión y hash antes de ejecutar. Como objetivos de planificación, añadir 10–20 afirmaciones revisadas por incremento hasta 50–100 para depuración y después un conjunto interno independiente de 200–300 para una señal de aceptación; el número por sí solo no acredita representatividad ni sustituye umbrales preacordados.
2. Registrar para cada afirmación la extracción, dominios elegidos, URLs y estados de descarga, contextos citables, hashes de Evidence Search y entrada del validador, citas reclamadas, auditoría de grounding, veredicto y consenso. Marcar explícitamente lo no observable.
3. Separar **fiabilidad técnica** (429, timeout, descargas, ausencia de validador), **calidad de recuperación** (fuente primaria y contexto) y **calidad de decisión** (veredicto, abstención y respaldo humano). Un PASS de grounding no satisface por sí solo las otras dos.
4. Comparar `full`, `gold-domains` y `gold-evidence` solo para la misma afirmación, repetición, configuración y plantilla. Los modos directos permiten contrafactuales; `--publish` mide el despliegue con reputaciones reales y no admite `--counterfactuals`. No atribuir a un modelo una diferencia producida por evidencia distinta.
5. Acordar antes de medir los umbrales de error, abstención, soporte, cobertura, latencia y coste. Añadir una comparación pareada con un LLM más búsqueda web, bajo el mismo corpus y criterios humanos. Un resultado técnico fallido cuenta como fallo, no se elimina del denominador.

Comandos de referencia, desde la raíz del repositorio, una vez revisados datos, configuración y cuota:

```bash
PYTHONPATH=tests python3 -m evaluation.pipeline --dataset RUTA_DATASET_V2 --validate-only
PYTHONPATH=tests python3 -m evaluation.pipeline --dataset RUTA_DATASET_V2 \
  --mode full --model openrouter:MODELO --counterfactuals --repetitions 3
PYTHONPATH=tests python3 -m evaluation.pipeline --dataset RUTA_DATASET_V2 \
  --mode full --publish --repetitions 3
PYTHONPATH=tests python3 -m evaluation.pipeline \
  --analyze tests/data/evaluation/artifacts/CAMPAIGN_ID
```

`--publish` crea órdenes y consume cuota. La campaña reproducible requiere servicios, credenciales, revisión efectiva del despliegue y proveedor disponibles; la ejecución offline de `--analyze` no. Véase la [guía de evaluación](tests/evaluation.md) para caché WARM/COLD, GOLD, autenticación, artefactos y límites de causalidad.

## Orden de ejecución incremental

Cada incremento dura aproximadamente **1–3 días** y limita los cambios de implementación a **dos incidencias**. Una incidencia grande puede ocupar varios incrementos. Las ventanas de acreditación pueden comprobar varias correcciones ya implementadas, pero sus resultados se registran por incidencia. El orden depende de que el incremento anterior deje una base reproducible; un P0 o P1 que invalide resultados desplaza esta secuencia.

| Incremento | Incidencias de implementación | Trabajo concreto | Evidencia para avanzar |
| --- | --- | --- | --- |
| A. Resumen y fechas | 014, 005 | Corregir la colisión `completedValidations`; aplicar un único contrato UTC/ISO y presentación ES/EN. No se mantiene compatibilidad con órdenes históricas borradas. | Órdenes actuales parciales, sin `assertion_results` todavía y con ERROR sin excepción; mismo instante mostrado coherentemente en eventos y orden, incluido cambio horario. |
| B. Estados y diagnóstico de regresión | 006, 016 | Hacer definitiva la tarjeta terminal y alinear API/GUI; completar dependencias de tests, fallo estricto ante HTTP/consola y ancho móvil, y captura en `finally`. | Matriz de estados `VALIDATED`, `VALIDATED_WITH_ERRORS`, timeout y sin evidencia; suite instalable desde entorno limpio; E2E falla si `scrollWidth > innerWidth` a 390 px. |
| C. Arranque seguro de validadores | 001, remate de 016 si queda | Implementado localmente: conservar la última caché válida ante respuesta vacía, malformada o caída de news-chain; commit atómico y fusión copy-on-write de eventos concurrentes sin perder actualizaciones. | Unitariamente acreditado; pendiente desplegar la misma revisión y ejecutar reinicio concurrente + eventos + news-chain degradado, con 3 afirmaciones × 3 validadores LIGHT sin refresco manual en Kind y Hetzner. |
| D. Documento primario | 021 | Recuperar PDF con página, fragmento, URL y `context_id` auditables; distinguir fallo de descarga/extracción de ausencia de evidencia. | El caso original del informe IEA recupera y cita el documento primario o termina `UNKNOWN`; tests y orden real conservan página y hash. |
| E. Independencia y corpus inicial | 021, 017 | Clasificar origen, copia y fuente derivada; impedir decisión documental fuerte solo con noticia/eco secundario. Anotar primer conjunto v2 revisado. | Mismo URL, mismo dominio, dominios distintos con el mismo cable, informe primario y evidencia insuficiente; `gold-evidence` separa error de validador de error de recuperación. |
| F. Errores y progreso | 008, 019 | Ejecutar matriz LIGHT/BLOCKCHAIN; corregir solo los fallos reproducidos. | Casos normal, lento, timeout, ERROR, duplicado, retry, llegada parcial, todos ERROR y UNKNOWN; `received + pending = total`, progreso ≤100 %, ERROR/timeout no votan. |
| G. Acreditación en Hetzner | Ninguna nueva por defecto | Desplegar una revisión fijada y validar en lotes: 007/013, 015/022, 011/012 y 018/023. Mantener una ficha de evidencia por incidencia. | Consenso y grounding; rutas/cache e índices; dos identidades y tokens negativos; enlaces seguros, CID/post/tx y validaciones BLOCKCHAIN. Cualquier fallo abre o reabre la incidencia correspondiente. |
| H. Calidad y móvil | 017, 020 | Ampliar el corpus revisado y ejecutar comparaciones repetidas; corregir overflow e idioma ES/EN, teclado y foco. | Umbrales preacordados en un conjunto no usado para ajustar modelos; resultados por estrato y línea base simple; ancho ≤390 px sin desbordamiento en LIGHT/BLOCKCHAIN. |
| I. Cierre | Ninguna | Dos ciclos completos consecutivos y tres demos, una desde otra red/equipo; revisar decisiones 003/004 y todos los P1. | Evidencia de [criterios de salida](version.md#exit-criterion) firmada/revisable, sin P0 ni P1 objetivo 13 abiertos salvo diferimiento formal. |

El incremento H se repite en tandas de 1–3 días hasta cubrir los estratos y el volumen acordados; no se promete construir ni revisar todo el corpus en una sola tanda. Las ventanas G acreditan trabajo ya implementado por pares de incidencias sobre una misma revisión desplegada.

### Detalle de las dependencias críticas

- **014 → 005 → 006:** los resúmenes legacy, fechas y estado terminal deben ser coherentes antes de usar la GUI como evidencia de otras pruebas. El cierre de 007 no sustituye estos tres arreglos.
- **016 → 001/021/017:** la suite limpia ya cubre la seguridad local de caché de 001; su cierre todavía exige la prueba concurrente 3×3 desplegada. Una campaña con errores de preparación o HTTP 429 conserva los errores en el resultado.
- **021 → 017:** un corpus con fuentes oficiales no prueba independencia si no se recupera el documento primario ni se detectan copias. Primero fijar reglas de elegibilidad; después fijar umbrales y medir.
- **015/022 y 013/023:** código local implementado; priorizar despliegue del mismo commit y evidencia de integración. Cambiar diseño solo cuando la validación muestre un defecto concreto.
- **003/004:** [next_releases.md](next_releases.md) propone resolver CA de K3s y clave SSH en v0.0.16. Antes de cerrar 13 se debe registrar responsable, riesgo, alcance de demo privada, mitigación y destino; si no hay decisión explícita, siguen bloqueando el cierre.

## Protocolo de cada iteración

1. **Preparar una ficha breve:** hasta dos incidencias, caso original, hipótesis, entorno, commit, configuraciones y criterio de fallo/cierre. Guardar entrada, hash del dataset y límites de cuota sin guardar secretos.
2. **Observar antes de cambiar:** reproducir el caso y conservar orden, trazas y artefactos. Clasificar etapa; si falta anotación o hash, escribir `NOT_EVALUATED` y cubrir esa observabilidad en el incremento.
3. **Cambiar una causa acotada:** actualizar contrato, política y migración de datos si corresponde. Mantener un caso de regresión por cada defecto corregido.
4. **Validar por capas:** pruebas enfocadas, suite afectada y, cuando proceda, LIGHT y BLOCKCHAIN en entorno local. En Hetzner comprobar el mismo commit, configuración efectiva e identidad de quien ejecuta.
5. **Analizar y decidir:** usar el informe y `--analyze`; distinguir fallos técnicos de veredictos incorrectos y comprobar fuentes/citas. Ante nuevo P0/P1, detener la promoción y reordenar. No repetir hasta obtener un PASS aislado.
6. **Actualizar solo lo necesario:** estado y evidencia en `issues.md`, resumen acumulado y contador de ciclos en `version.md`, próximo incremento en este fichero. Conservar artefactos fechados fuera de Git con una ubicación reproducible.

## Tablero de cierre (estado documentado al 2026-09-29)

| Puerta | Estado acreditado | Evidencia que falta |
| --- | --- | --- |
| P0/P1 objetivo 13 | Hay incidencias abiertas, en curso y pendientes de validación | Cerrar cada ficha con caso original y evidencia o registrar diferimiento formal cuando proceda |
| Regresión reproducible | Última base amplia registrada: 199 PASS del 2026-09-08; no hay suite completa verde reciente | Entorno limpio con dependencias, API/frontend/contratos y E2E, sin HTTP/console falsos positivos |
| Calidad factual e independencia | Benchmark y diagnóstico existen; corpus actual sintético, PDF/independencia pendientes | Corpus humano revisado, fuentes primarias, umbrales previos, contraste con línea base simple y resultados estratificados |
| Ciclos completos consecutivos | 0/2 acreditados con la matriz actual | Dos ciclos completos verdes sin P1 nuevo ni reapertura por el mismo caso |
| Demos consecutivas | 0/3 acreditadas con login, LIGHT y BLOCKCHAIN juntos | Tres demos con preparación/cierre y artefactos; una desde otra red/equipo |
| Riesgo CI 003/004 | Corrección propuesta para v0.0.16, diferimiento de 13 sin formalizar | Responsable, impacto, mitigación, alcance de demo privada y decisión registrada |

Los contadores se refieren a evidencia **acreditada**, no al número de ejecuciones parciales. Se actualizan en [version.md](version.md) al concluir cada ciclo; las causas y estados permanecen en [issues.md](issues.md).

## Puerta de cierre de v0.0.13

La versión se cierra cuando se cumplen simultáneamente los [criterios de version.md](version.md#exit-criterion): sin P0 ni P1 objetivo 13 abiertos salvo diferimiento formal; independencia documental y abstención verificadas; suite completa reproducible; corpus representativo revisado con umbrales definidos antes de medir; dos ciclos completos consecutivos sin nuevo P1; tres demos consecutivas con login, LIGHT y BLOCKCHAIN, una desde otra red/equipo; GUI y API coherentes en estados, fechas, errores y evidencias; móvil sin overflow a 390 px; y artefactos duraderos disponibles para revisión. Un fallo nuevo que invalide una decisión o una prueba reinicia el contador correspondiente.
