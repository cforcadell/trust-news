# v0.0.13b — Cierre de seguridad previo a la beta

**Estado: planificada; auditoría y plan preparados el 03-11-2026. Remediaciones sin ejecutar ni desplegar.** Versión intermedia entre v0.0.13 y v0.0.14. La v0.0.13 consta como desplegada en Hetzner con aceptación pendiente; esta versión no declara cerrada esa aceptación.

## Enfoque

Cerrar primero las vías de compromiso del despliegue, acceso interno y abuso autenticado antes de invitar organizaciones externas. Se mantiene LIGHT/SMART y Blockchain OFF, junto al mTLS general temporal y al mTLS administrativo. La retirada controlada del mTLS general sigue perteneciendo a v0.0.14 y depende de superar esta versión.

El trabajo se construirá como **motores de ejecución reutilizables, parametrizados y con contratos verificables**: acceso de despliegue, descarga segura, identidad/autorización, políticas de red, admisión/consumo, aceptación de eventos y recuperación. Las diferencias por servicio, proveedor y entorno se expresarán como configuración validada. No se aceptan excepciones de seguridad escritas para una URL, cliente, modelo, noticia o caso concreto.

El detalle de evidencia, disputas, condiciones y límites está en [security_review_codex.md](docs/security/security_review_codex.md). Las fuentes al mismo nivel son la [auditoría aportada](docs/security/security_review_aportada.md) y la [revisión Copilot](docs/security/security_review_copilot.md). Este archivo contiene la ejecución pendiente; los informes conservan sus conclusiones originales.

No se añaden funcionalidades comerciales. La aceptación funcional/factual pendiente de v0.0.13 mantiene sus propios criterios. Ni una orden `VALIDATED` ni el cierre de esta auditoría acreditan por sí solos calidad factual o preparación comercial.

## Prioridad y reglas de ejecución

1. **P0:** asegurar la identidad del despliegue antes de otro pipeline privilegiado; contener inmediatamente cualquier secreto activo expuesto o exposición directa descubiertos durante el inventario. El impacto potencial es alto, sin explotación crítica remota demostrada.
2. **P1:** cerrar descarga saliente, autorización/segmentación, cuotas/bajas, mensajería, identidad JWT/JWKS y recuperación/migración. Bloquean abrir v0.0.14.
3. **P2:** endurecimiento general de pods, cadena de suministro, TLS restante, cabeceras y Blockchain. Se registra cada residual con responsable y fecha de revisión; se eleva si las comprobaciones revelan exposición activa o una vulnerabilidad aplicable grave.

Mantener el acceso protegido mientras se ejecuta el plan. Aplicar cambios operativos con lock y rollback preparado, verificar el resultado y cerrar la ventana. No abrir beta mediante una aceptación genérica de riesgos P0/P1: si se cambia el alcance, registrar una decisión explícita y revisar estas puertas.

## Puntos a ejecutar, de mayor a menor riesgo

Todas las tareas parten **pendientes**. Los roles son responsables propuestos, no personas ya asignadas; el operador debe asignar un titular antes de iniciar cada paquete. Las horas incluyen implementación, pruebas específicas y documentación; son estimaciones, no compromisos.

