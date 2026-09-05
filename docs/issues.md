# Incidencias de Assermetry

Revisión: **2026-09-05**. Resumen del inventario histórico y de la regresión
[registrada aquí](testing-v0.0.13.md). La revisión inicial no modificó código.
Actualización posterior: 011 implementada, pendiente de validar en despliegue.
Evidencia de código local no implica explotación demostrada en el despliegue.

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
| 007 | P1 | Abierto; empates reproducidos | 13 |
| 008 | P1 | Pendiente de validación; exclusión de errores ya implementada | 13 |
| 009 | P1 | Abierto; edición opcional ya existe | 14 |
| 010 | P1 | Abierto; evidencia detallada ya existe | 14 |
| 011 | P1 | Pendiente de validación en despliegue; 15 pruebas locales correctas | 13 |
| 012–014 | P1 | Abiertos; confirmados en código/sondas locales | 13 |
| 015 | P1 | Abierto; fallo reproducido con perfil versionado | 13 |
| 016 | P1 | Abierto; falsos positivos y diagnóstico incompleto | 13 |
| 017 | P1 | Abierto; carencia de evaluación factual | 13, ampliar en 14 |
| 018 | P1 | Abierto; esquema de enlace sin validar | 13 |
| 019 | P1 | Abierto; contadores contradictorios en GUI | 13 |
| 020 | P2 | Abierto; desbordamiento y mezcla de idiomas | 13 |

Los P1 de objetivo 13 bloquean su cierre. 009–010 bloquean la experiencia de
revisión/evidencia de 14. 020 debe corregirse antes de acreditar móvil; cualquier
aceptación temporal debe limitar explícitamente el alcance de demo.

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

- **Reproducido:** `calculate_assertion_result` usa `max`: TRUE/FALSE empatados
  produce TRUE; FALSE/UNKNOWN produce FALSE. Depende del orden de las claves.
- **GUI:** el resumen Blockchain muestra «Desmentida» con una afirmación
  desmentida y otra no concluyente; debe explicitar el alcance de la conclusión.
- **Cierre:** empate explícito `NO_CONSENSUS`, sin verdad asignada arbitrariamente;
  explicar pesos, abstenciones y distribución. Un peso no es probabilidad de verdad.

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

- **Causa:** Gateway omitía identidad en `/validators/cache/{hash}/validations`;
  News Handler asumía `admin=True` y podía devolver órdenes ajenas.
- **Implementado:** Gateway deriva el propietario del token y codifica los
  filtros; News Handler exige identidad y filtra validaciones, textos, enlaces
  y estadísticas. El parámetro `admin` no amplía acceso, tampoco `trust-admin`.
- **Validación local:** 15 pruebas HTTP Gateway → News Handler con dos
  propietarios y colecciones simuladas; incluyen suplantación por parámetros,
  identidad ausente, ámbito vacío y órdenes huérfanas.
- **Pendiente:** desplegar Gateway y News Handler y repetir con dos identidades
  reales. Este endpoint interno confía en la identidad transmitida por Gateway;
  no debe exponerse directamente. La asociación a organizaciones y el modelo de
  roles globales siguen en 012; no se acredita aislamiento de todas las rutas.

### ISSUE-012 - JWT sin validación de audiencia ni cliente presentador

- **Confirmado:** `get_current_user` valida firma/emisor, pero desactiva `aud` y
  no exige una lista de `azp/client_id`. La identidad computada no demuestra
  asociación a organización. Fuente: `api/gateway/main.py`.
- **Cierre:** audiencia `TrustNewsApi`, presentadores permitidos y asociación
  server-side; pruebas negativas de token válido para otra API/cliente y roles.

### ISSUE-013 - Veredictos sin evidencia comprobada y atribución automática

- **Reproducido:** `parse_validator_api_response` acepta TRUE sin fuentes. En
  `validate_payload_v2`, la búsqueda completa se copia a
  `evidence_used` si el modelo no selecciona evidencia. Un prompt que exige
  citas no impone el contrato en el servidor.
- **Cierre:** para búsqueda/RAG exigir URL, fragmento y pertenencia a evidencia
  recuperada; distinguir recuperada de utilizada; rechazar atribuciones inventadas.
  Sin soporte, abstenerse o indicar resultado sin evidencia; el voto de memoria
  no debe presentarse como verificación documental. Probar citas falsas y vacías.

### ISSUE-014 - Resumen rompe al faltar resultados ponderados

- **Reproducido:** `buildVerificationSummary` declara el número
  `completedValidations` y después intenta llamarlo como función; una orden con
  validaciones sin resultado ponderado lanza `TypeError`.
- **Cierre:** corregir la colisión y renderizar órdenes antiguas, parciales y con
  solo errores sin excepción. Fuente: `web_classic/app/js/app.js`.

### ISSUE-015 - Selección local de fuentes sin pertinencia regional acreditada

- **Reproducido:** `test_catalunya_scoring_order` falla: el perfil predeterminado
  no contiene `idescat.cat`; devuelve primero `workandincome.govt.nz`, `va.gov`
  y `uwv.nl` para población de Catalunya. No acredita el comportamiento del
  perfil que esté cargado en MongoDB del despliegue.
- **Cierre:** revisar catálogo, ponderación geográfica y fallback; corpus de
  fuentes pertinentes por región/tema. Alinear la fixture con el contrato
  acordado sin limitarse a eliminar la expectativa que falla.

### ISSUE-016 - Regresión con falsos positivos y diagnóstico incompleto

- **Confirmado:** móvil solo comprueba viewport, aunque documento=847 y
  viewport=390; tests Blockchain antiguos aceptan HTTP 500. Una salida temprana
  evita agregar errores de red/consola: la ejecución interrumpida registra 400
  de autenticación y dos errores de consola, pero el resumen cuenta cero.
- **Además:** el test de logs usa `capsys` para eventos de logging; falla aunque
  `search_request` sí se registra. `api/tests/requirements.txt` no reúne las
  dependencias de la suite y la fixture no exige credenciales antes de conectar.
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

- **Reproducido en renderizado aislado:** `renderEvidenceLinks` conserva
  `href="javascript:void(0)"`; `safeText` escapa HTML, pero no valida protocolos.
  El modelo acepta fuentes como diccionarios libres. No se ha ejecutado un
  payload en el navegador ni probado explotación con la CSP desplegada.
- **Cierre:** aceptar solo HTTP(S) en servidor y cliente; texto inerte para URLs
  inválidas; pruebas con esquemas peligrosos y enlaces malformados.

### ISSUE-019 - Total de validaciones contradictorio durante el proceso

- **Observado en Blockchain:** dos afirmaciones, seis pendientes y tarjeta
  «0/4». `buildVerificationSummary` prioriza solicitudes parciales sobre otros
  recuentos. Puede producir porcentajes o mensajes prematuros.
- **Cierre:** una fuente autoritativa para esperadas/recibidas/error/pendientes;
  siempre total=recibidas+pendientes, sin superar 100 %. Probar llegada parcial,
  duplicados y reintentos en ambos modos.

### ISSUE-020 - Desbordamiento móvil y lenguaje de interfaz inconsistente

- **Reproducido:** documento de 847 px con viewport de 390 px en LIGHT y
  BLOCKCHAIN; navegación ocupa gran parte de la pantalla y el aviso sale del
  ancho visible. En castellano aparecen «valid», «errors» y «Publicar Noticia».
- **Cierre:** sin scroll horizontal de página a 390 px, navegación compacta,
  avisos contenidos y resultado accesible; ES/EN completos y acciones coherentes.
  Validar teclado y foco, no solo tamaño del viewport.
