# v0.0.13 — Estabilización funcional iterativa

**En curso. Revisión: 2026-09-11.** LIGHT y BLOCKCHAIN completan el recorrido
básico y la regresión local está en verde, pero siguen abiertos defectos de
seguridad, calidad factual, presentación y operación. **La versión no acredita
aún una verificación factual estable.** El inventario y los criterios de cada
hallazgo están en [issues.md](issues.md).

Versiones publicadas: [releases.md](releases.md). Evolución posterior:
[next_releases.md](next_releases.md).

## Objetivo y límites

Esta versión es un ciclo acumulativo de prueba, descubrimiento, implementación
y nueva prueba. Terminará cuando el producto sea funcionalmente estable según
los criterios de salida, no al completar una fecha o una lista inicial cerrada.

El objetivo es verificar afirmaciones de noticias y contenido generado mediante
evidencia identificable, independencia suficiente, incertidumbre explícita y
revisión humana. La coincidencia de LLMs y el registro Blockchain no prueban por
sí solos la veracidad.

Se mantiene el gate temporal de mTLS más namespaces permitidos y el mTLS
administrativo permanente. Sin accesos persistentes de clientes ni presentación
como producción o alta disponibilidad. La apertura y retirada controlada del
mTLS general pertenecen a v0.0.14. X/Threads, reputación nueva, LLM dedicado y
Cloudflare Tunnel quedan fuera de este ciclo.

## Forma de trabajo de la versión

Cada iteración dura de uno a tres días y limita a dos las incidencias en
implementación. El ciclo es:

1. **Observar:** ejecutar casos reales, regresión y sondas; registrar entorno,
   revisión, entrada y resultado.
2. **Clasificar:** crear o reabrir una incidencia con causa comprobada, impacto,
   criterio de cierre y relación con las existentes.
3. **Priorizar:** primero P0; después P1 que afecten seguridad, corrección factual
   o que bloqueen pruebas; luego robustez, presentación y deuda P2/P3.
4. **Implementar:** corregir una causa acotada y versionar cualquier política o
   contrato cuyo cambio pueda alterar resultados almacenados.
5. **Validar:** superar el caso original, las pruebas focalizadas y la regresión
   afectada; después comprobar el despliegue y ambos modos cuando corresponda.
6. **Acumular:** conservar el caso como regresión y actualizar la línea base. Un
   resultado nuevo puede reabrir, dividir o repriorizar trabajo anterior.

Una incidencia no cambia de prioridad solo por antigüedad. En cada inicio de
iteración se revisan gravedad, alcance, confianza del diagnóstico, dependencias
y capacidad de bloquear aprendizaje posterior. Los hallazgos que invaliden un
veredicto o una prueba previa entran delante del trabajo visual.

`version.md` conserva el estado de la versión, las iteraciones y la evidencia
resumida. `issues.md` conserva causas y criterios de cierre. Los informes de cada
ejecución deben ser artefactos fechados, no nuevos documentos narrativos que
dupliquen ambos archivos.

## Iteraciones acumulativas

### Iteración 13.1 — Preparación reproducible

**Cierre documental del 2026-09-04; validación operativa nueva pendiente.**

Se consideran implementados identidades y casos para LIGHT/BLOCKCHAIN, hooks
idempotentes, manifiestos sin secretos, timeout configurable y logs JSON. La
sesión disponible usó una única cuenta y no ejecutó preparación, limpieza ni
captura Kubernetes; por ello no acredita aislamiento ni estado reproducible.
El contrato operativo permanece en
[web_classic/test](../web_classic/test/README.md).

### Iteración 13.2 — GUI, estados y consenso

**En curso.** Login y los recorridos básicos pasan. ISSUE-007 tiene solución y
validación local; quedan fechas, estado final, resumen, contadores, errores
inducidos, móvil e idiomas: 005, 006, 008, 014, 019 y 020.

Debe cubrir login, sesión, navegación, creación y seguimiento de órdenes,
evidencias y enlaces, filtros, paginación, cuotas, estados vacío/error/timeout,
ES/EN, escritorio/móvil, teclado y foco. LIGHT y BLOCKCHAIN deben presentar la
misma semántica de decisión.

### Iteración 13.3 — API, identidad y aislamiento

**Pendiente de cierre.** 011, 012 y 018 están solucionadas y desplegadas en
Hetzner, pero falta completar la validación con identidades reales y conservar
evidencia de ejecución. Se deben cubrir tokens válidos y negativos, organización
derivada en servidor, roles y aislamiento de órdenes, validaciones, evidencias,
búsquedas, exportaciones y enlaces indirectos.

ISSUE-001 requiere todavía concurrencia y arranque conjunto. ISSUE-003/004 deben
corregirse o aplazarse mediante una decisión explícita antes de cerrar la
versión.

### Iteración 13.4 — Calidad de evidencia y estabilidad del routing

**Nueva; prioritaria antes de los ensayos finales.** Los casos reales han
mostrado límites que no cubren las correcciones 013 y 015:

