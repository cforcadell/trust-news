# v0.0.13 - Estabilización funcional y demo repetible

Este documento describe únicamente la versión en curso. Las versiones publicadas
están en [`releases.md`](releases.md) y el roadmap está en
[`next_releases.md`](next_releases.md).

## Estado de la versión

**En curso.**

**Punto de trabajo actual:** 11 de [`working.md`](working.md), iniciado. Los
puntos anteriores se consideran OK.

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

- Crear un conjunto fijo de datos sintéticos sin información de clientes.
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
