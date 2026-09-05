# v0.0.13 — Estabilización y demo repetible

**En curso. Revisión: 2026-09-05.** LIGHT y BLOCKCHAIN completan el recorrido
básico, pero la regresión Python tiene dos fallos y quedan defectos de
seguridad, evidencia y presentación. **No se acredita aún una web fiable de
verificación factual.** Resultados en [testing-v0.0.13.md](testing-v0.0.13.md);
trabajo pendiente en [issues.md](issues.md).

Versiones publicadas: [releases.md](releases.md). Evolución:
[next_releases.md](next_releases.md).

## Objetivo y límites

Verificar afirmaciones de noticias y de contenido generado mediante evidencia
identificable, incertidumbre explícita y revisión humana. La coincidencia de
LLMs y el registro Blockchain no prueban por sí solos la veracidad.

Esta versión estabiliza la demo privada. Se mantiene el gate temporal de mTLS
más namespaces permitidos y el mTLS administrativo permanente. Registrar lock
antes y después de cada ventana; sin accesos persistentes de clientes ni
presentación como producción/alta disponibilidad. Apertura y retirada del mTLS
general pertenecen a v0.0.14. Sin X/Threads, reputación nueva, LLM dedicado ni
Cloudflare Tunnel durante esta estabilización.

### Fase 13.1 - Preparación reproducible

**OK — cierre documental el 2026-09-04 por indicación del responsable.**
Se mantiene ese cierre; no equivale a una validación operativa nueva.

Alcance dado por implementado: identidades de administrador, usuario y cliente
API para dos organizaciones; casos LIGHT/BLOCKCHAIN; hooks idempotentes de
preparación/limpieza; manifiestos sin secretos; línea base; `HTTP_TIMEOUT=60`
por intento configurable por `PUT /admin/config`; logs JSON de una línea en
admin, evidence-search, gateway, generate-asertions, ipfs, news-chain,
news-handler y validate-asertions, con Uvicorn y tracebacks escapados. El
generador registra metadatos, sin prompts ni respuestas completas en INFO.

**Límite de esta revisión:** se usó una única cuenta facilitada por el operador,
sin hooks ni captura Kubernetes. Por tanto, no acredita aislamiento ni estado
reproducible. El contrato operativo sigue en
[web_classic/test](../web_classic/test/README.md); Blockchain/IPFS no se revierten.

### Fase 13.2 - Regresión de GUI

**En curso.** Login y recorridos LIGHT/BLOCKCHAIN pasan el smoke. Hay fallos
confirmados en fechas, estado final, resumen, contadores y móvil.

Cobertura de cierre:

- Login, refresh, logout, expiración, navegación y roles.
- Crear, consultar y seguir órdenes; aserciones, validaciones, evidencias,
  validadores y enlaces; LIGHT y BLOCKCHAIN.
- Filtros, búsqueda, paginación, cuotas y límites; vacío, carga, error, timeout
  y reintento; consola y mensajes sin datos internos.
- ES/EN, Chrome/Edge/Firefox, escritorio y móvil; teclado y foco.

#### Resultado verificado - publicación bajo `/gui/`

Hito previo conservado: `/gui/`, `/backend` y `/auth` separados, sin catch-all;
OIDC y post-logout alineados; redirects exactos Cloudflare, gate y origen
validados en Kind y Hetzner desde el mismo commit. LIGHT predeterminado y
BLOCKCHAIN opcional. Estas verificaciones históricas no sustituyen la cobertura
pendiente ni resuelven los hallazgos actuales.

### Fase 13.3 - Regresión de API y aislamiento

**Pendiente de cierre; bloqueantes confirmados en código (011–012).**

- Validar firma, emisor, audiencia `TrustNewsApi` y presentadores `azp/client_id`;
  tokens válidos, ausentes, expirados y manipulados.
- Organización derivada en servidor, roles de usuario/admin/service account y
  separación de administrador de organización/global; sin suplantación desde UI.
- Aislamiento en órdenes, detalles, aserciones, validaciones, evidencias,
  búsquedas, exportaciones y enlaces indirectos; respuestas y logs sin datos ajenos.
- Contratos de órdenes, cuotas, recomendaciones, validadores, categorías y modos;
  campos, parámetros, tamaños y HTTP 400/401/403/404/409/413/429/5xx.
- Timeouts, reintentos, compatibilidad Gateway/servicios y pruebas repetibles.

### Fase 13.4 - Corrección y ensayos de demo

**Corrección continua durante 13.2/13.3; ensayos finales pendientes.**
Iteraciones de uno a tres días, máximo dos incidencias en corrección:
probar → registrar → corregir → validar → resolver/reabrir.

| Orden | Resultado buscado | Incidencias |
| --- | --- | --- |
| 1 | Identidad, aislamiento y enlaces seguros | 011, 012, 018; decisión sobre 003–004 |
| 2 | Evidencia y fuentes pertinentes; consenso sin arbitrariedad | 013, 015, 007, 017 |
| 3 | UI estable y estado comprensible | 014, 005, 006, 008, 019, 020 |
| 4 | Despliegue LIGHT estable y regresión que detecta fallos | 001, 016 |
| 5 | Regresión completa y demos | Matriz de pruebas y criterios siguientes |

Las pruebas exploratorias independientes continúan mientras se corrige.
Cada arreglo supera el caso original y la regresión afectada; la suite completa
se ejecuta antes de cerrar la versión. Un fallo que impida probar tiene prioridad.

### Criterio de salida

- P1 de objetivo 13 resueltos y validados; cero P0. Sin bypass de aislamiento,
  elevación de privilegios, pérdida de datos ni resultados presentados sin soporte.
- ISSUE-001 validada en concurrencia y despliegue conjunto en Kind y Hetzner.
- ISSUE-003/004 corregidas o aplazadas mediante decisión explícita con motivo,
  impacto, responsable y versión; su objetivo 16 no supone aceptación automática.
- Suite de contrato sin fallos; GUI/API y evaluación factual mínima superadas.
  Sin empates arbitrarios, errores contados como votos o fechas contradictorias.
- P2 aceptados y alcance afectado documentados; no acreditar móvil mientras falle.
- Tres demos consecutivas con login/LIGHT/BLOCKCHAIN, una desde otra red/equipo
  con certificado temporal; inicialización, ejecución, limpieza y cierre registrados.
- Guion, evidencia, línea base comparable y limitaciones conocidas disponibles.

## Alcance posterior y diagnóstico revisado

El diagnóstico del 2026-09-01 se mantiene con ajustes: 008 ya excluye errores;
009 ya permite edición opcional; 010 ya muestra evidencia detallada. No se dan
por resueltas sin sus criterios de aceptación.

**v0.0.14:** revisión humana guiada (009), evidencia principal e informe
reutilizable (010). **v0.0.15:** piloto y seguimiento de calidad. La validez de
las citas y la abstención ante falta de evidencia (013/017) son necesarias ya
en 13; no se aplazan con la mejora visual del informe.
