# Pruebas iterativas de v0.0.13

**Revisión 2026-09-05. Resultado global: NO APTO para cierre.**
El flujo básico funciona; quedan dos fallos Python y defectos que el smoke no
comprueba. Plan de versión en [version.md](version.md); criterios de corrección
en [issues.md](issues.md).

## Sesión de regresión — 4 y 5 de septiembre

Código local: `bcf6c3efa395e797b534d3383405869c1e9ab45d`, árbol con cambios
documentales. Frontend servido idéntico al local: SHA-256
`42e61de7770f91c871e04da1949f8e2bcbcfbd0257970531cba57e739af35a8b`.
No se verificó el commit del backend desplegado. Chrome 138, Node 22.3.0,
Python 3.12; entorno Python temporal con dependencias de los servicios.

| Prueba ejecutada | Resultado | Interpretación |
| --- | --- | --- |
| Validación del paquete | 2 casos válidos | JSON/casos, sin aplicación |
| Sintaxis JS de app y runner individual | Correcta | No garantiza comportamiento |
| Python local, sin integraciones externas | **75 PASS, 2 FAIL** | Scoring, contratos, logs, seguridad de cuerpos y búsqueda |
| LIGHT, 04/09 19:13 UTC | **23/23 PASS**, 126,32 s de escenario | VALIDATED; 3 aserciones, 9 validaciones, 0 pendientes |
| BLOCKCHAIN, intento del 04/09 | **FAIL; sesión interrumpida** | Terminó el 05/09 redirigida a login; duración de unas 20 h no utilizable como latencia |
| BLOCKCHAIN repetido, 05/09 15:29 UTC | **26/26 PASS**, 123,77 s de escenario | VALIDATED; 2 aserciones, 6 validaciones, CID/post/transacción presentes |
| Inspección visual y DOM | **FAIL móvil/contadores/fechas** | Documento=847 px en viewport=390; 0/4 con 6 pendientes; actividad con 2 h de diferencia |
| Sondas locales de funciones reales | Defectos reproducidos | Empates, TRUE sin fuentes, consulta sin ámbito, resumen sin ponderación y enlaces no HTTP(S) |

Los tiempos incluyen login, seguimiento y capturas; no son latencias del LLM.
La interrupción no demuestra fallo del motor Blockchain. Los casos pasan por
separado; **no hubo una ejecución conjunta completa en verde**.

**Fallos Python:**

- `test_catalunya_scoring_order`: falta `idescat.cat` en el perfil; selección
  local de fuentes sin pertinencia regional acreditada (015).
- `test_search_evidence_logs_final_search_calls`: espera stdout con `capsys`;
  el evento se emite por logging (016).

La primera ejecución Python sin dependencias dio 12 PASS, 2 FAIL y 8 errores
de importación. Se preparó un venv temporal y se repitió: el resultado válido
para evaluar código es **75/2**, no los errores de preparación.

## Corrección posterior de ISSUE-011

`api/tests/test_validator_validation_isolation.py`: **15 PASS**. Pruebas HTTP
Gateway → News Handler con autenticación sustituida por claims sintéticos y
colecciones simuladas: dos propietarios, rol admin, identidad ausente,
suplantación por query, textos/enlaces y estadísticas sin datos ajenos.
No comprueban JWT real, MongoDB real ni el despliegue. Pendiente desplegar ambos
servicios y repetir con dos identidades; 012 conserva el trabajo de organizaciones.

Regresión local tras el cambio: **90 PASS, 2 FAIL**; permanecen únicamente los
dos fallos anteriores (015 y 016). Evidencia temporal: `issue011.xml` y
`issue011.log` en el directorio de artefactos indicado abajo.

## Límites y evidencia

- Una cuenta de pruebas proporcionada por el operador para ambos casos. Los
  alias org-alpha/org-beta del runner son metadatos del JSON, **no dos
  identidades efectivas**. Sin prueba de aislamiento, admin o cliente API.
- Sin setup/cleanup ni captura de recursos: `managedState=false`. 13.1 conserva
  su cierre documental; esta sesión no acredita su ejecución operativa.
