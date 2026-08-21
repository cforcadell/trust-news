# Próximas versiones

Este documento contiene únicamente las versiones posteriores a la versión en
curso. El estado de `v0.0.12` está en [`version.md`](version.md) y las
versiones publicadas en [`releases.md`](releases.md).

## Resumen

| Versión | Objetivo | Criterio principal de salida |
| --- | --- | --- |
| v0.0.13 | Estabilización funcional y demo repetible | Regresión GUI/API superada, sin P0/P1 y tres demos internas consecutivas |
| v0.0.14 | Beta cerrada por invitación | Dos evaluaciones externas y un candidato a design partner |
| v0.0.15 | Piloto con design partners | Un piloto con evidencia de valor y decisión explícita de continuidad |
| v0.0.16 | Preparación de producción | Hardening y recuperación demostrados; riesgos resueltos o aceptados |
| v0.9.0 | Release Candidate | Regresión integral y decisión formal GO/NO-GO |
| v1.0.0 | Producción controlada | Caso repetible, compromiso contractual y operación aceptada |

## v0.0.13 - Estabilización funcional y demo repetible

### Objetivo

Probar sistemáticamente la GUI y la API, corregir los problemas fundamentales y
obtener una demo privada reproducible con datos sintéticos. El estado del lock
se decide explícitamente para cada ventana y se comprueba antes y después de
ella. Durante toda esta versión se conservan la regla mTLS general temporal para
las rutas no administrativas y la regla mTLS administrativa permanente. No se
entregan accesos persistentes a clientes.

### Fase 13.1 - Preparación reproducible

- Crear un conjunto fijo de datos sintéticos sin información de clientes.
- Definir identidades pseudónimas de administrador, usuario y cliente API para
  al menos dos organizaciones sintéticas.
- Preparar casos Light y Blockchain con resultados comprobables.
- Documentar la inicialización, limpieza y repetición de los datos.
- Registrar versión, configuración y resultado sin guardar tokens, secretos ni
  datos personales.
- Fijar una línea base de latencia, errores y recursos.

Resultado esperado: cada regresión parte del mismo estado y genera evidencia
comparable.

### Fase 13.2 - Regresión de GUI

- Login, sesión, refresh, logout y expiración.
- Navegación y control por rol.
- Creación, consulta y seguimiento de órdenes.
- Flujos completos Light y Blockchain.
- Aserciones, validaciones, evidencias, validadores y enlaces entre entidades.
- Filtros, búsqueda, paginación, cuotas y límites.
- Estados vacíos, carga, error, timeout y reintento.
- Español e inglés.
- Chrome, Edge y Firefox, resoluciones habituales y comprobación móvil básica.
- Ausencia de errores relevantes en consola y de mensajes que expongan trazas,
  secretos o detalles internos.

Resultado esperado: recorridos repetibles y sin defectos bloqueantes para una
demo.

### Fase 13.3 - Regresión de API y aislamiento

- Definir `TrustNewsApi` como audiencia de la API y activar la validación de
  `aud`.
- Validar `azp` o `client_id` contra una lista explícita de clientes
  presentadores.
- Probar autenticación válida, ausente, expirada y manipulada.
- Probar autorización de administrador, usuario y service account.
- Derivar la organización server-side desde el token verificado o desde una
  asociación interna inmutable.
- Rechazar o ignorar de forma segura cualquier `client_id` u organización
  aportados por el frontend para sustituir la identidad efectiva.
- Demostrar aislamiento entre organizaciones en listados, detalles, órdenes,
  aserciones, validaciones, evidencias, búsquedas, exportaciones y enlaces
  indirectos.
- Impedir que un administrador de cliente obtenga privilegios globales.
- Cubrir creación y seguimiento de órdenes, cuotas, recomendaciones,
  validadores, categorías y los modos Light y Blockchain.
- Probar esquemas, campos ausentes, parámetros inválidos, límites de tamaño y
  respuestas `400`, `401`, `403`, `404`, `409`, `413`, `429` y
  `5xx`.
- Comprobar timeouts, reintentos y compatibilidad entre Gateway y servicios.
- Evitar que respuestas, errores o logs revelen datos de otra organización.
- Ampliar los tests Python hasta disponer de una regresión de contrato
  repetible.

Resultado esperado: contratos estables y aislamiento completo aplicado en el
servidor.

### Fase 13.4 - Corrección y ensayos de demo

Cada defecto se reproduce, documenta, clasifica, corrige y vuelve a probar junto
con la regresión completa.

