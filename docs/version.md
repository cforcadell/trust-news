# v0.0.13b — Plataforma de demos controladas

**Estado: en ejecución; apertura NO-GO hasta superar las puertas en Hetzner/K3s.** S00 y S01 están cerrados para preproducción con riesgos residuales. S02 y S03 tienen aceptación local en kind; el operador confirma que todas las pruebas locales del camino declarativo S03 están OK y se cierra esa aceptación. En la comprobación local del 13-11-2026, el preflight S03 pasó para nueve servicios y la inspección de variables no sensibles confirmó S03 activo y Blockchain OFF donde aplica. S07a superó en kind los E2E técnicos TLS y el E2E funcional autenticado LIGHT/SMART. La aceptación de S02, S03 y S07a en Hetzner/K3s sigue pendiente; la aceptación funcional/factual de v0.0.13 también.

**Entornos:** kind en VM es desarrollo local; Hetzner/K3s es preproducción; producción no existe. Los perfiles y overlays `-prod` conservan un nombre histórico. Código, render y pruebas kind no acreditan el comportamiento efectivo en Hetzner.

## Objetivo y límites de uso

Ofrecer demostraciones guiadas de LIGHT/SMART con Blockchain OFF y, como máximo, acceso temporal a **dos organizaciones externas identificadas**. Cada una tendrá identidad y organización propias. Se mantienen el mTLS general y administrativo, el gate de rutas de Cloudflare y el origen restringido. Altas, certificados, roles, cuotas, caducidad y bajas se gestionan manualmente y quedan registrados; no hay autorregistro, API pública para clientes ni apertura anónima.

Las demos usan datos sintéticos o desechables, sin datos personales, regulados, confidenciales o irremplazables, ni promesa de conservación. Se fija ventana, presupuesto de peticiones/coste, responsable y forma de revocar acceso. Mientras S05 no cierre la contabilidad idempotente, las organizaciones invitadas no pueden iniciar por sí mismas trabajos con gasto: el operador ejecuta cada flujo autorizado con identidad acotada, presupuesto comprobado y seguimiento de consumo. Si esta separación no puede imponerse y verificarse en el borde, **NO-GO para clientes**; solo se permiten demos internas guiadas.

Esta versión no acredita producción, servicio autónomo, piloto comercial, calidad factual general ni disponibilidad garantizada. No retira el mTLS general. Los controles se construyen como **motores reutilizables y contratos parametrizados**, sin ramas por cliente, URL, noticia o demo. Antes de añadir una función se adapta el motor compartido existente. La [auditoría contrastada](security/security_review_codex.md) y los [diseños S02](security/s02-design.md) y [S03](security/s03-design.md) conservan la justificación técnica; sus conclusiones históricas no equivalen a aceptación de este nuevo alcance.

## Estado y trabajo de v0.0.13b

La [ficha del candidato Hetzner/K3s](deploy/candidate-v0.0.13b-k3s.md)
registra el SHA base y los renders comprobados; el candidato sigue sin fijar
porque el árbol contiene cambios sin publicar y faltan digests y evidencia
efectiva del mismo SHA en K3s.

| Paquete | Estado observado | Trabajo y evidencia para demos |
| --- | --- | --- |
| S00 · inventario | Completado con hallazgos abiertos. [Inventario](security/s00-inventory.md). | Revalidar borde, flujos, secretos y responsables. No hay copias externas ni rotación definida. |
| S01 · confianza CI | Cerrado para preproducción: deploy `#3039935585`, preflight acceso/TLS/revisiones `#3040405655`; restauración de Deployment temporal probada en kind. | Revalidar preflight del candidato. TOFU de host key/CA y kubeconfig cluster-admin compartido son riesgos aceptados; rollback automático ante fallo real no ensayado en K3s y sin cobertura de datos/ConfigMaps. Preparar lock y rollback. |
| S02 · descarga pública | Motor común implementado y aceptado en kind, con E2E LIGHT/SMART y DIRECT comunicados por el operador. | Desplegar en Hetzner y probar descargas válidas, bloqueo SSRF/rebinding, TLS, límites y regresión desde el borde. |
| S03 · identidad y autorización | Aceptación local en kind, incluido el camino declarativo; el operador confirma todas las pruebas locales OK. Preflight actual: nueve servicios; variables no sensibles de runtime comprobadas. | Integrar y aceptar en Hetzner; comprobar Secrets efectivos sin valores, TLS, JWT/claims y aislamiento con dos organizaciones. Mantener inaccesibles propietarios legacy ambiguos. |
| S07a · Kafka TLS | En kind: E2E técnico de producción/consumo TLS, rechazo PLAINTEXT y E2E funcional autenticado LIGHT/SMART superados. | Integrar y aceptar TLS/CA y LIGHT/SMART en Hetzner. No atribuirle identidad ni ACL Kafka. |
| S11-D · borde de demos | Pendiente. | Verificar mTLS general/administrativo, gate de rutas, origen, login/refresh/logout, roles, Admin y revocación de invitación. Reutilizar la matriz S11. |
| S12-D · aceptación de demos | Pendiente. | Campaña acotada del SHA/digests/render/configuración efectivos: dos organizaciones, negativos, LIGHT/SMART, costes, límites, fallos y baja; GO/NO-GO firmado. Reutilizar runner y matriz S12. |