- Tres órdenes creadas: LIGHT, BLOCKCHAIN interrumpido y repetición. Sus IDs
  están en `createdResources`; no se limpiaron ni revirtieron Blockchain/IPFS.
- No se ejecutaron las seis suites de integración antiguas: necesitan servicios
  internos y/o credenciales API específicas; algunas modifican cuotas o
  registros de validadores. Se ejecutó el recorrido público autorizado.
- Proveedor/modelo/timeout efectivos sin registrar; pendiente línea base de
  recursos y calidad factual. No se induce un ataque ni se leen órdenes ajenas.

Artefactos locales **temporales, pendientes de archivo persistente**:
`/tmp/assermetry-review-20260904/`.

| Archivo relativo | Evidencia |
| --- | --- |
| `unit-ready.xml`, `unit-ready.log` | 77 tests y dos fallos |
| `live/summary.json` | Ejecución original agregada FAIL; no sobrescrita |
| `live/synthetic-light-01/report.json` y PNG | LIGHT y desbordamiento móvil |
| `live/synthetic-blockchain-01/report.json` | Interrupción, 400 de refresh y diagnóstico incompleto |
| `blockchain-repeat/report.json` y PNG | Repetición Blockchain correcta |
| `live-inspection.json` | Contadores y fechas durante Blockchain |
| `probe-backend.py`, `probe-backend.json` | Empates, evidencia vacía y consulta simulada sin ámbito |
| `probe-ui.js`, `probe-ui.json` | Parsers, TypeError del resumen y esquema de enlace |

## Repetir las pruebas

Runner y configuración: [README de pruebas](../web_classic/test/README.md).
Usar identidades separadas y hooks para acreditar estado gestionado. No poner
contraseñas en documentación ni informes. Los hooks no borran por CID.

La suite local ejecutada, con dependencias instaladas en el entorno activo:

```bash
PYTHONPATH=api python -m pytest api/tests -q \
  --ignore=api/tests/test_extraer_integration.py \
  --ignore=api/tests/test_ipfs_integration.py \
  --ignore=api/tests/test_news-chain_integration.py \
  --ignore=api/tests/test_news-handler.py \
  --ignore=api/tests/test_quotas.py \
  --ignore=api/tests/test_validator_api.py
```

## Cobertura y siguiente ciclo

Estados por caso: **Pendiente / Correcto / Fallido / Bloqueado**, vinculados a
sesión, commit y entorno. PASS funcional no implica calidad factual ni cobertura
completa de un área.

| Área | Estado actual / trabajo pendiente |
| --- | --- |
| Login y órdenes LIGHT/BLOCKCHAIN | Smoke correcto; refresh/logout/expiración y recuperación pendientes |
| Fechas, estado, consenso y contadores | Fallido: 005–007, 014, 019 |
| Errores/timeout | Unitarios correctos; fallo inducido y reintento sin duplicados pendientes (008) |
| Evidencia y calidad factual | Fallido/carencia: 013, 015, 017; revisión e informe en 14 |
| JWT, roles y dos organizaciones | 011 corregida y probada localmente; despliegue pendiente. 012 abierta |
| Cuotas, filtros, búsqueda, paginación, contratos y HTTP negativos | Pendiente más allá de unitarios existentes |
| ES/EN, navegadores, móvil, teclado y foco | Móvil y textos fallidos (020); Edge/Firefox/accesibilidad pendientes |
| Caché, despliegue, recursos y demos | Concurrencia 001, línea base y tres demos pendientes |

Seguir el orden de [version.md](version.md): seguridad → evidencia/consenso →
GUI → robustez/regresión → demos. Máximo dos correcciones en curso. Cada sesión
anota **objetivo, commit/entorno, casos, resultado, incidencias, evidencia y
siguiente acción**. Cerrar solo tras aceptación y regresión afectada; ejecutar
suite completa antes del cierre. No marcar un fallo como correcto por cambiar
la expectativa del test sin revisar el contrato.