- Resolver
  [`ISSUE-001`](issues.md#issue-001---carrera-de-inicializacion-en-la-cache-de-validadores-light):
  eliminar la carrera de inicialización de la caché LIGHT y superar todas sus
  pruebas de concurrencia y despliegue sin refresco manual.

- **P0:** seguridad, corrupción o pérdida de datos, o plataforma inaccesible.
- **P1:** rompe autenticación, órdenes, Light, Blockchain o cuotas; permite
  cambiar de organización, acceder a datos ajenos o elevar privilegios.
- **P2:** degradación visible con alternativa temporal aceptable.
- **P3:** problema cosmético o mejora no necesaria para la demo.

Hay congelación funcional: no se incorporan X/Threads, reputación, LLM dedicado
ni Cloudflare Tunnel.

### Criterio de salida

- No quedan defectos P0 ni P1.
- `ISSUE-001` está resuelta y validada en Kind y Hetzner.
- Los P2 aceptados están documentados.
- GUI y API superan una regresión reproducible.
- Login, Light y Blockchain funcionan en tres demos consecutivas; una se
  ejecuta desde otra red o equipo con un certificado cliente temporal válido.
- No existe bypass del aislamiento por organización.
- La demo puede inicializarse, ejecutarse, limpiarse y cerrarse.
- Existe un guion de demo y una lista de limitaciones conocidas.
- La plataforma no se presenta como producción ni como alta disponibilidad.

## v0.0.14 - Beta cerrada por invitación

### Objetivo

Permitir que un máximo de diez organizaciones externas evalúen la plataforma
durante un periodo definido, con identidades pseudónimas y acceso OIDC
provisionado manualmente. La retirada controlada de la regla mTLS general
temporal pertenece a esta versión y se completa antes de abrir las evaluaciones
externas.

### Alcance

- Una identidad opaca por evaluador; no se permiten usuarios compartidos ni se
  exige nombre real o correo personal.
- Keycloak conserva solo identificador técnico, organización y roles
  imprescindibles.
- Logs y métricas no incluyen nombres, correos, tokens, credenciales ni datos
  personales evitables.
- La regla mTLS general temporal se retira en una ventana controlada,
  manteniendo activos el lock, la regla mTLS administrativa y un rollback
  probado.
- Los usuarios acceden por OIDC sin certificado; mTLS queda reservado a la
  administración.
- Cuando se habilite API, cada organización usa su propio cliente confidencial;
  no se comparte el secreto de `TrustNewsApi`.
- Se validan firma, issuer, vigencia, audiencia, cliente presentador y roles.
- La asociación identidad-organización es inmutable y se resuelve server-side.
- El aislamiento cubre todos los recursos, búsquedas y exportaciones.
- Se aplican cuotas por organización, auditoría mínima, soporte y offboarding.
- Cada evaluación dispone de guía, tres tareas y recogida estructurada de
  feedback.

### Límite y datos

- Se permiten diez organizaciones externas activas simultáneamente. Los tenants
  sintéticos e identidades internas no consumen ese límite.
- No hay autorregistro. Altas, roles y cuotas se aprueban manualmente.
- El alta número once queda bloqueada y pasa a una lista de espera.
- No se introducen credenciales, datos personales, regulados o confidenciales
  sin necesidad, autorización y tratamiento acordados.
- Cada evaluación define fecha final, retención y limpieza.
- Los datos sintéticos o desechables no tienen recuperación garantizada.
- Un dato que deba conservarse exige backup mínimo; un dato irremplazable exige
  una restauración probada.

### Criterio de salida

- Una organización no puede leer ni inferir recursos de otra, aunque manipule
  `client_id`, parámetros o enlaces.
- Un administrador de cliente no puede elevarse a administrador global.
- Usuarios desactivados y tokens incorrectos o caducados pierden acceso.
- Los límites no rompen login, refresh ni polling legítimos.
- La regla mTLS general temporal está retirada y la administración continúa
  protegida por su regla mTLS permanente.
- El alta número once se deriva a la lista de espera.
- Se completan dos evaluaciones externas y se identifica un candidato a design
  partner con problema, métrica y posible piloto.

## v0.0.15 - Piloto con design partners

### Objetivo

Validar durante cuatro a ocho semanas uno o dos casos de uso especializados,
con alcance, datos, soporte y métricas acordados antes de desarrollar.

### Alcance

- Caso de uso y criterio de éxito acordados antes del piloto.
- Datos delimitados, exportación, eliminación y seguimiento semanal definidos.
- Pruebas de carga representativas, reinicios controlados y degradación de una
  dependencia.
- Hardening del canal CI, privilegio mínimo de Geth y artefactos reproducibles
  en los componentes afectados.
- Medición de latencia, coste por validación, calidad percibida, repetición y
  carga de soporte.

Este hardening se limita a los componentes afectados por el piloto. El cierre
transversal del pipeline, Geth, segmentación y cadena de suministro permanece
en `v0.0.16`.

Los datos desechables pueden aceptar riesgo de pérdida. Los datos que deban
conservarse requieren backup mínimo antes de entrar; los irremplazables no se
admiten hasta demostrar una restauración aislada.

La reputación de validadores y el LLM dedicado solo se incorporan si el piloto
demuestra su necesidad. X/Threads permanece en backlog hasta validar un flujo o
canal comercial concreto.

### Criterio de salida

Al menos un piloto termina con evidencia de valor y una decisión explícita de
continuar, cambiar el producto o detener el caso de uso.

## v0.0.16 - Preparación de producción

### Objetivo

Convertir la plataforma validada con clientes en un servicio operable. Es una
versión de estabilización y no incorpora funcionalidades comerciales salvo las
imprescindibles para cerrar un riesgo de producción.

### Hardening de identidad

- Revisar y endurecer la validación de `aud` implantada antes de la beta.
- Conservar la validación de `azp` o `client_id` mediante una lista explícita
  de clientes presentadores.
- Mantener validación de firma, algoritmo, issuer, expiración y vigencia.
- Separar permisos de usuario y service account.
- No registrar headers, tokens ni claims sin verificar.
- Eliminar implementaciones duplicadas de rutas administrativas.
- Ampliar y mantener las pruebas negativas de audiencia, presentador, issuer,
  expiración, firma y ausencia de token.

### Confianza del pipeline

- Resolver [`ISSUE-003`](issues.md#issue-003---ci-no-autentica-el-api-de-k3s-con-su-ca):
  autenticar el API de K3s con su CA real y eliminar saltos TLS inseguros.
- Resolver [`ISSUE-004`](issues.md#issue-004---ci-no-fija-la-clave-ssh-del-servidor):
  fijar y verificar la clave SSH esperada con `StrictHostKeyChecking=yes`.
- Hacer obligatorios los controles de seguridad aplicables a cada perfil.
- Probar que una CA, nombre TLS o clave SSH incorrectos fallan antes de ejecutar
  despliegues.

### Geth y segmentación interna

- Retirar `admin`, `personal`, el desbloqueo remoto y los comodines de CORS
  y virtual hosts de los RPC.
- Publicar únicamente módulos y métodos consumidos por la aplicación.
- Mantener RPC como `ClusterIP`, sin Ingress ni NodePort.
- Comprobar que el CNI aplica `NetworkPolicy`.
- Implantar `default-deny` progresivo con allowlists mínimas, incluido DNS.
- Aislar Geth, MongoDB, PostgreSQL, Kafka, IPFS, paneles y servicios
  administrativos.
- Demostrar que un pod no autorizado no puede alcanzar servicios sensibles.

### Cadena de suministro y capacidad

- Eliminar `latest`, referencias flotantes e imágenes sin versión.
- Fijar imágenes y dependencias por digest; desplegar los digests construidos
  por el pipeline.
- Generar inventario o SBOM, ejecutar escaneo y añadir controles al render
  productivo.
- Completar `requests` y `limits`, medir rollouts y definir alertas de
  memoria, disco y presión del nodo.
- Definir SLO, RTO y RPO.
- Decidir explícitamente si se acepta el nodo único como SPOF o se adopta
  infraestructura multinodo; una réplica en un nodo no se presenta como HA.
- Resolver o aceptar expresamente `DNSConfigForming`.

### Backups, restauración y operación

- Crear backups cifrados externos de MongoDB y PostgreSQL de Keycloak.
- Respaldar genesis, keystores, credenciales Ethereum, contrato, ABI,
  categorías, secretos Kubernetes, variables CI/CD, claves API y secretos OIDC.
- Verificar hash, fecha, tamaño, cifrado y legibilidad fuera del clúster.
- Restaurar MongoDB y Keycloak en un destino aislado y comprobar login y
  recuentos.
- Verificar dirección y bytecode del contrato frente a la línea base.
- Ensayar rollback de aplicación, manifests, configuración, imágenes y datos.
- Ejecutar carga, soak, fallos y recuperación.
- Preparar runbooks de incidentes, credenciales, certificados, soporte y bajas.
- Revisar privacidad, retención y condiciones de servicio.

Nunca se prueba una restauración destructiva sobre los PVC activos. El resultado
exige evidencia de restauración, no solo la existencia de ficheros de backup.

### Cloudflare Tunnel opcional

Puede sustituirse el inbound HTTPS por un Named Tunnel iniciado desde el
clúster, únicamente si un análisis explícito justifica el cambio. No forma parte
de `v0.0.13` y se estima en 12 a 18 horas técnicas.

Condiciones mínimas:

- `cloudflared` como workload restringido, con credencial externa, probes,
  límites, dos réplicas y `--no-autoupdate`.
- Traefik sigue siendo el único router para `/`, `/backend` y `/auth`.
- El salto `cloudflared -> Traefik` valida el Origin CA y
  `originServerName=assermetry.com`; no se usa `noTLSVerify`.
- `forwardedHeaders.insecure` permanece desactivado y solo se confían los
  orígenes internos definidos.
- El lock y el mTLS administrativo permanecen activos durante el cambio.
- El inbound `443` no se retira hasta superar las pruebas de extremo a extremo
  y preparar el rollback.
- Tras el periodo de observación, Traefik pasa a `ClusterIP` y no queda una
  ruta alternativa mediante LoadBalancer, NodePort, hostPort, IP pública o DNS
  histórico.
- Se validan IP real, rate limits, logs, pérdida de un conector, smoke tests y
  rollback completo.
- El perfil local no depende de `cloudflared`.

Resultado esperado: el dominio funciona exclusivamente por el túnel, Hetzner no
admite puertos web inbound y se conservan WAF, OIDC, mTLS administrativo,
límites y observabilidad. La opción no aporta alta disponibilidad del host
mientras el clúster siga en un único nodo.

### Criterio de salida

- Todos los flujos aplican identidad y autorización estrictas.
- CI autentica SSH y Kubernetes y no permite omitir controles.
- Geth no expone APIs administrativas ni desbloqueo inseguro.
- Las NetworkPolicy limitan el movimiento lateral.
- Producción usa artefactos inmutables e inventariados.
- Capacidad y disponibilidad tienen evidencia y decisión de riesgo.
- Backups cifrados externos y restauración aislada están demostrados.
- Rollback, carga, soak, fallos y recuperación están probados.
- Los riesgos restantes están resueltos o aceptados formalmente.

Cualquier incumplimiento mantiene el estado NO-GO y bloquea `v0.9.0`.

## v0.9.0 - Release Candidate

- Congelación funcional.
- Ensayo completo de despliegue, migración y rollback.
- Restauración repetida, aislada y cronometrada.
- Regresión funcional integral.
- Pruebas negativas de seguridad, carga y soak.
- Revisión de observabilidad, soporte y procedimientos operativos.
- GO/NO-GO formal con responsables y excepciones registradas.

Cualquier fallo crítico produce NO-GO y requiere una nueva release candidate.

## v1.0.0 - Producción controlada

Producción no exige autorregistro ni acceso anónimo. El servicio puede continuar
invite-only mediante OIDC y con mTLS exclusivamente administrativo.

La versión recibe GO cuando:

- Dos organizaciones especializadas han completado una evaluación o piloto.
- Al menos una mantiene un compromiso contractual de producción.
- Existe un caso de uso repetible y una propuesta económica sostenible.
- Backup, restauración, seguridad, capacidad y soporte están aceptados.
- Se conocen responsables, horarios, escalado y límites del servicio.
- El rollback de apertura o cierre está probado.

WAF, mTLS administrativo, rate limits, logs y alertas permanecen activos. La
regla de lock continúa disponible y su activación está probada.

## Secuencia transversal

1. Demo interna con datos sintéticos y operador presente.
2. Demo externa guiada con identidad OIDC temporal y, mientras siga vigente
   `v0.0.13`, certificado cliente temporal.
3. Evaluación cerrada con credenciales persistentes y fecha final.
4. Piloto con alcance, métricas y soporte pactados.
5. Release Candidate sin nuevas funcionalidades.
6. Producción controlada para clientes contratados.

Antes de cada demo o evaluación se congelan cambios durante 24 a 48 horas, se
activa el lock para desplegar, se ejecutan preflight, regresión y smoke y se abre
solo la ventana autorizada. Al finalizar se cierra el acceso, se revocan las
credenciales temporales y se limpian los datos previstos.

Material necesario: one-pager, presentación breve, guion de demo, guía de
evaluación, explicación de las garantías y límites de Assermetry, ficha de
seguridad y datos, FAQ, limitaciones conocidas y propuesta de piloto.

El proceso comercial previsto es:

```text
descubrimiento -> demo guiada -> evaluación -> design partner -> piloto -> producción
```

Se medirán tiempo hasta la primera validación útil, finalización de tareas,
utilidad percibida, repetición, coste y latencia por validación, carga de soporte
y conversión entre etapas.

## Invariantes

- No renombrar el realm `TrustNews` ni los clientes OIDC existentes.
- No publicar bases de datos, Kafka, IPFS API, RPC, paneles o APIs
  administrativas.
- No añadir `www.assermetry.com` sin una redirección canónica probada.
- No usar este roadmap como sustituto de los runbooks operativos.
- No afirmar que blockchain garantiza la verdad; el mensaje se centra en
  trazabilidad, evidencia, diversidad de validadores y auditabilidad.