| Orden / paquete | Prioridad y auditoría | Trabajo y motor resultante | Dependencias | Responsable propuesto | Horas |
| --- | --- | --- | --- | --- | --- |
| S00 | P0 · SEC-13/14 y contexto | Fijar SHA/digests/perfil/render; inventariar flujos, datos, reglas, secretos por entorno y permisos de CI. Comprobar origen IPv4/IPv6, puertos, Cloudflare y LIGHT/OFF. Rotar/contener de inmediato si aparece exposición activa. | Ninguna; lectura sin pipeline inseguro | Operación + seguridad | 6–10 |
| S01 | P0 · SEC-01 · ISSUE-003/004 | Motor de acceso CI con host key independiente, SSH estricto, CA/nombre K3s válidos y mínimo privilegio. Aplicarlo a preflight, deploy, bootstrap y rollback que accedan al clúster. | S00 | Plataforma/CI | 8–14 |
| S02 | P1 · SEC-02/19 | Motor compartido de descarga: resolución ligada a conexión, política de IP/puerto/proxy, TLS/Host/SNI, redirecciones y presupuesto total. Corregir fixture de tests que sustituye el validador real. | S00; despliegue tras S01 | Backend + seguridad | 16–28 |
| S03 | P1 · SEC-03/16 | Motor de identidad/autorización de servicios con acciones/audiencias/recursos, asociación a organización resuelta en servidor y delegación de usuario/tenant verificables; transporte protegido para canales sensibles. Quitar `admin=True` implícito e identidad administrativa basada solo en cabecera. | S00; coordinación con S04 | Backend + plataforma | 20–36 |
| S04 | P1 · SEC-04 | Motor declarativo de flujos por perfil; default-deny progresivo de ingreso/salida con DNS, probes, operación y destinos legítimos. Probar enforcement del controlador y denegación desde pod ajeno. | Matriz S00; validar S02/S03 | Plataforma/red | 12–24 |
| S05 | P1 · SEC-05 | Motor de reserva/consumo/liberación y presupuesto por organización: operación idempotente antes del gasto, concurrencia y replay seguros, corrección de la secuencia `consumo+1`/`consumo-1`. Cubrir HTTP, Kafka, LIGHT y contratos de Blockchain sin habilitarlo en Hetzner. | S03; contrato con S07 | Backend | 24–40 |
| S06 | P1 · SEC-06 | Integrar estado/vigencia de organización, usuario y cliente OIDC en la admisión; definir bajas/suspensiones, trabajos pendientes y latencia de revocación. | S03/S05 | Backend + identidad | 6–10 |
| S07 | P1 · SEC-07 | Motor de política de mensajería por servicio/topic/acción, SASL/TLS o mecanismo equivalente, ACL y aceptación correlacionada/idempotente de eventos. Extender helper común para fallar sin credenciales, sin fallback a PLAINTEXT. Desactivar creación libre de topics según inventario. | S03/S04; acordar idempotencia con S05 | Plataforma + backend | 16–30 |
| S08 | P1 · SEC-09 | Motor de backup/restauración por inventario: cifrado externo, claves separadas, integridad, retención, consistencia y verificación de MongoDB/Keycloak; ensayo aislado y rollback compatible. Definir y medir RPO/RTO. | S00/S01; obligatorio antes de S09 | Operación/datos | 16–28 |
| S09 | P1 · SEC-08 | Migración reproducible de MongoDB a versión soportada, drivers/herramientas/FCV compatibles; restauración, índices/counts y regresión. Ensayar rollback por restauración, sin downgrade directo de PVC. | S08 y compatibilidad de candidato | Datos + backend | 20–36 |
| S10 | P1 · SEC-10/17/19 y SEC-16 sensible | Motor de verificación JWT con caché JWKS acotada, rotación/refresh controlados, timeout/concurrencia y distribución autenticada de claves. Contrato obligatorio de sujeto/vigencia/audiencia/presentador; pruebas de firma reales en entorno reproducible. | S01/S03; puede desarrollarse con S05 | Backend + identidad | 12–20 |
| S11 | P1 · SEC-14 | Reconciliar contrato API/GUI/reglas de borde: PUT solo donde procede, mTLS permanente sin excepción por método, JWT/rol; comprobar login/refresh/logout, lock y origen. Preparar transición posterior sin ejecutarla. | S01–S04/S10; repetir tras S09 | Operación + frontend | 6–10 |
| S12 | P1 · SEC-01–10/14/16/17/19 | Campaña integrada del candidato exacto: aislamiento entre tenants, fallos de confianza, SSRF, cuotas concurrentes, bajas, ACL, recuperación y regresión LIGHT/SMART. Inventario/escaneo del candidato y cierre o elevación de riesgos graves. | S01–S11 | Seguridad + QA + operación | 16–28 |

S08 se inicia pronto porque protege la migración y cualquier cambio de estado; su posición en la tabla expresa prioridad de riesgo, no obliga a esperar a S07. S05/S07 comparten el contrato de idempotencia y deben integrarse antes de aceptación. Las actividades independientes pueden prepararse en paralelo si hay capacidad; cada cambio desplegado conserva sus dependencias y puertas.

## Planning por hitos

Plan relativo al inicio autorizado de implementación, sin fecha de despliegue comprometida. La preparación de este documento no inicia ni cierra las tareas.

| Hito | Paquetes y esfuerzo | Resultado exigido para avanzar |
| --- | --- | --- |
| G0 — Confianza y fotografía operativa | S00 + S01 · **14–24 h** | Identidades de SSH/K3s verificadas, rechazos negativos antes de acciones privilegiadas, base del despliegue y exposición registrada; cualquier exposición activa contenida |
| G1 — Cerrar el camino descarga → interior | S02 + S03 + S04 · **48–88 h** | Resolución/conexión sometidas a la misma política, Admin/News Handler autentican y autorizan, pod ajeno bloqueado, flujos legítimos conservados |
| G2 — Integridad, identidad y gasto | S05 + S06 + S07 + S10 · **58–100 h** | Reservas previas e idempotencia, bajas efectivas, Kafka con identidades/ACL, JWT/JWKS robustos y claves transportadas por canal autenticado |
| G3 — Recuperación y plataforma de datos | S08 + S09 · **36–64 h** | Copia cifrada externa y restauración aislada probadas antes de migrar; MongoDB soportado, recuperación y rollback medidos |
| G4 — Aceptación del candidato | S11 + S12 · **22–38 h** | Pruebas por borde e internas, regresión y evidencias sobre el mismo SHA/digests; decisión GO/NO-GO registrada |

**Estimación total P0/P1: 178–314 horas técnicas.** Con una persona a 40 h/semana y un margen de integración del 20 %, aproximadamente **5,5–9,5 semanas**. No incluye esperas por accesos/ventanas, una migración fallida ni incidentes que descubra el inventario. No sumar por segunda vez los tests propios de cada paquete; S12 cubre su integración y la aceptación final.