S11-D y S12-D son **cortes de aceptación** de S11 y S12, sin motores duplicados. Preparar S08 desde ahora. Antes de guardar datos que deban conservarse se exige copia y restauración demostrada. Un secreto activo expuesto o una ruta administrativa directa requiere contención inmediata, independientemente de la versión.

## Puertas de apertura de demos

1. **Candidato y operación:** SHA, imágenes, perfil, render, SMART y Blockchain OFF comprobados dentro de los pods Hetzner; preflight CI, lock, observación, responsable y rollback preparados. Riesgos TOFU, cluster-admin y límite de rollback aceptados explícitamente para la ventana o corregidos.
2. **Acceso y aislamiento:** mTLS de usuario/administrativo, OIDC, permisos de servicio/persona, rutas y origen probados en Hetzner. Comprobar que un invitado solo alcanza las rutas previstas del borde y no llega directamente a Admin, bases o broker. Dos organizaciones no leen ni infieren recursos ajenos. Se rechazan token ausente, firma/audiencia/presentador erróneos y rol insuficiente. Alta y baja manuales probadas con identidad descartable; medir el plazo efectivo de revocación del certificado, cuenta y token, sin prometer baja instantánea antes de S06.
3. **Flujo y presupuesto:** S02, S03 y S07a integrados en el candidato; LIGHT/SMART completa demo desde el borde. Solicitudes, coste y duración medidos y limitados. La invitación no permite iniciar gasto sin supervisión hasta S05; se detiene el flujo al alcanzar presupuesto.
4. **Datos y comunicación:** solo datos desechables; consentimiento, duración y borrado documentados. Sin promesa de persistencia o exactitud factual. Si se precisan datos conservables, confidenciales o flujo autónomo, se aplican las puertas posteriores.
5. **Evidencia:** cada prueba identifica entorno, instante UTC, SHA/digests, perfil, ejecutor, esperado/obtenido y artefacto sin secretos. Fallo, prueba ausente o cambio posterior del candidato devuelve a NO-GO. Una orden `VALIDATED` no cierra la aceptación de v0.0.13.

**GO de v0.0.13b:** cinco puertas superadas para Hetzner y la ventana concreta. El operador registra alcance, impacto, compensaciones, caducidad y criterio de suspensión de los riesgos residuales, incluidos S04, S05, S06, S07b, S08–S10 y los límites S01; un camino externo directo a servicios internos es NO-GO, no un riesgo aceptable para demos. **NO-GO:** falta cualquiera de las puertas. El GO habilita solo demos en estos límites y como máximo dos organizaciones; no retira mTLS, no abre beta ni promueve a producción.

## Trabajo posterior y roadmap

Los P1 diferidos no se consideran aceptados por reducir el alcance. [v0.0.13c](releases.md) reúne los controles **antes del acceso autónomo de clientes y de v0.0.14**:

| Paquetes | Dependencia | Resultado pendiente |
| --- | --- | --- |
| S04 · SEC-04 | Matriz S00, S02/S03 | Segmentación declarativa default-deny, enforcement y flujos legítimos. |
| S05 · SEC-05 | S03/S07 | Reserva, consumo y liberación idempotentes por organización; concurrencia, replay y límites LIGHT. |
| S06 · SEC-06 | S03/S05 | Estado/vigencia de organización, membresía y cliente OIDC; bajas y revocación medibles. |
| S07b · SEC-07 | S07a/S04/S05 | Identidad Kafka, ACL por topic/acción y aceptación correlacionada de eventos. |
| S08 → S09 · SEC-09/08 | Iniciar S08 pronto; restauración antes de migrar | Copia cifrada externa y restauración aislada MongoDB/Keycloak; luego migración reproducible de MongoDB 4.4 a versión soportada y retorno ensayado. |
| S10 · SEC-10/17/19 | S03 | Caché JWKS, rotación, concurrencia y fallo acotado; S03 ya exige verificación criptográfica. |
| S11/S12 completos | Paquetes anteriores | Contrato de borde para acceso autónomo y campaña integral del candidato exacto: aislamiento, gasto, bajas, Kafka, recuperación y regresión. |

Las estimaciones históricas P0/P1 de **178–314 h** cubrían el cierre integral hasta acceso autónomo; **no estiman v0.0.13b**. Reestimar v0.0.13c tras fijar candidato y dependencias. v0.0.14 mantiene transición controlada del mTLS general, revocación administrativa y aceptación propia con límite de dos clientes; v0.0.15 es piloto con uno o dos socios de diseño. v0.0.16, v0.9.0 y v1.0.0 conservan preparación, candidato y producción como hitos futuros. Ninguno queda autorizado por el GO de demos.

El endurecimiento P2 sigue en v0.0.16: S13 (pods/RBAC), S14 (cadena de suministro y secretos), S15 (cabeceras/TLS restante). S16 bloquea habilitar Blockchain hasta controlar Geth, RPC, claves y recuperación. Los hallazgos graves descubiertos durante demos se elevan de prioridad. El nodo único conserva riesgo de disponibilidad a resolver o aceptar antes de producción.
