# v0.0.12 - Cierre del perímetro y acceso administrativo

Este documento describe únicamente la versión en curso. Las versiones publicadas
están en [`releases.md`](releases.md) y el roadmap está en
[`next_releases.md`](next_releases.md).

## Objetivo

Cerrar la preparación técnica de `https://assermetry.com` como entorno
controlado. Bajo la regla mTLS general temporal, los usuarios previamente
provisionados deben completar el acceso mediante OIDC; las rutas
administrativas de Keycloak deben mantener su regla mTLS permanente; y el lock
de mantenimiento debe poder cerrar todo el hostname en un solo paso.

La versión no habilita autorregistro ni acceso público anónimo. El origen de
Hetzner solo acepta HTTPS procedente de Cloudflare y conserva cerrados el resto
de puertos públicos de aplicación.

La regla mTLS general temporal para las rutas no administrativas se conserva en
`v0.0.12` y `v0.0.13`. Su retirada controlada forma parte de `v0.0.14`.

## Estado de la versión

**Cerrada.** Las fases 0 a 7 están completadas y la línea base estable quedó
registrada después de superar las pruebas de cierre.

Configuración vigente:

| Ámbito | Estado |
| --- | --- |
| Local | `https://localhost:7443` mediante `overlays/local` |
| Dominio | `https://assermetry.com`, proxificado por Cloudflare |
| Origen Hetzner | `TCP/443` permitido solo desde las 22 redes verificadas de Cloudflare; `80` y `6443` cerrados |
| Cloudflare | Cinco reglas ocupadas; lock en posición 1 con estado selectivo, mTLS administrativo y mTLS general temporal activos |
| Objetivo de cierre | OIDC de usuario validado tras el mTLS general temporal, mTLS administrativo permanente y lock disponible como pausa general |

Contrato público:

```text
https://assermetry.com/          -> frontend
https://assermetry.com/backend   -> Gateway
https://assermetry.com/auth      -> Keycloak
```

Identidad OIDC:

```text
Realm:          TrustNews
Display name:   Assermetry
Cliente web:    TrustNewsWeb
Cliente API:    TrustNewsApi
Issuer:         https://assermetry.com/auth/realms/TrustNews
```

## Tabla de fases

| Fase | Estado | Objetivo | Resultado actual |
| --- | --- | --- | --- |
| 0 | Cerrada | Inventariar el sistema estable y fijar una línea base recuperable | Despliegue, datos, dependencias y flujos principales inventariados y comprobados |
| 1 | Cerrada | Preparar aplicación, OIDC, manifests y overlays para el dominio sin activarlo | Configuración local, `prod` y `prod-domain` separada y validada |
| 2 | Cerrada | Registrar el dominio, delegar DNS y asegurar el perímetro inicial | Dominio y Cloudflare configurados; origen todavía filtrado |
| 3 | Cerrada | Proteger temporalmente el dominio con certificado cliente durante la preparación | Certificado individual y regla mTLS general emitidos, instalados y probados |
| 4 | Cerrada | Instalar TLS válido en el origen antes de permitir tráfico HTTPS | Cloudflare Origin CA instalado, validado y con renovación controlada |
| 5 | Cerrada | Implantar protecciones permanentes, límites y observabilidad | WAF, rate limit, límites de petición, logs y persistencia comprobados |
| 6 | Cerrada | Activar la configuración definitiva del dominio manteniendo el origen cerrado | Keycloak, Gateway, frontend e Ingress alineados con `assermetry.com` |
| 7 | Cerrada | Cerrar el perímetro y validar OIDC conservando el mTLS general temporal hasta `v0.0.14` | Pruebas finales superadas y línea base estable registrada |

## Detalle de las fases

### Fase 0 - Inventario y línea base

**Objetivo**

Identificar una versión recuperable del despliegue de Hetzner y comprobar su
funcionamiento antes de modificar manifests, DNS o firewall.

**Hecho**

- Se inventariaron imágenes, manifests, PVC, secretos, contrato, categorías,
  DNS y reglas de firewall.
- Se identificaron el commit y los artefactos de la versión estable.
- Se comprobaron por túnel SSH el frontend, la autenticación, los modos Light y
  Blockchain, colas, workers, IPFS, validadores, contrato y categorías.