Ruta de dependencia principal: `G0 → G1 → G2 → G4`, con `S08 → S09 → G4` iniciable tras G0. Se puede adelantar desarrollo local; no se usa la CI insegura para «validar que luego se corregirá».

## Aceptación verificable

| Puerta | Pruebas mínimas de cierre |
| --- | --- |
| Confianza del despliegue | Host key ausente/cambiada, CA incorrecta y nombre TLS incorrecto detienen todo job privilegiado antes de lectura de Secrets, apply o migración; deploy/rollback válidos funcionan |
| Descarga segura | Privadas, loopback, link-local, IPv4/IPv6, DNS mixto y rebinding controlado rechazados; redirección/retry no eluden controles; TLS sigue verificándose, bytes y tiempo total acotados |
| Autorización/tenants | Sin identidad interna o audiencia/permiso incorrectos: rechazo. Dos organizaciones no leen/infieren órdenes, eventos, validaciones, enlaces, búsquedas o exportaciones ajenas. Rol global y rol de cliente diferenciados |
| Red y broker | Pod sin permiso no alcanza Admin/bases/broker; cliente Kafka ajeno o topic prohibido rechazados. DNS, probes, logs y operaciones autorizadas funcionan |
| Consumo y baja | Solicitudes concurrentes nunca admiten gasto superior al reservado; redelivery/retry no duplica cobro; no hay consumos negativos. LIGHT no omite límites; suspendido/baja no admite trabajo nuevo según política |
| JWT/JWKS | Firma inválida, ausencia de `exp`/`sub` o issuer/audiencia/presentador incorrectos: rechazo uniforme. Probar expiración, claims ausentes, rotación, Keycloak caído y `kid` desconocidos sin tormenta de descargas |
| Datos y recuperación | MongoDB soportado sobre artefactos fijados; copias protegidas y restauración aislada MongoDB/Keycloak con login, índices/counts y consistencia. RPO/RTO y retorno de migración demostrados |
| Borde administrativo | Sin certificado: bloqueo de administración; con certificado sin JWT: rechazo del Gateway; sin rol: 403; autorizado: PUT funcional. Firewall del origen verificado y reglas atribuidas mediante eventos, no solo por un 403 |
| Regresión y entrega | LIGHT/SMART termina correctamente; Blockchain sigue OFF en todos los workloads efectivos; aceptación funcional pendiente de v0.0.13 respetada. Informe sobre mismo SHA/digests sin secretos |

Cada resultado registrará identificador de paquete/SEC, entorno, SHA, digest, render/perfil, instante UTC, ejecutor, esperado/obtenido y artefacto de evidencia. Ninguna tarea pasa a completada por existir código, YAML, un test sin ejecutar o una captura sin contexto.

**GO para cerrar v0.0.13b:** todas las puertas P0/P1 anteriores superadas y evidencias revisadas; riesgos P2 con titular/fecha/disparador, operación y rollback aceptados. **NO-GO:** cualquiera de esas puertas falla o queda sin demostrar. No se retira automáticamente mTLS ni se abre beta al cerrar: v0.0.14 conserva su propia ventana, revocación administrativa y aceptación.

## P2 y límites que continúan después

| Orden | Hallazgos | Trabajo reutilizable pendiente | Tratamiento |
| --- | --- | --- | --- |
| S13 | SEC-11 | Política uniforme de pods, capacidades/seccomp, ServiceAccount/RBAC y filesystem por workload | Completar en v0.0.16; elevar antes si S00/S12 identifica privilegios innecesarios sensibles |
| S14 | SEC-12/13 | Locks/digests/SBOM/escaneo obligatorios de toda la plataforma, verificación de herramientas y gestión de secretos por entorno | Escaneo/inventario del candidato ya en S12; cobertura completa en v0.0.16. Secreto activo expuesto: contención P0 inmediata |
| S15 | SEC-15/16 restante | Política de cabeceras probada con GUI/OIDC y protección de transporte restante según datos/riesgo | Comprobar exposición en S11/S12; completar política en v0.0.16. Canales de identidad/Admin/Kafka ya incluidos en P1 |
| S16 | SEC-18 | Gate de activación Blockchain, RPC mínimo y cliente soportado, claves/firmas y recuperación del perfil ON | Permanece OFF. Bloquea cualquier habilitación, incluso antes de v0.0.16; probar localmente en entorno aislado |

No se cuentan estas ampliaciones en las 178–314 h. Se estimarán tras el inventario. AOP específico de origen, service mesh, Cloudflare Tunnel y alta disponibilidad requieren decisión técnica propia; no se imponen para resolver los defectos comprobados. El nodo único mantiene su riesgo de disponibilidad, que deberá aceptarse o corregirse en preparación productiva.

El [roadmap](docs/next_releases.md) y el [registro de releases](docs/releases.md) sitúan v0.0.13b antes de v0.0.14. ISSUE-003/004 se adelantan desde el objetivo anterior v0.0.16; siguen abiertas hasta su cierre demostrado. Los informes históricos no se reescriben para aparentar que estas medidas ya estaban implantadas.
