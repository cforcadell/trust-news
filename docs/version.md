# v0.0.13 - Estabilización funcional y demo repetible

Este documento describe únicamente la versión en curso. Las versiones publicadas
están en [`releases.md`](releases.md) y el roadmap está en
[`next_releases.md`](next_releases.md).

## Estado de la versión

**En curso.**

**Último hito completado:** publicación de la interfaz bajo `/gui/`, validada en
Kind y desplegada después en Hetzner. La frontera pública, los redirects de
Cloudflare, la integración OIDC y los flujos LIGHT y BLOCKCHAIN quedaron
verificados. El gate temporal con mTLS general se conserva hasta la v0.0.14,
junto con el mTLS administrativo permanente.

## Objetivo

Probar sistemáticamente la GUI y la API, corregir los problemas fundamentales y
obtener una demo privada reproducible con datos sintéticos. El estado del lock
se decide explícitamente para cada ventana y se comprueba antes y después de
ella. Durante esta versión se conserva un gate temporal que combina mTLS
general para las rutas no administrativas con el bloqueo de namespaces no
permitidos, además de la regla mTLS administrativa permanente. La retirada de
mTLS y la apertura a clientes pertenecen a la v0.0.14. No se entregan accesos
persistentes a clientes durante esta fase.

### Fase 13.1 - Preparación reproducible


- Definir identidades pseudónimas de administrador, usuario y cliente API para
  al menos dos organizaciones sintéticas.
- Preparar casos Light y Blockchain con resultados comprobables.
- Documentar la inicialización, limpieza y repetición de los datos.
- Registrar versión, configuración y resultado sin guardar tokens, secretos ni
  datos personales.
- Parametrizar mediante `HTTP_TIMEOUT` y `PUT /admin/config` el timeout de cada
  intento contra el proveedor LLM, con un valor predeterminado de 60 segundos.
- Unificar en JSON de una sola línea los logs de `admin`, `evidence-search`,
  `gateway`, `generate-asertions`, `ipfs`, `news-chain`, `news-handler` y
  `validate-asertions`, incluidos los registros de Uvicorn y las excepciones.
- Escapar dentro del JSON los saltos de línea de mensajes y tracebacks para que
  CRI, Fluent Bit y Loki conserven un único evento por registro, aunque Grafana
  pueda presentarlo indentado cuando esté activado `Prettify JSON`.
- Sustituir salidas directas y configuraciones de logging particulares que
  eludan el formato común. El generador no registrará prompts ni cuerpos LLM
  completos en nivel `INFO`; registrará proveedor, modelo, intento, estado,
  duración, tamaños y tipo de error.
- Fijar una línea base de latencia, errores y recursos.

Resultado esperado: cada regresión parte del mismo estado y genera evidencia
comparable.

El runner y los casos sintéticos de esta fase se mantienen en
[`web_classic/test`](../web_classic/test/README.md). `run-regression.js` ejecuta
Light y Blockchain, aplica oráculos funcionales y genera manifiesto, resumen y
capturas sanitizadas. Una ejecución solo acredita estado reproducible cuando se
activa `ASSERMETRY_REQUIRE_MANAGED_STATE=true` con hooks idempotentes de
preparación y limpieza; las escrituras Blockchain e IPFS no se revierten.

### Fase 13.2 - Regresión de GUI

- Publicar la interfaz bajo `/gui/`, conservar `/backend` y `/auth` como
  namespaces separados y probar primero el mismo contrato de Ingress en Kind.
- Alinear `TrustNewsWeb` con redirects y post-logout bajo `/gui/*`, manteniendo
  Web Origins limitado al origen sin path.
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

#### Resultado verificado - publicación bajo `/gui/`

- Despliegue validado primero en Kind y después en Hetzner desde el mismo
  commit, con los pipelines productivos completados correctamente.
- Frontend servido exclusivamente bajo `/gui/`, con prefijos estrictos,
  eliminación del prefijo en Traefik y sin un Ingress catch-all para `/`.
- `TrustNewsWeb` alineado con redirects, orígenes web y post-logout bajo
  `/gui/*`; login, refresh y logout validados.
- LIGHT establecido como modo predeterminado y BLOCKCHAIN activable mediante
  checkbox, con publicación, IPFS y trazabilidad comprobados.
- Progreso, timeout, errores y reintentos de generación de aserciones y polling
  verificados en la interfaz.
- Cloudflare configurado con redirects exactos `302` para `/` y `/gui`,
  preservación de query y bloqueo de paths ajenos a `/gui/`, `/backend` y
  `/auth`.
- Gate temporal combinado de mTLS y namespaces públicos validado, manteniendo
  el mTLS específico para la administración de Keycloak.
- Regresión de rutas, OIDC, LIGHT/BLOCKCHAIN, WAF y protección del origen
  completada sin defectos P0/P1 ni regresiones sostenidas durante la
  observación.

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

## Análisis fusionado de pruebas de dos IAs (2026-09-01)

Las pruebas de validación realizadas con Codex y Copilot coinciden en que el
problema central no es una falta de flujo, sino una falta de coherencia entre la
representación del resultado y la evidencia que la sustenta. Ambos análisis
concluyen que Assermetry debe pasar de un modelo de «veredicto opaco» a un
modelo de «análisis explicable y revisable por humanos».