- Se registró una línea base de pods, reinicios, disco, latencias y errores
  conocidos.

### Fase 1 - Adaptación de aplicación y manifests

**Objetivo**

Preparar la configuración de `assermetry.com` sin alterar el acceso activo por
`localhost` ni introducir valores productivos en las bases comunes.

**Hecho**

- Los overlays `local` y `prod` conservan `localhost`; `prod-domain`
  contiene exclusivamente la configuración del dominio.
- Gateway separa el issuer público de la URL interna de JWKS.
- Keycloak, Gateway e Ingress disponen de configuraciones coherentes para el
  dominio definitivo.
- `TrustNewsApi` permanece confidencial, con service account y secreto fuera
  del repositorio.
- Swagger, Redoc y OpenAPI están desactivados en producción.
- El frontend conserva rutas relativas `/backend` y `/auth`.
- Los renderizados y los flujos local y productivo por túnel quedaron
  validados sin activar prematuramente `prod-domain`.

### Fase 2 - Dominio, Cloudflare y DNS

**Objetivo**

Registrar `assermetry.com`, delegar su DNS a Cloudflare y configurar el
perímetro externo sin exponer todavía el origen.

**Hecho**

- El dominio quedó registrado con renovación automática, bloqueo de
  transferencia, privacidad de contacto y 2FA en registrador y Cloudflare.
- El DNS se delegó a Cloudflare y el registro raíz quedó proxificado hacia
  Hetzner; no se publicaron `www` ni servicios de correo.
- Cloudflare usa TLS `Full (strict)`, HTTPS obligatorio, TLS mínimo 1.2 y
  TLS 1.3.
- Los resolvers públicos devuelven direcciones de Cloudflare, no la IP directa
  del origen.
- Hetzner mantuvo `80/tcp` y `443/tcp` filtrados durante esta fase.
- SSH permanece en `2222/tcp`, solo con clave pública, sin acceso root ni
  autenticación por contraseña.

### Fase 3 - Acceso privado temporal por certificado cliente

**Objetivo**

Impedir el acceso al dominio durante la preparación mediante una regla mTLS
general y certificados individuales por dispositivo.

**Hecho**

- Se emitió un certificado cliente individual con la CA gestionada de
  Cloudflare; la clave privada se generó y conservó fuera de Git, Kubernetes,
  Hetzner y Cloudflare.
- El certificado y la clave se validaron, se empaquetaron en PKCS#12 cifrado y
  se importaron en el dispositivo autorizado.
- Cloudflare asoció mTLS al hostname y la regla temporal cubre `/`, `/auth`
  y `/backend`.
- Las pruebas sin certificado fueron bloqueadas y las realizadas con el
  certificado válido superaron el control mTLS.
- Se comprobó la desactivación y reactivación de la regla como rollback.
- No se ejecutó una revocación real ni se emitió un reemplazo en esta fase; la
  prueba de revocación administrativa se traslada a `v0.0.14`, durante la
  retirada controlada del mTLS general temporal.

### Fase 4 - TLS del origen

**Objetivo**

Instalar un certificado de servidor válido para el salto
Cloudflare-Traefik antes de permitir tráfico HTTPS hacia Hetzner.

**Hecho**

- Se emitió un Cloudflare Origin CA cuyo SAN incluye `assermetry.com`.
- Certificado y clave quedaron instalados manualmente en
  `kube-system/trustnews-origin-tls`, fuera de los overlays y del repositorio.
- `TLSStore/default` referencia el Secret productivo y Traefik presenta el
  certificado correcto.
- La pareja criptográfica, cadena, hostname, SNI y vigencia se validaron por
  túnel sin usar `-k`.
- Frontend, Gateway y discovery OIDC siguieron operativos.
- Kind conserva su certificado local y no depende del material productivo.
- La caducidad está inventariada, con alerta previa y material anterior
  disponible para rollback. La renovación es manual.

### Fase 5 - WAF, restricciones y observabilidad

**Objetivo**

Dejar activas y observables las protecciones que deben sobrevivir a la retirada
del mTLS general.

**Hecho**

- Cloudflare mantiene una regla mTLS permanente para
  `/auth/admin`, `/auth/admin/*`, `/auth/realms/master` y
  `/auth/realms/master/*`.