- Una cita puede pertenecer al corpus y aun proceder de la misma noticia que se
  intenta verificar; eso prueba coincidencia textual, no corroboración
  independiente (ISSUE-021).
- `EXT_ONLY_OFFICIAL` expresa una intención en la búsqueda, pero no filtra de
  forma determinista los resultados recibidos (ISSUE-021).
- El informe primario puede localizarse y perder frente a un medio porque el
  recuperador no extrae PDF y el paso `source-router → evidence-search` pierde
  metadatos de autoridad y tipo de fuente (ISSUE-021).
- La subcategoría libre y el `claim_type` inestable fragmentaban rutas
  equivalentes; se sustituyen por taxonomía cerrada y una firma `route-v2`
  (ISSUE-022).

La iteración debe propagar la URL de origen, clasificar procedencia e
independencia, recuperar documentos primarios en PDF, aplicar la política de
fuentes después de la búsqueda y conservar los metadatos del router. También
introduce temas y tipos de evidencia canónicos y claves de ruta versionadas. Al
ser una ruptura deliberada, el realineamiento elimina la caché histórica
incompatible y conserva las nuevas colecciones en ejecuciones posteriores.

ISSUE-017 aporta el corpus y las métricas para comprobar el resultado. La orden
`355f6090-cec0-4ed3-a29a-46763fe66cc6` queda como caso de regresión: la noticia
de origen no puede ser la única evidencia decisiva; debe citarse el informe
primario o emitirse `UNKNOWN`.

### Iteración 13.5 — Convergencia y ensayos de demo

**Pendiente.** Se ejecutará cuando las iteraciones anteriores no tengan P1
abiertos sin decisión explícita. Cada arreglo debe superar su caso original; la
suite completa y los recorridos desplegados se repiten al final de cada ciclo.

Orden inicial, revisable al aparecer evidencia nueva:

| Orden | Resultado buscado | Incidencias principales |
| --- | --- | --- |
| 1 | Identidad y aislamiento seguros | 001, 003, 004, 011, 012, 018 |
| 2 | Evidencia independiente y routing estable | 013, 015, 017, 021, 022 |
| 3 | Estado y resultado comprensibles | 005, 006, 007, 008, 014, 019 |
| 4 | GUI utilizable y regresión fiable | 016, 020 |
| 5 | Regresión completa y demos consecutivas | Todos los bloqueantes de 13 |

## Línea base acumulada

La última línea base local registrada el 2026-09-08 fue **199 pruebas Python
correctas**, sin las seis integraciones externas históricas. Las pruebas
focalizadas de routing fueron correctas y la sintaxis/configuración asociada se
validó. Esto acredita comportamiento local del código, no calidad factual ni el
despliegue.

Los smokes del 4–5 de septiembre completaron LIGHT (23/23) y una repetición
BLOCKCHAIN (26/26). No hubo una ejecución conjunta completa en verde. La
inspección descubrió desbordamiento móvil, contadores y fechas incoherentes. Las
correcciones posteriores de aislamiento, JWT y enlaces están desplegadas; las
de consenso, grounding y Source Router requieren completar sus comprobaciones
de extremo a extremo según `issues.md`.

Limitaciones de la evidencia acumulada:

- una sola identidad efectiva en el smoke inicial;
- integraciones externas y proveedor/modelo efectivos sin línea base completa;
- artefactos originales temporales, no archivo persistente;
- ningún PASS anterior acredita por sí solo corrección factual;
- los casos reales nuevos se incorporan como regresiones versionadas.

## Criterio de salida

- Cero P0 y cero P1 del objetivo 13 abiertos, salvo aplazamiento explícito con
  motivo, impacto, responsable, mitigación y versión de destino.
- Sin bypass de aislamiento, elevación de privilegios, pérdida de datos,
  autoconfirmación documental ni resultados decisivos sin soporte elegible.
- Suite de contrato y regresión completa sin fallos; GUI/API y corpus factual
  dentro de umbrales acordados antes de ejecutar la evaluación.
- Dos ciclos completos consecutivos sin nuevos P1 y sin reabrir correcciones por
  el mismo caso; cualquier hallazgo nuevo reinicia este contador.
- Tres demos consecutivas con login, LIGHT y BLOCKCHAIN; al menos una desde otra
  red/equipo con certificado temporal, preparación y cierre registrados.
- Contadores, fechas, errores, incertidumbre y evidencia coherentes en API y GUI;
  móvil solo se acredita cuando no exista desbordamiento a 390 px.
- Línea base, artefactos persistentes, limitaciones conocidas y decisiones de
  aplazamiento disponibles para revisión.

## Alcance posterior

v0.0.14 mantiene la revisión humana guiada (009), el informe reutilizable (010)
y la retirada controlada del gate general. v0.0.15 mantiene piloto y seguimiento
de calidad. La independencia de fuentes, la abstención y la estabilidad del
routing son requisitos de v0.0.13 y no se aplazan por esas mejoras posteriores.