### Síntesis del diagnóstico

- La categoría automática de aserciones y la extracción de afirmaciones no son
  todavía suficientemente fiables para beta cerrada.
- El estado del proceso, la decisión final y la representación temporal se
  mezclan en la misma pantalla.
- Las decisiones de consenso y los desempates no se explican de forma legible.
- Los errores de validadores y los timeouts se tratan como resultados válidos,
  cuando no generan evidencia y deben estar separados de `UNKNOWN`.
- La interfaz prioriza la lista de validadores y las fuentes sobre la evidencia
  principal, cuando el usuario necesita ver primero: afirmación, veredicto,
  unidad de medida, evidencia y fuente.
- El lenguaje de la experiencia sigue teniendo ambigüedad entre "publicar",
  "validar" y "auditar con blockchain"; esto debe simplificarse antes del piloto.
- La experiencia móvil y la internacionalización degradan la confianza del
  producto aunque el flujo básico funcione.

### Bloques funcionales priorizados

Los hallazgos se agrupan en nueve bloques que deben resolverse en este orden:

1. Coherencia temporal y de estado.
2. Consenso y veredicto.
3. Errores y reintentos de validadores.
4. Revisión humana de aserciones.
5. Evidencia principal y informe reutilizable.
6. Lenguaje y modos de operación.
7. Trabajos asíncronos y progreso persistente.
8. Responsive, navegación y accesibilidad.
9. Ambigüedad semántica y numérica.

Esta secuencia es coherente con el roadmap de [`next_releases.md`](next_releases.md):
los puntos 1 a 5 son correcciones de rigor y de confianza que deben cerrarse
antes de abrir evaluaciones con clientes; el resto refuerzan la experiencia y la
operación del piloto.

### Incidencias abiertas derivadas

Estas incidencias se han dado de alta en [`issues.md`](issues.md) y deben ser
la base de la ejecución técnica del ciclo de estabilización:

- [`ISSUE-005`](issues.md#issue-005---fechas-zonas-horarias-y-estados-temporales-inconsistentes-en-la-gui-de-resultados)
- [`ISSUE-006`](issues.md#issue-006---estado-provisionalfinal-mezclado-en-la-pantalla-de-proceso)
- [`ISSUE-007`](issues.md#issue-007---veredicto-global-y-calculo-de-consenso-no-explican-empates-ni-decisiones)
- [`ISSUE-008`](issues.md#issue-008---validadores-con-timeout-tratados-como-resultado-v-alido)
- [`ISSUE-009`](issues.md#issue-009---flujo-de-extraccion-y-clasificacion-de-afirmaciones-no-revisable)
- [`ISSUE-010`](issues.md#issue-010---resultado-no-presenta-evidencia-principal-ni-informe-reutilizable)

### Recomendaciones de implementación

- Separar `process_status` y `decision_status` en la API y en la UI: el proceso
  puede terminar sin que la decisión sea definitiva.
- Definir `TRUE`, `FALSE`, `UNKNOWN` y `NO_CONSENSUS` como categorías de
  decisión; no mezclar un empate con una falsedad determinada.
- Diferenciar `timeout` o `error` de `UNKNOWN`: un fallo de validación no equivale
  a un resultado de evidencia.
- Hacer el flujo `texto → afirmaciones → revisión → validación` obligatorio en la
  experiencia humana; la validación automática queda como modo operativo para
  integraciones y backends.
- Mostrar obligatorio el resumen de evidencia principal por afirmación: texto
  original, veredicto, fuente principal, fecha, enlace y fragmento de apoyo o
  contradicción.
- Sustituir la etiqueta de publicación por "Validar contenido" y simplificar el
  selector entre validación rápida y validación auditable, sin vender blockchain
  como garantía de verdad.
- Introducir progresos persistentes con un panel de validaciones activas y un
  aviso de finalización para el usuario.
- Corregir antes del piloto la experiencia móvil, la internacionalización y la
  accesibilidad base.

### Plan de implementación recomendado

- v0.0.13.x: corrección de rigor y consistencia.
  - `ISSUE-005`, `ISSUE-006`, `ISSUE-007`, `ISSUE-008`.
  - Lenguaje de producto y eliminación de mensajes ambiguos.
- v0.0.14: revisión humana y evidencia.
  - `ISSUE-009`, `ISSUE-010`.
  - flujo revisable de afirmaciones, resumen de evidencia de la orden y
    generación de informe compartible.
- v0.0.15: piloto con design partners.
  - seguimiento de validaciones activas, selector de modo, experiencias
    responsive/a11y y telemetría para comparar tasa de edición, rechazo y
    consenso.

### Criterio de salida para la fase actual

La versión en curso solo se considera estable cuando:

- la GUI distingue proceso y decisión sin contradicciones;
- los empates se presentan como `NO_CONSENSO` y no como decisión arbitraria;
- los errores de validación quedan separados de `UNKNOWN` y no se ocultan;
- el usuario puede revisar y corregir las afirmaciones antes de validar;
- la evidencia principal es visible sin abrir varios acordeones;
- las fechas y los formatos se renderizan de forma consistente en la zona del
  usuario.

Este criterio encaja con la intención del roadmap de `[next_releases.md](next_releases.md)`: cerrar la base de confianza antes de abrir la beta cerrada y el piloto con design partners.