- La Free Managed Ruleset, las reglas personalizadas para recursos sensibles y
  métodos no permitidos, y el rate limit de los endpoints de mayor coste
  quedaron activados y probados.
- Traefik y Gateway aplican un límite coherente de 5 MiB por petición.
- OpenAPI permanece inaccesible en producción y los servicios internos no
  tienen Ingress ni NodePort.
- Gateway y Traefik generan logs estructurados sin tokens, query strings ni
  cuerpos. Fluent Bit incluye `kube-system`.
- Loki y Grafana tienen almacenamiento persistente, probes y conservaron datos
  y datasource después del reemplazo de sus pods.
- Se correlacionaron rechazos controlados `401`, `403`, `429` y `500`
  en el borde, Gateway y Loki.
- La medición de cierre de la Fase 5 mostró 29 de 29 pods preparados, cero
  reinicios y nueve PVC `Bound`. El nodo estaba al 5 % de CPU, 78 % de memoria
  y 56 % de disco;
  la memoria queda bajo vigilancia.

### Fase 6 - Despliegue definitivo todavía cerrado

**Objetivo**

Activar coordinadamente `prod-domain` en K3s, alinear OIDC e Ingress con el
dominio definitivo y validar la aplicación sin abrir el origen a Internet.

**Hecho**

- `infra-prod` usa el overlay de dominio de Keycloak y
  `apis-frontend-prod` usa los overlays de dominio de Gateway e Ingress.
- El realm técnico sigue siendo `TrustNews`, muestra `Assermetry` y publica
  el issuer canónico.
- `TrustNewsWeb` usa las URLs, redirects, post-logout y Web Origin de
  `https://assermetry.com`.
- `TrustNewsApi` permanece confidencial, habilitado y con service account,
  sin modificar ni exponer su secreto.
- Los tres Ingress usan `host: assermetry.com` y el TLS productivo sigue
  referenciado mediante `trustnews-origin-tls`.
- Los 29 pods quedaron preparados, sin reinicios, y los nueve PVC permanecieron
  `Bound`.
- Frontend y discovery respondieron correctamente con validación TLS; Gateway
  rechazó sin credenciales y aceptó un JWT válido.
- OpenAPI devolvió `404` y los smoke tests Light y Blockchain se completaron.
- Se eliminó el valor por defecto no vacío de `ISSUE-002` y se confirmó que
  no coincidía con el secreto productivo.

### Fase 7 - Cierre del perímetro y acceso administrativo

**Objetivo**

Completar el cierre del perímetro y validar que los usuarios provisionados
acceden mediante OIDC después de superar la regla mTLS general temporal. Las
rutas administrativas conservan además su regla mTLS permanente y el lock de
Cloudflare mantiene un cierre general independiente.

**Hecho**

- Traefik usa `externalTrafficPolicy: Local` y solo confía las cabeceras
  reenviadas por las 22 redes oficiales de Cloudflare configuradas.
- Hetzner permite `TCP/443` exclusivamente desde esas redes. El acceso directo
  al origen en `443`, `80` y `6443` permanece bloqueado.
- Cloudflare tiene ocupadas las cinco reglas personalizadas: lock general,
  mTLS administrativo, mTLS general temporal, bloqueo de recursos no públicos
  y bloqueo de métodos inesperados, en ese orden.
- La regla mTLS administrativa permanente está activa sobre las rutas de
  administración de Keycloak.
- La regla mTLS general temporal sigue activa y su retirada controlada queda
  programada para `v0.0.14`.
- Bajo el acceso privado se comprobaron frontend, discovery, login, refresh,
  logout, roles, client credentials, Gateway con y sin JWT y los modos Light y
  Blockchain.
- La revisión posterior mantuvo todos los workloads disponibles, cero
  reinicios y el nodo `Ready`. El uso de memoria cercano al 80 % y el warning
  `DNSConfigForming` quedan como observaciones no bloqueantes.
- El lock de mantenimiento está configurado en primera posición y cubre todo
  `assermetry.com`. Con sesiones válidas de usuario y administrador, su
  activación produjo `403` en ambos accesos y los eventos se atribuyeron al
  lock. Al deshabilitarlo, ambos accesos volvieron a `200`; el estado operativo
  final quedó deshabilitado y las reglas permanentes continuaron activas.
- El pipeline `PROFILE=infra-prod` del commit `8bdaa6f` completó la
  reconciliación automatizada del realm `TrustNews` y del cliente
  `TrustNewsWeb`, obtuvo `keycloak_web_alignment=PASS` y confirmó el issuer
  canónico `https://assermetry.com/auth/realms/TrustNews`.
- Se confirmó la convivencia y atribución de las reglas de Cloudflare: una
  ruta administrativa sin certificado fue bloqueada por el mTLS
  administrativo permanente y una ruta no administrativa por el mTLS general
  temporal. El lock conserva la prioridad y el bloqueo general ya probado.
  Para `v0.0.14`, el rollback consiste en reactivar únicamente la regla
  temporal, manteniendo la asociación mTLS y la regla administrativa.
- Desde la red habitual y con un certificado cliente válido se comprobaron el
  frontend, el discovery OIDC con el issuer canónico, el inicio de sesión, la
  persistencia de la sesión tras recargar, el logout con retorno al login y los
  flujos Light y Blockchain.
- Con el certificado cliente válido, Gateway rechazó
  `/backend/auth/is-admin` sin JWT mediante `403 Not authenticated`; tras
  renovar el token, aceptó el JWT y confirmó el rol `trust-admin` del usuario.
- Las rutas administrativas quedaron verificadas en las dos capas: sin
  certificado fueron bloqueadas por la regla mTLS administrativa; con un
  certificado válido, la consola de Keycloak respondió, mientras que su API
  administrativa sin token mantuvo el rechazo `401 Unauthorized`. El
  certificado no elude la autenticación de Keycloak.
- La línea base estable de cierre, capturada el `2026-08-21T15:32:55Z` y
  vinculada al pipeline verificado del commit `8bdaa6f`, registró el nodo
  `Ready`, 20 Deployments, siete StatefulSets y dos DaemonSets disponibles,
  29 pods preparados sin reinicios y nueve PVC `Bound`. Los tres Ingress
  esperados permanecían tras Traefik, único Service `LoadBalancer`; el resto de
  servicios eran internos.
- En esa captura el nodo consumía un 5 % de CPU y un 76 % de memoria, el disco
  raíz estaba al 58 %, y Loki y Grafana estaban disponibles con sus PVC
  enlazados y sus rollouts completados. `DNSConfigForming` y un
  `FailedScheduling` transitorio de Loki por presión de CPU y memoria quedan
  como observaciones no bloqueantes; Loki terminó preparado y sin reinicios.
- La evidencia conservada de la mitigación de `ISSUE-001` mantiene tres
  aserciones por tres validadores, con nueve solicitudes y nueve respuestas
  LIGHT.

**Incidencia conocida no bloqueante**

[`ISSUE-001`](issues.md#issue-001---carrera-de-inicializacion-en-la-cache-de-validadores-light)
permanece mitigada: el refresco manual recupera los tres validadores LIGHT,
pero la carrera de inicialización todavía puede repetirse tras un despliegue
simultáneo. La Fase 7 debe conservar evidencia de la mitigación y del smoke
test de nueve solicitudes y nueve respuestas. La corrección sistemática y sus
pruebas de concurrencia pertenecen a `v0.0.13`, coherentemente con que la
corrección funcional está fuera del alcance de esta versión.

## Criterio de cierre

La versión se cierra cuando un usuario provisionado completa los flujos OIDC
con un certificado cliente temporal, Gateway rechaza las peticiones protegidas
sin JWT, la administración exige su regla mTLS permanente y la autenticación de
Keycloak, el origen solo admite Cloudflare y el lock bloquea toda la plataforma.
La regla mTLS general permanece activa y su retirada, junto con la prueba de
revocación de un certificado administrativo desechable, se reserva para
`v0.0.14`. `ISSUE-001` puede permanecer mitigada y registrada al cierre; debe
resolverse en `v0.0.13` antes de superar la regresión y las demos repetibles.

## Fuera de alcance

- Pruebas sistemáticas y corrección funcional de GUI y API.
- Entrega de credenciales persistentes a clientes.
- Pilotos con datos reales o compromisos de servicio.
- Revocación real de un certificado administrativo; su prueba controlada se
  realizará en `v0.0.14` con un certificado desechable y otro de respaldo.
- Hardening completo, backups, restauración y alta disponibilidad.
- Decisión GO/NO-GO de producción y apertura pública.
