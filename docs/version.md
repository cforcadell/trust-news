# Versiones del despliegue Kubernetes

Este documento describe el objetivo, alcance, dependencias, orden de despliegue
y criterios de aceptacion de cada version de la plataforma Kubernetes de
Assermetry. Los comandos operativos se mantienen en:

- [`k8s-common.md`](deploy/k8s-common.md): configuracion compartida.
- [`skaffold-local.md`](deploy/skaffold-local.md): despliegue local con `kind`.
- [`skaffold-server.md`](deploy/skaffold-server.md): despliegue productivo en Hetzner.
- [`issues.md`](issues.md): incidencias detectadas y propuestas de mejora por version.

---

## v0.0.12 - Cierre del perimetro y acceso administrativo

### Objetivo

Cerrar la preparacion tecnica del entorno controlado de Hetzner en
`https://assermetry.com`, conservando el despliegue local y sin autoservicio ni
registro publico de usuarios.

La version termina con la **Fase 8 - Cierre del perimetro y acceso
administrativo**. El estado objetivo permite que un usuario previamente
provisionado acceda mediante login OIDC sin certificado cliente, mantiene mTLS
solo para la administracion de Keycloak y utiliza el lock de Cloudflare para
cerrar temporalmente todo el hostname. Las pruebas sistematicas de GUI y API,
la correccion funcional y los ensayos de demo comienzan en `v0.0.13`.

### Estado actual

La version `v0.0.12` ha cerrado la **Fase 0 - Inventario y linea base**, la
**Fase 1 - Adaptacion de aplicacion y manifests** y la **Fase 2 - Dominio,
Cloudflare y DNS**. En la Fase 2 se completaron la configuracion tecnica, las
comprobaciones externas y la verificacion del 2FA en Porkbun y Cloudflare. La
**Fase 3 - Acceso privado temporal por certificado cliente** esta cerrada: la emision,
instalacion y validacion funcional del certificado, el gate mTLS y su rollback
estan completados. Por decision de alcance no se ejecutaron una revocacion real
ni un certificado de reemplazo; se mantiene el certificado probado durante el
periodo privado y queda documentado el procedimiento ante incidentes. La
**Fase 4 - TLS del origen antes de abrir 443** esta cerrada. El inventario de
K3s se ha completado y el certificado Cloudflare Origin CA para
`assermetry.com` esta instalado en `kube-system/trustnews-origin-tls`. Traefik
lo presenta correctamente y la cadena, el hostname y el SNI se validaron por
tunel con la raiz Origin CA. Las pruebas funcionales mantienen frontend `200`,
discovery OIDC `200` y Gateway alcanzable. El origen permanece filtrado en
`80/tcp` y `443/tcp`. La caducidad esta inventariada y dispone de una alerta
operativa. La **Fase 5 - WAF, restricciones permanentes y observabilidad** esta
cerrada desde el 2026-08-18: Loki y Grafana conservaron sus datos tras
reemplazar los pods, Grafana mantuvo el datasource Loki, los rechazos
controlados `401`, `403`, `429` y `500` quedaron correlacionados en el punto de
control correspondiente y la muestra final mantuvo 29 de 29 pods preparados,
9 de 9 PVC `Bound` y cero reinicios. El nodo estaba al 5% de CPU, 78% de
memoria y 56% de disco; la memoria sigue por debajo del aviso del 80%, pero
requiere vigilancia durante los siguientes cambios operativos. La **Fase 6 -
Despliegue definitivo todavia cerrado** esta cerrada. El pipeline GitLab `#2770049730`
sobre el commit `4a7e9185` completo `build`, el gate TLS, `infra-prod` y el
bootstrap de MongoDB; el rollback no se ejecuto. Tras dos intentos de
diagnostico, el job sobre `dc81ca9` actualizo idempotentemente el atributo del
realm y confirmo el issuer
`https://assermetry.com/auth/realms/TrustNews`. El gate de infraestructura esta
cerrado. El 2026-08-19 se alineo `TrustNewsWeb` mediante `kcadm` dentro del pod,
se establecio el display name `Assermetry`, se verifico el issuer definitivo y
se confirmo que `TrustNewsApi` conserva su configuracion confidencial y su
service account sin cambios. La evidencia posterior al despliegue de
`apis-frontend-prod` muestra los 29 pods preparados, cero reinicios, los nueve
PVC `Bound` y los tres Ingress con `host: assermetry.com`. Por tunel, el
frontend devolvio `200` y discovery publico el issuer definitivo. La repeticion
desde Windows, con `--cacert` y sin `-k`, acepto la cadena TLS; Gateway devolvio
`403` sin credenciales y los tres endpoints OpenAPI devolvieron `404`. El
operador valido despues el flujo web y los smoke tests Light y Blockchain.
`TrustNewsApi` emitio un token y Gateway acepto el JWT; `/orders/list` devolvio
`404` porque no habia noticias para el service account. Con un token nuevo,
`/auth/is-admin` devolvio `HTTP 200` e `is_admin:false`, cerrando el gate API.
La limpieza local esta completada. `ISSUE-002` esta resuelto: el valor por
defecto no vacio se elimino y el operador confirmo que no coincide con el
secret productivo, por lo que no requiere rotacion productiva. La posible
revision de una credencial historica de tests queda como recomendacion no
bloqueante. La **Fase 8 - Cierre del acceso privado**
esta en curso: sus pasos 8.1 a 8.5 estan completados y la prueba desde una red
alternativa permanece pendiente. Hetzner permite ahora `TCP/443` exclusivamente
desde las 22 redes verificadas de Cloudflare; los accesos directos a `443`, `80`
y `6443` quedaron bloqueados. El lock de mantenimiento de Cloudflare esta
activo en primera posicion y bloquea el hostname completo mientras no se prueba.
`v0.0.12` se cerrara al retirar de forma controlada la regla mTLS general,
validar el acceso OIDC de usuario sin certificado, probar la proteccion mTLS
administrativa y su revocacion, comprobar el lock y repetir desde una red
alternativa.
Las pruebas sistematicas de GUI y API, el hardening, los backups, la
recuperacion y cualquier decision de produccion dejan de pertenecer a esta
version.

Configuracion activa:

```text
Local:           https://localhost:7443
Hetzner/origen:  TCP/443 accesible solo desde las 22 redes de Cloudflare
Cloudflare hoy: https://assermetry.com (lock, mTLS general temporal y mTLS administrativo activos)
Objetivo Fase 8: acceso OIDC de usuario sin certificado; mTLS solo administrativo; lock disponible
```

Los perfiles locales continúan usando `overlays/local`. `infra-prod` referencia
el overlay `prod-domain` de Keycloak y ya fue desplegado por el pipeline
`#2770049730`. `apis-frontend-prod` referencia los overlays `prod-domain` de
Gateway e Ingress y ya fue aplicado; los tres Ingress activos usan
`host: assermetry.com`. La aceptacion funcional y la limpieza local estan
completadas. `ISSUE-002` esta resuelto y no afecta al secret productivo. La
revision historica recomendada no bloquea el cierre de la Fase 8.

### Contrato de acceso controlado de la version

```text
https://assermetry.com/          -> frontend
https://assermetry.com/backend   -> Gateway
https://assermetry.com/auth      -> Keycloak
```

Identidades OIDC que se mantienen:

```text
Realm:          TrustNews
Display name:   Assermetry
Cliente web:    TrustNewsWeb
Cliente API:    TrustNewsApi
Issuer:         https://assermetry.com/auth/realms/TrustNews
```

No se utilizara un dominio provisional. Tampoco se renombrara el realm tecnico,
porque hacerlo cambiaria el issuer, las URLs OIDC y la configuracion de todos
los clientes.

### Arquitectura objetivo de acceso

```text
Usuario provisionado                 Administrador
        |                                  |
        | HTTPS sin certificado cliente    | HTTPS + certificado mTLS administrativo
        v                                  v
Cloudflare WAF + maintenance lock     Regla mTLS administrativa permanente
        |                                  |
        +----------------+-----------------+
                         | HTTPS Full (strict)
                         v
        Firewall Hetzner: 443 solo desde rangos de Cloudflare
                         |
                         v
                    Traefik (K3s)
                         +-- /         -> frontend + login OIDC
                         +-- /backend  -> Gateway + validacion JWT
                         +-- /auth     -> Keycloak
```

Hay dos certificados con finalidades diferentes:

- El certificado TLS del origen autentica `assermetry.com` y cifra la conexion
  entre Cloudflare y Traefik.
- El certificado cliente mTLS administrativo, emitido por la CA gestionada de
  Cloudflare, protege `/auth/admin` y `/auth/realms/master`. No se entrega a
  usuarios ni clientes para acceder a los flujos funcionales.

Tener solo el certificado TLS del servidor no autoriza a usar la aplicacion. El
acceso funcional se controla mediante OIDC, JWT, roles y asociacion de cliente
en servidor; el mTLS se reserva para la administracion.

### Regla de oro de seguridad

- Los usuarios previamente provisionados acceden sin certificado cliente y se
  autentican mediante OIDC. Gateway debe rechazar las APIs protegidas cuando no
  existe un token valido.
- El mTLS permanece obligatorio en `/auth/admin`, `/auth/admin/*`,
  `/auth/realms/master` y `/auth/realms/master/*`.
- El lock de mantenimiento es independiente de OIDC y mTLS administrativo:
  cuando esta activo bloquea todo `assermetry.com`, incluidos usuarios y
  administradores validos.
- `443/tcp` no se abrira al trafico publico general dentro de `v0.0.12`.
  Hetzner solo aceptara los rangos oficiales vigentes de Cloudflare y el origen
  no sera accesible directamente.
- Si aparece una incidencia durante una demo, el cierre inmediato consiste en
  reactivar el lock sin cambiar DNS, Kubernetes, Keycloak ni certificados. Para
  una pausa prolongada se retirara la regla inbound de `443/tcp`.

### Compatibilidad con el despliegue local

La version debe conservar estas reglas:

- `k8s/ingress/base` permanece sin hostname y sin secretos dependientes del
  entorno.
- `k8s/ingress/overlays/local` mantiene el certificado local y `host: localhost` para
  `https://localhost:7443`.
- `k8s/ingress/overlays/prod` mantiene `localhost` para el acceso cerrado por
  tunel y no genera el Secret TLS.
- `k8s/ingress/overlays/prod-domain` hereda de `prod` y sustituye unicamente el
  host por `assermetry.com`; permanece inactivo hasta la fase de dominio.
- El frontend conserva URLs relativas (`/backend` y `/auth`) para funcionar en
  local y produccion.
- Los valores de Keycloak y del issuer se parametrizan por overlay; no se
  introducen valores productivos en `base`.

### Revision critica del plan inicial

El plan de partida es valido como objetivo, con las siguientes correcciones y
controles:

1. No se debe confundir TLS con control de acceso. El certificado del origen
   protege el salto Cloudflare-Traefik; OIDC/JWT autoriza usuarios y el mTLS
   administrativo protege las rutas de administracion.
2. El issuer externo y la URL interna de JWKS tienen responsabilidades
   distintas. El Gateway valida `iss` contra la URL publica, pero puede obtener
   las claves por la red interna de Kubernetes.
3. No se debe añadir `:443` al issuer canonico. Keycloak y Gateway deben producir
   y validar exactamente la misma cadena sin el puerto HTTPS implicito.
4. El DNS proxificado, WAF, lock y regla mTLS administrativa deben configurarse
   antes de permitir que Cloudflare alcance el origen. En el plan Free se usan
   certificados emitidos por la CA gestionada de Cloudflare.
5. El firewall no puede abrir `443/tcp` a `0.0.0.0/0`. Solo aceptara los rangos
   oficiales vigentes de Cloudflare. Esos rangos requieren un procedimiento de
   actualizacion.
6. Bloquear `/auth/admin/*` no basta por si solo: tambien se debe bloquear el
   realm `master`, la documentacion del Gateway y cualquier servicio operativo.
7. Los cambios de seguridad e issuer deben probarse primero por tunel y luego en
   el dominio real. Los flujos de usuario se prueban sin certificado; las rutas
   administrativas, con y sin certificado administrativo.
8. Cada demo necesita un cierre de un solo paso: reactivar el lock de
   mantenimiento sin cambiar DNS, Kubernetes, Keycloak ni certificados.

### Plan ordenado de despliegue

Cada fase es un gate. No se inicia la siguiente hasta cumplir sus criterios de
salida.

#### Matriz de despliegue por fase

| Fase | Estado | Alcance breve | Kubernetes local | Kubernetes Hetzner | Cambio externo |
| --- | --- | --- | --- | --- | --- |
| 0 | **Cerrada** | Inventariar el sistema estable y fijar una linea base funcional y recuperable | No | No; se prueba lo ya desplegado | No |
| 1 | **Cerrada** | Preparar aplicacion, OIDC, manifests y overlays para el dominio sin activarlo | **OK** | **OK**; se valido `prod` y `prod-domain` no se activo durante esta fase | No |
| 2 | **Cerrada** | Registrar el dominio, delegar DNS a Cloudflare y asegurar el perimetro inicial | No | No | Dominio, Cloudflare y DNS |
| 3 | **Cerrada** | Proteger temporalmente todo el dominio con certificado cliente durante la preparacion | No | No | Gate mTLS general probado como control transitorio; no es el modelo final de usuario |
| 4 | **Cerrada** | Instalar y rotar manualmente un certificado Cloudflare Origin CA sin abrir puertos publicos | Render validado; Secret local y `localhost` intactos | Origin CA instalado y validado por tunel | Certificado emitido; origen filtrado en 80/443 y alerta activa |
| 5 | **Cerrada** | Implantar protecciones permanentes, limites, registros y alertas antes de las demos | Validada | Validada | WAF, rate limits y alertas activos y comprobados |
| 6 | **Cerrada** | Activar la configuracion definitiva del dominio en K3s manteniendo el origen cerrado | Render validado; no desplegar en local | Funcionalidad y limpieza aceptadas; valor por defecto de tests eliminado y sin coincidencia con produccion | No |
| 8 | **En curso (pasos 8.1 a 8.5 completados; 8.6 pendiente)** | Activar acceso OIDC de usuario y mantener mTLS solo administrativo | No | `443/tcp` solo desde Cloudflare; Gateway protegido por JWT | Retirar mTLS general, probar administracion mTLS, lock y red alternativa |

**Hito actual para versionado:** `infra-prod`, los clientes OIDC y el despliegue
de `apis-frontend-prod` estan aplicados. La muestra posterior mantiene 29 de 29
pods preparados, cero reinicios, nueve PVC `Bound` y los tres Ingress en
`assermetry.com`. Desde Windows, frontend y discovery pasaron sin `-k` usando
la raiz Origin CA; Gateway rechazo sin credenciales con `403` y los tres
endpoints OpenAPI devolvieron `404`. El operador confirmo despues login,
refresh, logout, redirects y Web Origins, junto con los smoke tests Light y
Blockchain. `TrustNewsApi` emitio un token valido y Gateway acepto el JWT; la
ruta de listado devolvio `404` por ausencia de noticias para ese service
account. La repeticion con un token nuevo obtuvo `HTTP 200` e
`is_admin:false` en `/backend/auth/is-admin`. El primer `403` observado en esa
ruta se produjo con la variable del token vacia y no se clasifica como fallo.
La entrada temporal de `hosts`, la raiz importada, el tunel y las variables se
retiraron. El operador confirmo que el valor de `ISSUE-002` no coincide con el
secret productivo de `TrustNewsApi`; no se requiere rotacion productiva por
este hallazgo. La copia de trabajo elimina ya el valor no vacio y `ISSUE-002`
queda resuelto. Determinar si el valor historico pertenecio a una credencial de
tests activa es una recomendacion de seguridad independiente y no bloquea la
Fase 8. El firewall permite `443/tcp` exclusivamente desde las redes de
Cloudflare; no esta abierto al trafico general ni al acceso directo al origen.

`No` significa que esa fase no debe provocar un despliegue en ese cluster. Las
consultas, renderizados y pruebas indicadas siguen siendo obligatorios.

#### Fase 0 - Inventario y linea base (cerrada)

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar nada nuevo; validar la instalacion existente
  por tunel SSH antes de tocar manifests, DNS o firewall.

**Pruebas**

- Local: ninguna prueba de despliegue; comprobar unicamente que el commit,
  imagenes y manifests de la version estable estan identificados.
- Hetzner por tunel: probar frontend, login, refresh y logout; una orden Light y
  una Blockchain; colas y workers; lectura y escritura en IPFS; validadores;
  contrato y categorias.
- Registrar pods, reinicios, uso de disco, latencias y errores conocidos como
  linea base.

1. Confirmar que la version actualmente desplegada en Hetzner es recuperable.
2. Inventariar imagenes, manifests, PVC, secrets, contrato, categorias, DNS y
   reglas actuales de firewall.
3. Ejecutar pruebas funcionales por el tunel SSH existente con solo `2222/tcp`
   accesible.
4. Registrar metricas y errores conocidos para poder distinguir regresiones.

Criterio de salida: frontend, autenticacion, modos Light y Blockchain, colas,
IPFS y validadores funcionan antes de introducir el dominio.

#### Fase 1 - Adaptacion de aplicacion y manifests (cerrada)

Finalidad: preparar y verificar la configuracion que necesitara el dominio
definitivo sin cambiar todavia la identidad OIDC del despliegue activo. En esta
fase `prod` sigue representando el acceso cerrado por
`https://localhost:9443`; `prod-domain` representa la configuracion futura de
`https://assermetry.com`.

**Estado**

- Kubernetes local: **OK**.
- Kubernetes Hetzner: **OK**.
- Estado global de la fase: **cerrada** tras completar el despliegue compatible
  con `prod` y su validacion por tunel en Hetzner.

**Despliegue**

- Kubernetes local: **OK**. Se han desplegado los perfiles locales sin
  sustituirlos por `prod-domain`.
- Kubernetes Hetzner: si, despues de superar local. Desplegar por tunel solo el
  Gateway, imagenes y manifests compatibles con la configuracion activa `prod`.
  No desplegar blockchain si no ha cambiado.
- Solo renderizar `prod-domain`; no referenciarlo desde Skaffold ni modificar
  todavia los clientes OIDC activos.

**Pruebas**

- Local: renderizar `local`, `prod` y `prod-domain`; desplegar `local`; comprobar
  frontend, login, refresh, logout, una orden Light y una Blockchain, workers,
  IPFS y validadores. `/backend/docs` debe estar disponible en local.
- Hetzner por tunel: repetir el smoke funcional con `https://localhost:9443`;
  comprobar que Keycloak y Gateway usan exactamente el issuer de `localhost`,
  que el Gateway obtiene el JWKS por la red interna y que `/backend/docs`,
  `/backend/redoc` y `/backend/openapi.json` responden `404`.
- Estatica: confirmar que `prod-domain` genera `assermetry.com`, que `prod` sigue
  generando `localhost` y que ningun secreto aparece en el repositorio.

1. Separar en el Gateway la identidad publica del emisor y la obtencion interna
   de sus claves:

   ```dotenv
   KEYCLOAK_ISSUER_URL=https://assermetry.com/auth/realms/TrustNews
   KEYCLOAK_JWKS_URL=http://keycloak.infra.svc.cluster.local:8080/auth/realms/TrustNews/protocol/openid-connect/certs
   ```

   El primer valor se configura en `prod-domain`; el segundo puede ser comun a
   todos los entornos Kubernetes. El Gateway valida `iss` con la URL publica,
   pero no necesita salir por Cloudflare para descargar el JWKS.

2. Evitar que la configuracion productiva dependa de `localhost`, cabeceras
   `Host` forzadas o construcciones del issuer mediante hostname, puerto y path
   separados. Se conserva `localhost` como fallback local y como valor explicito
   de los overlays `local` y `prod` mientras sigan siendo los perfiles activos.
3. Preparar Keycloak en `overlays/prod-domain` con la URL publica definitiva y
   proxy headers, sin alterar el hostname ni el issuer del `prod` activo. El
   nombre visible `Assermetry` es un atributo del realm almacenado en PostgreSQL,
   no una variable del overlay; dejar preparado su cambio para aplicarlo junto
   con los clientes OIDC en la Fase 6.
4. Dejar preparados para la activacion coordinada de la Fase 6 los valores de
   `TrustNewsWeb`:

   ```text
   Root URL:                https://assermetry.com
   Home URL:                https://assermetry.com/
   Valid redirect URIs:     https://assermetry.com/*
   Valid post logout URIs:  https://assermetry.com/*
   Web Origins:             https://assermetry.com
   ```

   No aplicar todavia estos valores como los unicos permitidos al cliente
   activo, porque se romperia el login por `https://localhost:9443`. No usar
   `*` en produccion.
5. Mantener `TrustNewsApi` confidencial, con service account y secret fuera del
   repositorio.
6. Parametrizar Swagger, Redoc y OpenAPI y mantenerlos desactivados en los
   overlays productivos, incluido el acceso temporal por tunel.
7. Mantener los parches de dominio en `k8s/ingress/overlays/prod-domain` con
   `host: assermetry.com`, conservando `websecure`, TLS y el middleware que
   elimina `/backend`; no conectarlos aun a Skaffold.
8. Mantener `/auth/admin/*`, `/auth/realms/master/*` y el admin-service fuera de
   la exposicion publica.

Criterio de salida: el despliegue activo continua funcionando por tunel con
`localhost:9443`; `local` y `prod` siguen renderizando `localhost`; los
`prod-domain` generan de forma aislada y coherente el issuer, los hosts y la
configuracion futura de `assermetry.com`; la URL JWKS es interna; la
documentacion del Gateway no existe en los overlays productivos; ningun recurso
de dominio esta referenciado por Skaffold ni activo en el cluster.

#### Fase 2 - Dominio, Cloudflare y DNS (cerrada)

**Estado**

- Estado tecnico: **OK**.
- Estado formal: **cerrada**; el 2FA esta activo y verificado en las cuentas de
  Porkbun y Cloudflare.
- Kubernetes local y Hetzner no se han redesplegado.
- El firewall de Hetzner esta aplicado al servidor y no contiene reglas de
  entrada para `80/tcp` ni `443/tcp`. Solo permite `2222/tcp` e ICMP; el
  trafico saliente permanece permitido.
- SSH en `2222/tcp` usa exclusivamente clave publica. El acceso root, las
  contraseñas y la autenticacion interactiva estan desactivados.
- La Fase 3 no se ha iniciado.

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar ni modificar el firewall.
- Externo: configurar registrador, Cloudflare y DNS; el origen debe continuar
  inaccesible desde Internet.

**Pruebas**

- Consultar los nameservers y el registro `A` desde al menos dos resolvers
  publicos y confirmar que el dominio devuelve direcciones de Cloudflare, no la
  IP directa de Hetzner.
- Verificar en Cloudflare proxy activo, `Full (strict)`, HTTPS obligatorio y TLS
  minimo 1.2.
- Confirmar desde una red externa que `80/tcp` y `443/tcp` del origen siguen
  cerrados; no se prueba todavia la aplicacion por el dominio.
- Verificar la configuracion efectiva de `sshd` y que `authorized_keys`
  contiene unicamente las claves previstas.

1. Registrar `assermetry.com` con renovacion automatica, bloqueo de transferencia
   y 2FA.
2. Delegar los nameservers a Cloudflare.
3. Crear el registro `A` de `@` hacia Hetzner con proxy activado.
4. Configurar TLS `Full (strict)`, HTTPS obligatorio y TLS minimo 1.2.
5. No publicar `www` en esta version salvo que se añada y pruebe expresamente la
   redireccion canonica.

**Resumen de pasos realizados**

1. Se registro `assermetry.com` en Porkbun y se verificaron la renovacion
   automatica, el bloqueo del dominio, la privacidad de contacto y DNSSEC
   desactivado. Tambien se verifico el 2FA activo en Porkbun y Cloudflare.
2. Se creo la zona `assermetry.com` en el plan Free de Cloudflare y se eliminaron
   los registros importados de aparcamiento, wildcard, `www` y correo de Porkbun.
3. Se creo un unico registro `A` para el dominio raiz hacia la IP publica de
   Hetzner, con proxy de Cloudflare activado y TTL automatico. No se publico
   `www` ni se configuro correo en esta version.
4. En Porkbun se sustituyeron los cuatro nameservers originales por los dos
   asignados por Cloudflare:

   ```text
   luke.ns.cloudflare.com
   rosemary.ns.cloudflare.com
   ```

5. Se verifico la delegacion desde el registro `.com` y mediante los resolvers
   publicos `1.1.1.1` y `8.8.8.8`. Ambos resolvieron el dominio a direcciones
   anycast de Cloudflare en lugar de publicar la IP de Hetzner.
6. Se configuro Cloudflare con modo personalizado `Full (strict)`, Universal SSL
   y certificado de respaldo activos, `Always Use HTTPS`, TLS minimo 1.2, TLS
   1.3 y `Automatic HTTPS Rewrites`. HSTS permanece desactivado hasta validar el
   servicio completo.
7. Se comprobo desde una red externa que una peticion HTTP recibe una redireccion
   `301` a HTTPS. Las pruebas con `nc` agotaron el tiempo de espera contra la
   IP directa de Hetzner en `80/tcp` y `443/tcp`; `nmap -Pn` confirmo ambos
   puertos como `filtered`.
8. Se verifico en Hetzner que el firewall esta completamente aplicado al unico
   servidor asociado. No existen reglas de entrada para `80/tcp` ni
   `443/tcp`; solo se permiten TCP `2222` e ICMP desde IPv4 e IPv6, y todo el
   trafico saliente permanece permitido.
9. `2222/tcp` permanece accesible desde cualquier IP porque el administrador no
   dispone de una IP publica fija. Se verifico la configuracion efectiva de
   OpenSSH: `PermitRootLogin no`, `PubkeyAuthentication yes`,
   `PasswordAuthentication no`, `KbdInteractiveAuthentication no` y
   `MaxAuthTries 6`. El usuario `sysadmin` tiene una sola clave ED25519 en
   `authorized_keys`, bajo control exclusivo del administrador.
10. No se probo la aplicacion mediante el dominio ni se abrio el origen. El
    certificado TLS del borde de Cloudflare no sustituye al certificado del
    origen, que se instalara en la Fase 4.

Criterio de salida: **cumplido**. DNS resuelve a Cloudflare, el origen sigue
filtrado en `80/tcp` y `443/tcp`, SSH solo admite la unica clave autorizada y
el 2FA esta activo en Porkbun y Cloudflare.

#### Fase 3 - Acceso privado temporal por certificado cliente (cerrada)

La implementacion se hara con **Cloudflare Application Security mTLS**,
compatible con el plan Free y con certificados emitidos por la CA gestionada de
Cloudflare. No se usara una CA privada propia ni Cloudflare Access mTLS, porque
esa modalidad requiere Zero Trust Enterprise.

**Estado**

- Emision, instalacion y prueba funcional del certificado
  `cforcadell-win11-01`: **completadas**.
- Asociacion mTLS del hostname y regla WAF temporal: **completadas y activas**.
- Cobertura con y sin certificado de `/`, `/auth` y `/backend`: **comprobada**.
- Desactivacion y reactivacion de la regla como rollback de un solo paso:
  **comprobada**, dejando la regla activa al finalizar.
- Revocacion real y certificado de reemplazo: **no ejecutados por decision de
  alcance**; se conserva el certificado probado mientras mTLS sea temporal.
- Kubernetes no se ha redesplegado y el origen continua cerrado en `80/tcp` y
  `443/tcp`.

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar ni abrir `443/tcp`.
- Externo: emitir un certificado cliente por tester, asociar
  `assermetry.com` a mTLS y crear una regla WAF que bloquee certificados
  ausentes o invalidos.

**Pruebas**

- Verificar cadena, fechas, identificador y presencia o ausencia de restricciones
  EKU en cada certificado; probar su importacion como PKCS#12, confirmar la
  aceptacion mTLS real y documentar el procedimiento de revocacion.
- Confirmar que la clave privada de cada tester se genera y conserva fuera de
  Git, Kubernetes, Hetzner y Cloudflare.
- Confirmar que mTLS esta asociado al hostname `assermetry.com` y que la regla
  WAF cubre todas las rutas, incluidas `/`, `/auth` y `/backend`, sin
  excepciones ni reglas bypass.
- Sin certificado, esperar bloqueo de Cloudflare. La regla tambien debe incluir
  expresamente el estado revocado para que un certificado revocado quede
  bloqueado si fuese necesario ejecutar ese procedimiento. Con un certificado
  valido se supera el gate mTLS, aunque el acceso a la aplicacion seguira
  fallando mientras el origen permanezca cerrado.
- La prueba HTTP extremo a extremo con la aplicacion se realiza en la Fase 8.

1. Inventariar testers y dispositivos. Usar un certificado distinto por
   dispositivo, con nombre identificable, validez limitada y revocacion
   individual.
2. Generar localmente la clave privada y el CSR de cada dispositivo para no
   entregar la clave privada a Cloudflare.
3. En `SSL/TLS > Client Certificates`, solicitar a la CA gestionada de
   Cloudflare la emision del certificado a partir del CSR.
4. Exportar certificado y clave como PKCS#12 protegido por una contraseña unica
   e instalarlo en el dispositivo correspondiente.
5. Asociar el hostname raiz `assermetry.com` a mTLS. No asociar `www`, que
   permanece fuera de alcance.
6. Crear una regla WAF temporal con accion `Block` equivalente a:

   ```text
   http.host eq "assermetry.com"
   and (
     not cf.tls_client_auth.cert_verified
     or cf.tls_client_auth.cert_revoked
   )
   ```

7. Probar sin certificado y con certificado valido. Incluir en la regla la
   condicion de certificado revocado y documentar la revocacion y el reemplazo;
   su ejecucion real puede reservarse para un incidente cuando el gate sea
   temporal y exista un unico tester.
8. Probar que la regla WAF puede desactivarse y reactivarse como rollback de un
   solo paso, dejandola activa al terminar la fase.

**Resumen de pasos realizados**

1. Se inventario un tester y un dispositivo Windows 11 y se asigno el
   identificador individual `cforcadell-win11-01`.
2. La clave privada cifrada y el CSR se generaron localmente fuera del
   repositorio. Se verifico la autofirma del CSR y su sujeto
   `CN=cforcadell-win11-01, O=Assermetry, OU=Tester`.
3. La CA gestionada de Cloudflare emitio un certificado cliente con validez
   limitada hasta el 5 de agosto de 2028. Se comprobaron sujeto, emisor, fechas
   y correspondencia criptografica entre certificado y clave privada. La
   inspeccion repetida durante la Fase 8 confirmo que
   no declara una extension EKU;
   Cloudflare lo acepto correctamente como certificado cliente mTLS.
4. Se creo un PKCS#12 cifrado y se valido su estructura antes de importarlo en el
   almacen personal del usuario de Windows. El certificado importado conserva
   la clave privada; no declara una extension EKU restrictiva.
5. En Cloudflare se asocio exclusivamente `assermetry.com` a Application
   Security mTLS; `www` permanece fuera de alcance.
6. Se creo y activo la regla WAF temporal `Temporary mTLS gate -
   assermetry.com`, con accion `Block`. La expresion bloquea tanto certificados
   no verificados como certificados marcados expresamente como revocados.
7. Sin certificado, `/`, `/auth` y `/backend` devolvieron `403` desde
   Cloudflare. Con el certificado valido, las tres rutas devolvieron `522`: el
   gate mTLS fue superado y Cloudflare intento alcanzar el origen, que continua
   correctamente cerrado.
8. Se configuro Microsoft Edge para seleccionar automaticamente este certificado
   solo en `https://assermetry.com`. La prueba en el navegador devolvio `522`,
   confirmando la presentacion y aceptacion del certificado sin afectar otros
   dominios.
9. Se desactivo temporalmente la regla WAF y, tras su propagacion, una peticion
   sin certificado devolvio `522`. Se reactivo la misma regla y se comprobaron
   de nuevo `403` sin certificado y `522` con el certificado valido. La regla
   quedo activa al terminar y el origen permanecio cerrado durante toda la
   prueba.

**Decisiones y trabajos no realizados**

1. No se genero `cforcadell-win11-02` y no se revoco
   `cforcadell-win11-01`. Se decidio conservar la credencial ya probada porque
   existe un unico tester, la clave privada esta cifrada y bajo su control. Esta
   decision describia el gate temporal de preparacion y queda sustituida por el
   modelo de acceso de la Fase 8.
2. Se acepta el riesgo residual de que una copia de la clave privada y su
   contraseña permitiria superar el gate mientras este activo. La autenticacion
   de la aplicacion seguiria siendo una barrera independiente.
3. Ante perdida, copia o sospecha de compromiso, el procedimiento sera mantener
   activa la regla WAF, revocar inmediatamente el certificado en Cloudflare,
   emitir e instalar otro certificado individual y actualizar la seleccion
   automatica de Edge antes de continuar las pruebas.
4. La cuenta de Cloudflare y su 2FA son independientes del certificado cliente,
   por lo que la administracion y revocacion siguen disponibles aunque el
   certificado deje de funcionar.
5. La Fase 8 desactivara la regla mTLS general. El certificado operativo se
   conserva solo para administracion, junto con los procedimientos de
   renovacion, revocacion y reemplazo.
6. No se desplego Kubernetes, no se modificaron las URLs OIDC y no se abrieron
   `80/tcp` ni `443/tcp` en el origen.

Criterio de salida: **cumplido con aceptacion de alcance**. El unico tester
dispone de un certificado individual valido; las peticiones sin certificado
quedan bloqueadas; la emision, importacion, cobertura de rutas y reactivacion de
la regla estan probadas. La revocacion y el reemplazo no se ejecutaron de forma
destructiva y se sustituyen por el procedimiento de incidente documentado. El
origen continua cerrado y no se ha redesplegado la aplicacion. Este cierre dio
paso al inicio controlado de la Fase 4.

#### Fase 4 - TLS del origen antes de abrir 443 (cerrada)

**Decision vigente**

- El certificado del origen es un Cloudflare Origin CA para `assermetry.com`,
  instalado manualmente en `kube-system/trustnews-origin-tls` y consumido por
  el `TLSStore` de Traefik.
- Se acepta que la CA no sea publica: las pruebas directas por tunel usaran la
  raiz Origin CA de Cloudflare, mientras que Cloudflare validara el origen en
  modo `Full (strict)`.
- La renovacion es manual. La fecha de expiracion se registrara en el inventario
  y tendra alerta y procedimiento de rotacion.

**Contrato Kind/K3s**

- Kind conserva el certificado local, `host: localhost` y el `secretGenerator`
  de `k8s/ingress/overlays/local`.
- K3s mantiene `trustnews-origin-tls` fuera de los overlays. El helper
  `apply_tls_secret` es su unico mecanismo de instalacion y rotacion.
- `k8s/ingress/base/tls-store.yaml` permanece comun y referencia siempre
  `trustnews-origin-tls` en `kube-system`.
- `prod-domain` se mantuvo inactivo durante las Fases 4 y 5. Su referencia en
  Skaffold esta preparada en la Fase 6, pero K3s aun no la ha desplegado.
- Ningun certificado, clave privada o fichero `tls-origin.env` entra en Git.

**Despliegue**

- Kubernetes local: no desplegar. Solo comprobar que
  `skaffold render -p apis-frontend` conserva el Secret local, `localhost` y el
  `TLSStore`.
- Externo: emitir manualmente en Cloudflare Origin CA un certificado PEM cuyo
  SAN incluya `assermetry.com`; guardar certificado y clave una sola vez en una
  ubicacion privada.
- Kubernetes Hetzner: validar certificado y clave fuera del cluster y actualizar
  `kube-system/trustnews-origin-tls` mediante `apply_tls_secret`, sin abrir
  `80/tcp` ni `443/tcp`.

**Pruebas**

- Confirmar que certificado y clave forman pareja, que el SAN contiene
  `assermetry.com` y registrar emisor, huellas, `notBefore` y `notAfter`.
- Conservar los ficheros del certificado anterior para rollback antes de
  sustituir el Secret.
- Verificar que `TLSStore/default` sigue apuntando a `trustnews-origin-tls` y
  que Traefik permanece disponible.
- Mediante tunel, SNI `assermetry.com` y la raiz Origin CA correspondiente,
  validar la cadena sin usar `-k`.
- Repetir frontend, Gateway y discovery OIDC por tunel.
- Renderizar `apis-frontend`, `apis-frontend-prod` y `prod-domain` sin desplegar
  este ultimo; confirmar la separacion Kind/K3s.
- Confirmar externamente que la IP de Hetzner mantiene `80/tcp` y `443/tcp`
  filtrados. `Full (strict)` se probara cuando Cloudflare pueda alcanzar el
  origen en la Fase 8.

**Evidencias registradas el 2026-08-11**

- Certificado y clave: pareja validada mediante la huella SHA-256 de sus claves
  publicas.
- SAN: `DNS:assermetry.com`.
- Vigencia: `2026-08-11 15:34:00 UTC` - `2028-08-10 15:34:00 UTC`.
- Huella SHA-256 del certificado:
  `0A:82:C8:13:C6:BC:CA:ED:EE:C2:83:7B:14:68:1E:20:D5:6A:E5:27:A8:A0:9E:42:D3:5A:90:BF:44:06:1B:7F`.
- Rollback validado en
  `/home/sysadmin/trustnews-origin-ca/rollback-20260811T155518Z`; el certificado
  y la clave anteriores forman pareja.
- `TLSStore/default` referencia `trustnews-origin-tls` y Traefik permanece
  `Running`.
- Validacion por tunel: `Verification: OK` y
  `Verify return code: 0 (ok)` con SNI y hostname `assermetry.com`.
- Pruebas funcionales por tunel: frontend `200`, raiz del Gateway `404`
  esperado y discovery OIDC `200`.
- Comprobacion externa: conexiones TCP a la IP de Hetzner por `80` y `443`
  rechazadas (`TcpTestSucceeded: False`).
- Skaffold `v2.17.3`: perfiles `apis-frontend` y `apis-frontend-prod`
  renderizados sin conexion al cluster ni despliegue. Local genera su Secret TLS
  y conserva `localhost`; produccion referencia `trustnews-origin-tls` sin
  generarlo y conserva `localhost`.
- Overlays `prod-domain` de Ingress, Gateway y Keycloak renderizados por separado
  sin desplegar: hosts `assermetry.com`, `KC_HOSTNAME_URL` y
  `KEYCLOAK_ISSUER_URL` correctos.
- Alerta de renovacion registrada para el `2028-07-11`, antes de la caducidad
  del `2028-08-10 15:34:00 UTC`.

**Procedimiento de reinstalacion y rotacion**

1. Emitir en `SSL/TLS > Origin Server` un certificado Origin CA para
   `assermetry.com`, en formato PEM y con una clave privada sin passphrase para
   su uso como Secret TLS de Kubernetes.
2. Guardar certificado y clave fuera de Git con permisos restrictivos; registrar
   identificador, algoritmo, SAN, huellas y caducidad.
3. Validar localmente la pareja certificado/clave y preparar `tls-origin.env`
   con rutas a ambos ficheros.
4. Confirmar que el material anterior esta disponible para rollback y ejecutar
   `apply_tls_secret kube-system trustnews-origin-tls "$HOME/trustnews-origin-ca/tls-origin.env"`.
5. Verificar el Secret, el `TLSStore` y el certificado presentado por Traefik
   mediante tunel, SNI y la raiz Origin CA de Cloudflare.
6. Repetir las pruebas funcionales por tunel y mantener el origen cerrado hasta
   la Fase 8.
7. Registrar una alerta anterior a `notAfter` y probar documentalmente la
   rotacion y el rollback manuales.

Criterio de salida: **cumplido**. Kind conserva su certificado local sin
dependencias productivas; K3s presenta por tunel un Cloudflare Origin CA valido
para `assermetry.com`, instalado manualmente en `trustnews-origin-tls` y
referenciado por `TLSStore/default`. El certificado anterior permite rollback,
la caducidad esta inventariada. El origen continua filtrado en `80/tcp` y
`443/tcp`; `prod-domain` permanece sin desplegar hasta la Fase 6.

#### Fase 5 - WAF, restricciones permanentes y observabilidad (cerrada)

**Estado**

- Paso 5.0, inventario y restricciones del plan: **completado**.
- Subpaso Cloudflare del inventario 5.0: **completado**.
- Subpaso Ingress y Services de K3s del inventario 5.0: **completado**.
- Subpaso salud de pods y estado de PVC del inventario 5.0: **completado**.
- Subpaso recursos del nodo y disponibilidad de observabilidad: **completado**.
- Paso 5.4, persistencia, correlacion y cierre: **completado y aceptado en
  Hetzner el 2026-08-18**.
- Paso 5.1, restricciones permanentes del origen: **proteccion Cloudflare y
  navegador administrativo completados**. Las reglas temporal y permanente se
  verificaron sin certificado y con certificado. Las pruebas reales de
  origen/tunel quedan como aceptacion de las Fases 6-7, cuando se active
  `prod-domain`; no requieren un despliegue prematuro. La
  asociacion mTLS de `assermetry.com` permanece
  activa. Una regla WAF permanente exige
  certificado cliente valido solo en `/auth/admin` y
  `/auth/realms/master`; la regla general actual es solo el gate historico de
  preparacion y se desactivara en la Fase 8. La administracion por tunel SSH
  directo a Traefik no pasa
  por Cloudflare y conservara Host/SNI `assermetry.com`. OpenAPI continua
  desactivado en produccion.
  `Permanent mTLS - Keycloak administration` esta activa con accion `Block`
  en posicion 1; `Temporary mTLS gate - assermetry.com` esta activa en
  posicion 2. Ocupan dos de las cinco reglas personalizadas y quedan tres
  disponibles. Dos peticiones sin certificado a
  `/auth/admin/master/console/` y
  `/auth/realms/master/.well-known/openid-configuration` devolvieron `403` y
  generaron dos eventos en la regla permanente, confirmando su precedencia.
  La separacion entre reglas tambien quedo comprobada: dos peticiones sin
  certificado a `/` y
  `/auth/realms/TrustNews/.well-known/openid-configuration` devolvieron `403`.
  Security Events atribuyo la ruta de `TrustNews` a
  `Temporary mTLS gate - assermetry.com`; el contador visible de la regla
  temporal paso a 146, mientras que la regla permanente permanecio en 4. Los
  contadores de la interfaz son muestras agregadas y no se usan para exigir
  una correspondencia exacta de uno a uno con cada peticion.
  La primera repeticion de la prueba positiva desde Microsoft Edge devolvio
  `403`, tanto en `/` como en `/auth/admin/master/console/`, en lugar del `522`
  esperado con el origen cerrado. El navegador no presento un certificado que
  Cloudflare considerase valido. Antes de repetirla se comprobara la politica
  `AutoSelectCertificateForUrls` y la presencia de `cforcadell-win11-01`, con
  su clave privada, en el almacen personal de Windows; no se revoca ni reemite
  el certificado durante este diagnostico.
  La politica de Edge se comprobo cargada y aceptada, con nivel obligatorio,
  alcance de dispositivo, patron `https://assermetry.com` y filtro de sujeto
  `CN=cforcadell-win11-01`. Tambien se comprobo en `CurrentUser\My` el
  certificado esperado, emitido por la CA gestionada de Cloudflare, valido del
  6 de agosto de 2026 al 5 de agosto de 2028 y con clave privada. Una inspeccion
  posterior confirmo que no declara la extension EKU. Cloudflare lo acepta
  correctamente para mTLS, por lo que la ausencia de esa restriccion no impide
  este uso. Tanto la politica como el
  certificado local quedan descartados como ausentes; antes de revisar
  Cloudflare se forzara una nueva sesion TLS de Edge.
  Tras reiniciar Edge y abrir URLs nuevas, `/` y
  `/auth/admin/master/console/` continuaron devolviendo `403`. La reutilizacion
  de una sesion TLS anterior queda descartada; falta verificar en Cloudflare
  el estado del certificado y la asociacion del hostname con la CA gestionada.
  La comprobacion en `SSL/TLS > Client Certificates > Cloudflare-issued`
  confirmo despues que `assermetry.com` sigue asociado a mTLS y que
  `CN=cforcadell-win11-01, OU=Tester, O=Assermetry` figura `Active`, emitido por
  la CA gestionada de la cuenta y con caducidad el 5 de agosto de 2028. El
  siguiente aislamiento consiste en presentar explicitamente el certificado
  del almacen de Windows mediante `curl.exe` con Schannel.
  Esa prueba explicita devolvio `522` tanto para `/` como para
  `/auth/admin/master/console/`. Queda demostrado que el certificado es valido,
  Cloudflare lo acepta y ambas reglas permiten el trafico autenticado antes de
  que el firewall cerrado del origen cause el timeout esperado. El `403`
  residual queda aislado a la seleccion automatica de Microsoft Edge; no es un
  fallo de las reglas mTLS ni requiere reemitir el certificado.
  Google Chrome tambien devolvio `403` sin mostrar selector de certificado.
  Dado que `curl.exe` con Schannel si presenta la misma credencial, se probara
  a continuacion Chromium sin QUIC/HTTP/3 antes de investigar VPN, proxy o la
  cadena anunciada por el servidor.
  Con `Experimental QUIC protocol` desactivado, Chrome solicito el certificado
  y devolvio `522`; quedan confirmados la presentacion en navegador, la
  validacion de Cloudflare y el timeout esperado del origen cerrado. La causa
  de los `403` de Chromium es el uso de QUIC/HTTP/3 en este flujo mTLS. Para el
  navegador administrativo se fijara una configuracion permanente sin QUIC.
  En Edge, al desactivar `Experimental QUIC protocol`, la politica selecciono
  automaticamente el certificado y `/` devolvio `522`. La repeticion sobre
  `/auth/admin/master/console/` tambien devolvio `522`. Las dos ramas mTLS
  quedan validadas en Edge sobre HTTP/2: seleccion automatica, certificado
  aceptado y timeout posterior del origen cerrado. El siguiente paso es
  sustituir el flag experimental por la politica estable `QuicAllowed=0`.
  Se aplico `QuicAllowed=0` como politica obligatoria de dispositivo, se
  devolvio el flag experimental a `Default` y, tras reiniciar Edge, `/` y
  `/auth/admin/master/console/` mantuvieron el `522`. La configuracion durable
  del navegador administrativo queda validada. La restriccion es global para
  Edge en ese dispositivo y se mantiene mientras la administracion dependa de
  mTLS.
  Durante la prueba, `curl` rechazo inicialmente el certificado TLS del edge
  con `certificate is not yet valid`; `-k` se uso solo para aislar y comprobar
  la regla WAF. El diagnostico confirmo que el cliente marcaba
  `2026-07-31 05:05 UTC`, con `System clock synchronized: no`, mientras que el
  certificado de `assermetry.com` es valido desde `2026-08-04 14:21:20 UTC` y
  Cloudflare ya registraba eventos del 12 de agosto. La causa es el reloj
  atrasado del cliente. `systemd-timesyncd` resolvia
  `ntp.ubuntu.com`, pero mostraba `Packet count: 0`; el journal registro
  timeouts contra todos los servidores NTP probados por IPv4 e IPv6. El
  cliente es una VM VirtualBox y
  `vboxadd-service` 7.0.12 estaba instalado y habilitado, pero inactivo desde
  el 13 de junio. Al arrancarlo, Guest Additions corrigio el reloj a
  `2026-08-12`; una nueva peticion sin `-k` valido correctamente TLS y devolvio
  `403` en la ruta administrativa. `System clock synchronized: no` continua
  describiendo a `systemd-timesyncd`, no a la sincronizacion de Guest
  Additions que corrigio la hora.
- Paso 5.2, metodos, cuerpos y rechazos: **completado y aceptado en Hetzner**.
  Gateway y Traefik aplican el mismo maximo de 5 MiB. Traefik usa
  `buffering.maxRequestBodyBytes` y Gateway conserva una defensa interna para
  peticiones directas o fragmentadas. Gateway emite un evento JSON
  `gateway_access` por respuesta con `request_id`, metodo, ruta, estado, bytes y
  duracion; `401/403/405/413/429` se registran como warning y `5xx` como error,
  sin tokens, query string ni cuerpos. Ocho pruebas unitarias cubren el limite
  declarado y fragmentado, el replay del cuerpo, el identificador y los estados
  relevantes. En Kind se verifico `405`; a 5 MiB la peticion alcanzo Gateway y
  devolvio `403` por falta de credenciales; a 5 MiB + 1 byte Traefik devolvio
  `413`. Por acceso directo, Gateway devolvio y registro `413` y `405`. Dos
  payloads JSON superiores al limite, uno Light y otro Blockchain, devolvieron
  `413` sin crear ordenes ni consumir cuotas. En Hetzner se confirmaron ambos
  limites activos con `5242880`, los rechazos `405`, `401` y `413` a traves de Traefik,
  y el `413` directo del Gateway con `body_bytes=5242881` y `request_id`. El pod
  permanecio preparado, sin reinicios, y las ordenes legitimas Light y
  Blockchain completaron el flujo extremo a extremo. La carrera de
  descubrimiento de validadores observada en Light queda mitigada y registrada
  como `ISSUE-001` en `docs/issues.md`, con correccion de frescura de cache
  pendiente.
- Inventario Cloudflare del 2026-07-31: la regla personalizada
  `Temporary mTLS gate - assermetry.com` esta activa con accion `Block`,
  ocupa una de las cinco reglas disponibles y muestra 238 eventos en la captura
  de verificacion. No hay reglas de rate limiting y el unico slot disponible
  permanece libre. En `Security > Settings > Web application exploits`, el
  `Cloudflare managed ruleset` figura `Always active` y muestra 31 reglas,
  incluidas firmas generales como Shellshock y varias especificas de WordPress;
  las diez primeras reglas mostradas tienen accion `Block`.
  Security Events, filtrado por el Rule ID del gate mTLS y por las ultimas 24
  horas, muestra unicamente acciones `Block` del servicio `Custom rules`
  desde varios paises y rafagas repetidas desde un mismo origen. Las IP no se
  registran en Git. Se inspeccionaron tres muestras anonimizadas:
  `GET /backend/.git/config`, `GET /.git/config` y `GET /`. Las dos
  primeras son reconocimiento hostil. La intencion de la tercera es
  indeterminada, pero su bloqueo es correcto durante la fase privada porque no
  presento un certificado cliente valido. No hay evidencia en las muestras de
  bloqueo a un tester autorizado. La proteccion permanente posterior a mTLS
  debera cubrir intentos de acceso a `/.git` y otros archivos sensibles.
  La sustitucion de librerias JavaScript inseguras esta activa y el modo
  `I'm under attack` esta desactivado.
- Los cambios de 5.2 se desplegaron y aceptaron en Hetzner el 2026-08-13 con
  el perfil `apis-frontend-prod`. Gateway y Traefik exponen el limite coherente
  de 5 MiB; los rechazos por ambos caminos y los flujos legitimos Light y
  Blockchain quedaron verificados.
- El paso 5.3 se inicio el 2026-08-14. Se contrastaron las rutas reales del
  Gateway con los limites vigentes de Cloudflare Free y se preparo en
  `docs/deploy/skaffold-server.md` el despliegue controlado de dos reglas WAF
  permanentes y la unica regla de rate limiting. El limite inicial es de 5
  peticiones en 10 segundos por IP para importacion, generacion y publicacion.
  Token, refresh y polling quedan excluidos porque el plan Free solo permite
  filtrar el rate limiting por ruta y no puede distinguir el tipo de concesion
  dentro del endpoint compartido de Keycloak. El dashboard confirmo la managed
  ruleset como `Always active`, las cuatro reglas WAF quedaron activas en el
  orden previsto y la regla de rate limiting quedo activa como `1/1`. Las
  pruebas de recursos no publicos quedaron aceptadas: el control `GET /`
  devolvio `522` tras superar mTLS, mientras que OpenAPI y las dos rutas Git
  controladas devolvieron `403`. La regla de metodos tambien quedo aceptada:
  `DELETE /backend/orders/list` devolvio `403` y el control `GET` devolvio
  `522`. Una primera rafaga de seis `HEAD` simultaneos no produjo `429`; las
  seis peticiones devolvieron `522`. La prueba definitiva uso respuestas
  rapidas `403` de la Free Managed Ruleset: las cinco primeras peticiones
  pasaron a esa fase, las diez siguientes devolvieron `429` y, tras 15
  segundos, la recuperacion devolvio de nuevo `403`. Security Events atribuyo
  las muestras a `Custom rules`, `Managed rules` y `Rate limiting rules`
  segun lo esperado, sin falsos positivos visibles. No se registran IP ni
  identificadores de Cloudflare. El paso 5.3 queda aceptado en el borde; los
  flujos legitimos a traves de Cloudflare son un gate de las Fases 6-7, cuando
  el origen sea alcanzable. El gate mTLS sigue activo.
- Los perfiles Skaffold quedan preparados para usar `prod-domain`, pero no se
  han desplegado. El K3s activo sigue con `host: localhost` y el origen continua
  filtrado en `80/tcp` y `443/tcp`.
- La revision estatica del repositorio confirma que solo frontend, Gateway y
  Keycloak tienen Ingress. Los Services inventariados no declaran `NodePort`;
  el estado real de K3s se contrasto y coincide. Solo existen
  `gateway-ingress`, `frontend-ingress` y `keycloak-ingress`, todos con
  `host: localhost`. Los Services de aplicacion e infraestructura son
  `ClusterIP`; no hay Services de aplicacion `NodePort`. El unico
  `LoadBalancer` es Traefik en `80/443`, como borde previsto, y su alcance
  publico continua controlado por el firewall externo. No se registran
  direcciones del cluster en Git.
- La muestra final del 2026-08-18 confirma 29 pods activos, todos preparados y
  con cero reinicios. Los nueve PVC estan `Bound` sobre `local-path`, incluidos
  `loki-data` y `grafana-data`; no hay PVC pendientes.
- Brechas de observabilidad detectadas en 5.0: Loki y Grafana no tenian PVC y
  Fluent Bit excluia `kube-system`. Las tres quedaron corregidas y probadas en
  5.4; Loki conserva sus eventos, Grafana conserva su datasource y los access
  logs de Traefik son consultables por `namespace` y `container`.
- Muestra final de recursos: nodo al 5% de CPU, 78% de memoria y 56% de disco
  raiz, con 31,7 GiB disponibles. La memoria requiere vigilancia antes de abrir;
  se propone alerta preventiva al 80% y critica al 90%. Para disco se propone
  aviso al 75% y critico al 85%. Los tres nodos Geth suman aproximadamente
  1,9 GiB; Kafka usa unos 577 MiB y Keycloak unos 469 MiB en la muestra.
- En la linea base de 5.0, Fluent Bit, Loki y Grafana tenian una replica disponible y 108 dias de
  antiguedad. Metrics Server responde correctamente. La API de consulta de Loki
  funciona y contiene streams de `apis`, `blockchain` e `infra`; no
  contiene `kube-system`, confirmando la ausencia de logs de Traefik.
  `frontend` no aparece en la ventana retenida, posiblemente por falta de
  trafico reciente. Grafana responde con base de datos `ok`. Una consulta
  inicial a `/ready` mediante el proxy de la API de Kubernetes devolvio
  `ServiceUnavailable`, pero dos comprobaciones directas consecutivas dentro
  del contenedor devolvieron `HTTP 200` y `ready`. Loki y Grafana tienen
  endpoints internos validos y los logs revisados contienen solo operaciones
  informativas de indices TSDB, sin errores. Se clasifica el `503` como
  transitorio o propio del camino de proxy, no como indisponibilidad persistente.
  El Deployment de Loki no tenia `readinessProbe` ni `livenessProbe`; esta
  brecha quedo corregida y validada en 5.4.
- El plan activo de Cloudflare es Free. En este plan no existe la accion `Log`
  para reglas WAF personalizadas, Security Events contiene muestras con hasta
  24 horas de retencion, hay cinco reglas personalizadas y una regla de rate
  limiting. La Free Managed Ruleset esta disponible y se despliega por defecto.
  Por ello, el requisito original de comenzar todas las reglas en deteccion se
  sustituye por una puesta en marcha controlada bajo el gate mTLS: revisar la
  Free Managed Ruleset y Security Events, probar cada regla con trafico
  controlado y solo entonces conservar su accion de bloqueo.

- Primer incremento de 5.4 preparado en Git, validado en Kind y desplegado en
  Hetzner el 2026-08-17, segun confirmacion del operador. Loki usa un PVC de
  2 GiB en Kind y de 5 GiB en Hetzner; Grafana usa 1 GiB en ambos entornos. Se
  han anadido probes de
  arranque, disponibilidad y vida, e inclusion de `kube-system` con
  etiqueta `container` en Fluent Bit. `frontend-logs` sigue el patron de
  recursos compartidos y overlays `local`/`prod`; Skaffold selecciona el
  correspondiente en `infra` e `infra-prod`. Ambos perfiles renderizan y
  superan el dry-run cliente. En Kind, ambos PVC quedaron `Bound`; Loki,
  Grafana y
  Fluent Bit quedaron preparados y sin reinicios; sus endpoints de salud
  respondieron correctamente, y Loki catalogo `kube-system` y `traefik`.
  La incidencia de reloj observada en Kind no se reprodujo en Hetzner. La
  ingesta de Gateway y Traefik, la retencion tras reiniciar Loki, la base y el
  datasource de Grafana tras reiniciarlo, los recursos, los reinicios y las
  evidencias controladas quedaron validados el 2026-08-18. El paso queda
  cerrado.

- El 2026-08-17 se confirmo el acceso operativo a Grafana en Hetzner mediante
  un doble tunel: `kubectl port-forward` escucha en el puerto `3000` del
  servidor y SSH lo publica unicamente en `127.0.0.1:13000` del puesto de
  operacion. Se uso `13000` porque Windows no permitio enlazar el puerto local
  `3000`. Esta prueba acredita la alcanzabilidad privada de Grafana, sin crear
  Ingress ni exponer el servicio; no acredita por si sola los PVC, las probes,
  la retencion de Loki ni la ausencia de reinicios.

- Validacion posdespliegue del 2026-08-17 a las 14:35 UTC: los rollouts de
  Loki, Grafana y Fluent Bit finalizaron correctamente. Los PVC `loki-data` y
  `grafana-data` estan `Bound` con StorageClass `local-path`, y capacidad y
  solicitud de 5 GiB y 1 GiB respectivamente. Los pods de los tres componentes
  estaban preparados y acumulaban cero reinicios. No se guardan nombres de pod
  ni datos identificativos del servidor.

- Salud posdespliegue validada el 2026-08-17 a las 14:37 UTC: dos muestras
  separadas por 16 segundos devolvieron Loki `ready` y Grafana 11.5.2 con
  base de datos `ok`. Loki, Grafana y Fluent Bit permanecieron preparados y
  con cero reinicios en ambas muestras.

- Diagnostico de ingesta del 2026-08-17: la API de Loki respondio `success` y
  su catalogo contiene `apis`, `blockchain`, `infra` y `kube-system`. Sin
  embargo, las consultas exactas de Traefik y Gateway no devolvieron streams
  en la ventana de 24 horas. Una consulta ampliada confirmo ingesta actual a
  las 14:44 UTC desde `coredns`, `news-chain` y `evidence-search`, por lo que
  no existe una interrupcion general entre Fluent Bit y Loki. El resumen de
  Fluent Bit examino 162 lineas. La clasificacion posterior identifico once
  eventos entre las 09:04:43 y las 09:06:39 UTC: seis errores genericos, dos
  fallos de envio, dos reintentos y una respuesta HTTP 500 de Loki. No hubo
  eventos en la ultima hora y la ingesta actual estaba confirmada, por lo que
  se consideran transitorios del despliegue, no un fallo persistente. El paso
  3 avanzo con una peticion GET controlada y sin credenciales a una ruta
  protegida: devolvio el `403` esperado y Gateway genero dos muestras en Loki
  a las 14:50:00 UTC. Traefik no genero ninguna muestra en la misma ventana.
  La inspeccion posterior confirmo que sus argumentos no habilitan access log.
  Tampoco existe un `HelmChartConfig/traefik` ni un `HelmChart/traefik`
  empaquetado de K3s. El Deployment pertenece a la release Helm `traefik`,
  revision 1, con chart `traefik-41.0.2` e imagen
  `docker.io/traefik:v3.7.6`; la release figura desplegada y el Deployment no
  tiene `ownerReference`, como es habitual en recursos gestionados por Helm.
  La revision del proyecto y de su historial confirmo una brecha de
  automatizacion: Skaffold desplegaba los Ingress, pero no declaraba el chart
  ni la release. La correccion queda preparada en Git: los perfiles `traefik`
  y `traefik-prod` fijan el chart `41.0.2`, consumen valores versionados y
  activan access log JSON descartando cabeceras y parametros de consulta.
  GitLab CI instala Helm 3.21.0 en los jobs `build` y `deploy` tras verificar
  su SHA-256, aplica el upgrade con `--atomic` y comprueba el rollout y
  `--accesslog=true`. El esquema Skaffold, el render real del chart, el
  `build.json` sin imagenes y el YAML estan validados. No ejecutar un
  `helm upgrade` manual ni parchear el Deployment. El primer pipeline fallo en
  `build` porque el cliente Helm solo estaba instalado en `deploy`; no hubo
  cambios en el cluster. El segundo actualizo la release a la revision 2, pero
  termino con codigo 1 porque el perfil heredaba el deployer global `kubectl`
  sin manifests. El tercer pipeline, con Helm disponible en ambos jobs y los
  perfiles exclusivamente Helm, finalizo correctamente el 2026-08-17 a las
  15:41 UTC: release en revision 3, Deployment preparado, rollout aceptado y
  comprobacion de access log superada. La verificacion directa de las 15:44
  UTC confirmo el rollout, un pod preparado con cero reinicios y los argumentos
  de access log, formato JSON, descarte de cabeceras y descarte de parametros
  de consulta. A las 15:46 UTC, las peticiones controladas devolvieron frontend
  `200`, discovery OIDC `200` y Gateway protegido `403`. Loki respondio
  `success`, pero el primer extractor no encontro eventos con el campo
  `DownstreamStatus`. La lectura directa y resumida de stdout confirmo 25
  lineas, tres JSON de access log y exactamente los tres eventos controlados:
  dos `200` y un `403`. Traefik genera correctamente los registros. La
  consulta estructural de Loki devolvio tres streams y 50 muestras con campos
  superiores `kubernetes` y `log`: Fluent Bit conserva el evento dentro de
  `log` con un prefijo anterior al JSON. La ingesta quedo confirmada con una
  correlacion final que recupero exactamente los tres eventos de las 15:46:23
  UTC: `GET /` con `200`, discovery OIDC con `200` y
  `GET /backend/orders/list` con `403`.
  Como el servidor no dispone de `jq`, el JSON se resume con `python3` sin
  instalar paquetes ni mostrar lineas de log.

**Cierre de 5.4**

1. **Completado:** evidencia de rollouts, PVC, pods preparados y reinicios del
   despliegue `infra-prod`.
2. **Completado:** salud de Loki y Grafana comprobada dos veces; componentes
   preparados y sin reinicios inesperados.
3. **Completado:** Gateway y Traefik confirmados en Loki; los tres eventos
   controlados quedaron correlacionados por instante, metodo, ruta y estado.
4. **Completado:** la linea base previa al reinicio confirmo ambos PVC `Bound`,
   pods preparados y sin reinicios, la base persistente de Grafana presente con
   1.110.016 bytes y Loki `ready`. A las 15:55 UTC Loki creo un pod nuevo,
   mantuvo el mismo PVC y volvio a `ready`; el pod anterior aun estaba terminando
   durante la primera consulta. Con una sola replica activa, la consulta posterior
   devolvio cero streams y cero muestras para el intervalo que antes contenia los
   tres eventos. El diagnostico confirmo que el PVC estaba vacio en `/tmp/loki`,
   mientras la configuracion efectiva escribia `path_prefix`, chunks y WAL en
   `/loki`. El manifiesto queda corregido para montar `loki-data` en `/loki`;
   el overlay productivo renderizo correctamente el nuevo montaje. `infra-prod`
   lo desplego y, a las 16:05 UTC, el mismo PVC de 5 GiB estaba `Bound` en
   `/loki`, con cuatro archivos, WAL persistente, pod preparado sin reinicios y
   Loki `ready`. El probe controlado devolvio `404`, aparecio una vez antes del
   reinicio y permanecio una vez despues. El pod fue reemplazado, quedo
   preparado y con cero reinicios. Grafana tambien reemplazo su pod y conservo
   la base, el datasource Loki y la consulta del mismo probe.
5. **Completado:** los `401` y `403` controlados quedaron correlacionados por
   `request_id` en Gateway y Loki. La regla de Cloudflare produjo cinco `403`,
   diez `429` y volvio a `403` tras 15 segundos; Security Events mostro las diez
   acciones `Block` esperadas, sin falsos positivos visibles. Una consulta
   blockchain imposible y de solo lectura produjo un unico `500`, tambien
   correlacionado en Gateway y Loki. No se detuvieron servicios ni se crearon
   ordenes.
6. **Completado:** CPU 5%, memoria 78% y disco 56%, con 31,7 GiB disponibles.
   Los 29 pods activos estaban preparados, los nueve PVC estaban `Bound` y no
   habia reinicios.
7. **Completado:** 5.4 y la Fase 5 quedan cerradas. La Fase 6 puede comenzar
   manteniendo el origen cerrado.

**Punto de reanudacion del 2026-08-18**

Los perfiles Skaffold quedan preparados para `prod-domain`, pero no se han
desplegado. La comparacion de renderizados y el rollback estatico a `prod`
estan revisados. Reanudar tras versionar y publicar el cambio: verificar de
nuevo certificado y `TLSStore`, ejecutar `infra-prod`, validar Keycloak y solo
entonces ejecutar `apis-frontend-prod`. No tocar el firewall.

**Secuencia de trabajo**

1. **5.0 - Inventario:** registrar reglas WAF y rate limits existentes, revisar
   Security Events y contrastar Ingress, Services y observabilidad del K3s real.
2. **5.1 - Restricciones permanentes del origen:** mantener OpenAPI
   desactivado y no aplicar un `deny` total en Traefik que tambien bloquearia
   el acceso administrativo por tunel. Crear antes del gate temporal una regla
   WAF mTLS permanente para
   `/auth/admin` y `/auth/realms/master`. Mantener la asociacion mTLS del
   hostname y la regla general temporal. Solo una futura decision de produccion
   podra desactivar esta ultima. La administracion por SSH usara Traefik
   directamente, preservando el hostname canonico `assermetry.com`; el firewall impedira que Internet
   utilice esa via para evitar Cloudflare.
3. **5.2 - Metodos, cuerpos y rechazos (completado):** aplicar limites compatibles en
   Gateway y Traefik, emitir logs para `401/403/405/413/429/5xx` y probar los
   flujos legitimos antes de desplegar en Hetzner.
4. **5.3 - Cloudflare (completado):** confirmar la Free Managed Ruleset, crear el conjunto
   minimo de reglas personalizadas permanentes y dedicar la unica regla de rate
   limiting a los endpoints de mayor coste, sin incluir refresh ni polling.
5. **5.4 - Observabilidad y cierre (completado):** persistencia, consultas,
   rechazos controlados, falsos positivos, recursos y reinicios aceptados.

**Despliegue**

- Kubernetes local: desplegar y probar solo si cambian Gateway, Traefik,
  middlewares o configuracion de logs; las reglas Cloudflare no se despliegan en
  local.
- Kubernetes Hetzner: desplegar los manifests de seguridad u observabilidad que
  hayan cambiado, manteniendo `prod` y el acceso por tunel.
- Externo: configurar WAF y rate limiting de Cloudflare de forma controlada bajo
  el gate mTLS y revisar Security Events antes de conservar cada bloqueo.

**Pruebas**

- Local, si hubo despliegue: verificar metodos permitidos, tamaño maximo,
  respuestas `404/403/405/413/429` y que login, refresh, polling y flujos Light y
  Blockchain legitimos no se rompen.
- Hetzner por tunel: repetir las restricciones implementadas en Gateway o
  Traefik y comprobar logs de cada rechazo.
- Cloudflare: reproducir peticiones validas e invalidas, revisar falsos
  positivos antes de bloquear y comprobar rate limits sin bloquear refresh.
- Generar de forma controlada un `401`, `403`, `429` y `5xx` y verificar logs y
  alertas. Confirmar que servicios internos no tienen Ingress ni NodePort.

1. Confirmar la Free Managed Ruleset y revisar sus eventos; probar los bloqueos
   personalizados de forma controlada bajo mTLS y revisar falsos positivos.
2. Definir rate limits para login/token, importacion, generacion y publicacion,
   sin romper refresh tokens ni polling.
3. Limitar metodos HTTP y tamano de peticiones en Cloudflare, Traefik y Gateway.
4. Bloquear permanentemente:

   ```text
   /auth/admin/*
   /auth/realms/master/*
   /backend/docs
   /backend/redoc
   /backend/openapi.json
   ```

5. Preparar logs y alertas para mTLS, WAF, Traefik, Gateway, Keycloak,
   certificados, reinicios, disco y respuestas 401, 403, 429 y 5xx.
6. Confirmar que MongoDB, PostgreSQL, Kafka, Kafdrop, Mongo Express, IPFS API,
   RPC Ethereum, admin-service y Kubernetes API no tienen Ingress ni NodePort.

Criterio de salida: **cumplido**. Las protecciones que deben sobrevivir a la
retirada del mTLS estan activas y observables; la persistencia, los rechazos y
los umbrales operativos quedaron validados sin abrir el origen.

#### Fase 6 - Despliegue definitivo todavia cerrado (cerrada)

**Estado del 2026-08-18**

- `infra-prod` referencia `k8s/infra/keycloak/overlays/prod-domain`.
- `apis-frontend-prod` referencia los overlays `prod-domain` de Gateway e
  Ingress.
- Los dos perfiles renderizan offline y el diagnostico de Skaffold es valido.
- Frente al render anterior, solo cambian `KC_HOSTNAME_URL`,
  `KC_HOSTNAME_ADMIN_URL`, `KEYCLOAK_ISSUER_URL` y los tres hosts de Ingress,
  todos de `localhost` a `assermetry.com` con las rutas y puertos previstos.
- El pipeline GitLab `#2770049730`, ejecutado sobre `postTFM` y el commit
  `4a7e9185`, finalizo correctamente en 2 minutos y 22 segundos. Completaron
  `build`, `check_phase6_origin_tls`, `deploy` con `PROFILE=infra-prod` y
  `bootstrap_mongodb`; el job de rollback no se ejecuto.
- Esta evidencia confirma el gate TLS y la aplicacion de `infra-prod`, pero el
  pipeline ejecutado aun no esperaba explicitamente el rollout de Keycloak ni
  comprobaba su discovery OIDC. Esa validacion es el siguiente gate. El
  firewall permanece cerrado.
- La repeticion de `infra-prod` sobre el commit `77e189ef` estabilizo los nueve
  workloads. `keycloak-db` quedo preparado, el Deployment de Keycloak completo
  su rollout y las dos comprobaciones de `KC_HOSTNAME_URL` y
  `KC_HOSTNAME_ADMIN_URL` no fallaron. El job termino con codigo 1 unicamente en
  la consulta del discovery OIDC.
- Durante el rollout, el nuevo pod de Loki quedo temporalmente sin programar
  por CPU y memoria insuficientes y su startup probe devolvio `503`. Finalmente
  quedo preparado y Skaffold estabilizo los nueve workloads; vigilar recursos
  antes y durante `apis-frontend-prod`.
- La repeticion sobre `3c99a48e` emulo correctamente `Host`, proto y puerto
  externos. El discovery publico
  `https://localhost/auth/realms/TrustNews`, confirmando que el atributo
  persistido `frontendUrl` del realm prevalece sobre `KC_HOSTNAME_URL`.
- El gate actualizado autentica `kcadm` solo dentro del pod, usa un fichero de
  sesion temporal con permisos internos, actualiza idempotentemente
  `attributes.frontendUrl=https://assermetry.com/auth` y elimina la sesion antes
  de consultar discovery. No modifica todavia clientes ni secretos. No se
  despliega `apis-frontend-prod` hasta obtener el issuer definitivo.
- El job ejecutado sobre `dc81ca9` completo el rollout de Keycloak, autentico
  `kcadm` dentro del pod, actualizo `attributes.frontendUrl` y observo
  `https://assermetry.com/auth/realms/TrustNews`. MongoDB, Loki, Grafana y
  Fluent Bit completaron tambien sus rollouts. El job finalizo correctamente y
  la sesion administrativa temporal se elimino durante la limpieza del bloque.
  El gate de `infra-prod` queda aceptado.
- El preflight local se repitio con Skaffold `v2.17.3`: `infra-prod` renderizo
  27 recursos y `apis-frontend-prod` 43, todos aceptados por la validacion
  client-side. La comparacion directa confirma como unicos cambios las dos URLs
  externas de Keycloak, el issuer del Gateway y los tres hosts de Ingress; el
  Secret de origen referenciado continua siendo `trustnews-origin-tls`.
- GitLab CI incorpora `check_phase6_origin_tls` como dependencia previa de los
  despliegues `infra-prod` y `apis-frontend-prod`. El gate comprueba en K3s el
  tipo del Secret, la referencia de `TLSStore/default`, el hostname
  `assermetry.com`, una vigencia restante minima de 30 dias y la pareja
  certificado/clave, sin modificar el cluster ni mostrar la clave privada.

**Punto de control posterior a `apis-frontend-prod` del 2026-08-19**

- Estado confirmado antes del segundo despliegue: `infra-prod`, el certificado,
  `TLSStore/default`, Keycloak y los clientes OIDC estaban aceptados.
- Evidencia posterior a `apis-frontend-prod`: 29 de 29 pods preparados, cero
  reinicios y los nueve PVC `Bound`. Los pods de APIs y frontend tenian unos
  80 segundos de antiguedad en la captura, coherente con el rollout reciente.
- `gateway-ingress`, `frontend-ingress` y `keycloak-ingress` usan
  `host: assermetry.com`; `TLSStore/default` continua apuntando a
  `trustnews-origin-tls`. No se registra la direccion del servidor en Git.
- Mediante `--connect-to assermetry.com:443:127.0.0.1:9443`, el frontend
  devolvio `HTTP/2 200` y discovery devolvio el issuer exacto
  `https://assermetry.com/auth/realms/TrustNews`, junto con endpoints de
  autorizacion, token, JWKS y logout bajo el dominio definitivo.
- Las dos peticiones preliminares usaron `curl -k`; una repeticion posterior
  desde Windows uso la raiz publica Origin CA mediante `--cacert`, sin `-k`, y
  obtuvo `HTTP/1.1 200` en el frontend sin errores de certificado. Discovery
  confirmo issuer, token endpoint, JWKS y logout bajo el dominio definitivo.
- Gateway devolvio `403` sin credenciales, como se esperaba.
  `/backend/docs`, `/backend/redoc` y `/backend/openapi.json` devolvieron `404`.
- Una hora despues del rollout, los 29 pods continuaban preparados y sin
  reinicios. El nodo estaba al 5% de CPU y 74% de memoria; los mayores consumos
  eran los tres nodos Geth, Kafka y Keycloak. No habia pods `Pending`.
- El operador recupero el secret por su via autorizada, lo introdujo como
  `SecureString` y lo elimino de las variables tras la prueba. Keycloak emitio
  un access token para `TrustNewsApi`. Gateway valido el JWT y envio
  `GET /orders/list` a `news-handler`; la respuesta fue `404` porque ese
  servicio devuelve `No hay noticias registradas` cuando el service account no
  tiene noticias. No fue un rechazo `401/403` de autenticacion.
- Tras obtener un token nuevo, `GET /backend/auth/is-admin` devolvio `HTTP 200`
  con `is_admin:false`, esperado para un service account sin `trust-admin`. Un
  intento anterior devolvio `403` porque la variable `AccessToken` ya estaba
  vacia; no se considera un fallo de `TrustNewsApi`.
- El operador confirmo la validacion hasta el punto 6 del procedimiento de
  navegador: carga por el dominio canonico, flujo de `TrustNewsWeb` y smoke
  tests Light y Blockchain. No se aportaron al documento tokens, secrets, datos
  de usuario ni identificadores de orden. El punto 7 tambien se completo: se
  retiraron la entrada de `hosts`, la raiz Origin CA importada, el tunel y las
  variables temporales.
- `TrustNewsWeb` se actualizo mediante `kcadm` dentro del pod porque la consola
  cargada como `https://localhost:9443` quedaba bloqueada por la CSP: Keycloak
  ya genera sus recursos administrativos para el hostname canonico
  `assermetry.com`, mientras los Ingress activos todavia conservaban
  `host: localhost`. Tras `apis-frontend-prod`, los tres usan el dominio final.
- El realm conserva el nombre tecnico `TrustNews`, tiene display name
  `Assermetry` y su representacion completa confirma
  `attributes.frontendUrl=https://assermetry.com/auth`. La proyeccion abreviada
  de `kcadm` con `--fields ... attributes` mostro inicialmente un mapa vacio;
  para verificar atributos se uso la representacion completa.
- `TrustNewsWeb` quedo con `rootUrl=https://assermetry.com`,
  `baseUrl=https://assermetry.com/`, redirects y post-logout
  `https://assermetry.com/*`, y Web Origin `https://assermetry.com`.
- `TrustNewsApi` se verifico antes y despues: continua habilitado,
  confidencial (`client-secret`), con service account activa y sin cambios. No
  se consulto, mostro ni modifico su secret.
- El rollback no secreto capturado para `TrustNewsWeb` es
  `rootUrl=https://localhost:9443`, `baseUrl` vacio, redirects
  `https://localhost:9443/*`, Web Origin `*` y post-logout ausente.
- La sesion temporal de `kcadm` se elimino. El discovery, consultado por
  port-forward con las cabeceras externas emuladas, devolvio exactamente
  `https://assermetry.com/auth/realms/TrustNews`.
- Limpieza local completada. `ISSUE-002` esta resuelto: se elimino el valor por
  defecto no vacio y se confirmo que no coincide con produccion, por lo que no
  exige rotar `TrustNewsApi`. Comprobar si el valor historico corresponde a una
  credencial de tests activa queda como recomendacion no bloqueante. El
  firewall mantiene cerrados `80/tcp` y `443/tcp`.
- No repetir `infra-prod` salvo que aparezca un problema de salud. No desplegar
  `blockchain-prod` porque esta fase no ha introducido cambios en blockchain.

La fase queda formalmente cerrada. Como recomendacion independiente, comprobar
si el valor historico pertenecio a una credencial de tests activa y revocarla o
rotarla si procede. No rotar `TrustNewsApi` de produccion por este hallazgo,
porque el operador confirmo que los valores no coinciden. La Fase 8 puede
continuar manteniendo el alcance privado definido para Cloudflare.

**Despliegue**

- Kubernetes local: no desplegar `prod-domain` sobre el cluster local habitual;
  solo renderizarlo y validarlo estaticamente.
- Kubernetes Hetzner: si. Activar coordinadamente `prod-domain` en los perfiles
  productivos y desplegar `infra-prod` y `apis-frontend-prod` por tunel.
  Desplegar `blockchain-prod` solo si ha cambiado o falta.
- Mantener el firewall cerrado a Internet durante todo el despliegue.

**Pruebas**

- Antes de desplegar: comparar los renderizados `prod` y `prod-domain` y revisar
  que solo cambian los valores previstos de dominio, issuer y hosts.
- Hetzner por tunel, resolviendo localmente `assermetry.com` hacia Traefik:
  verificar certificado, discovery OIDC, issuer exacto, redirects, post-logout,
  Web Origins, login, refresh, logout, roles y client credentials.
- Ejecutar smoke Light y Blockchain, workers, cuotas, IPFS, validadores,
  exploradores, contrato y categorias; comprobar `404` en OpenAPI y ausencia de
  acceso a administracion y servicios internos.
- Probar rollback a los overlays `prod` antes de modificar el firewall.

1. **Completado en el pipeline `#2770049730`:** el certificado instalado en la
   Fase 4, su clave, el SAN, la vigencia y la referencia de `TLSStore/default`
   superaron `check_phase6_origin_tls`.
2. **Completado:** cambiar los paths de los perfiles productivos desde
   `overlays/prod` a `overlays/prod-domain`, revisar el diff renderizado y
   preparar el rollback estatico.
3. **Completado:** el job sobre `dc81ca9` aplico la migracion del realm y
   confirmo por discovery el issuer definitivo. Keycloak y el resto de
   `infra-prod` completaron sus rollouts.
4. Desplegar `blockchain-prod` solo si hay cambios o si falta el despliegue;
   verificar peers, bloques, contrato y categorias.
5. **Completado el 2026-08-19:** alinear mediante `kcadm` las URLs permitidas de
   `TrustNewsWeb`, confirmar el realm y verificar que `TrustNewsApi` permanece
   confidencial y sin cambios.
6. **Aceptacion funcional completada:** `apis-frontend-prod` actualizo Gateway,
   frontend, workers e Ingress. TLS, salud, dominio, ambos clientes OIDC,
   Gateway, OpenAPI y smoke tests Light y Blockchain tienen evidencia. El
   `404` autenticado de `/orders/list` corresponde a ausencia de datos.
7. **Limpieza completada; `ISSUE-002` resuelto:** la prueba independiente de
   `TrustNewsApi` devolvio `200` y se retiro la configuracion temporal de
   Windows. El valor por defecto eliminado no coincide con produccion y no
   requiere rotar `TrustNewsApi`. La revision de su posible alcance historico
   en tests es una recomendacion no bloqueante.

Criterio de salida: la aplicacion completa usa ya la configuracion final, pero
el origen todavia no acepta trafico de Internet.

#### Fase 8 - Cierre del perimetro y acceso administrativo (en curso)

Esta fase es el unico trabajo pendiente para cerrar `v0.0.12`.

**Estado del 2026-08-19 - Paso 8.1 completado**

- DNS de `assermetry.com` continua proxificado y Cloudflare mantiene el modo
  TLS `Full (strict)`.
- `Permanent mTLS - Keycloak administration` esta activa con accion `Block` en
  posicion 1. Su expresion cubre `/auth/admin`, `/auth/admin/*`,
  `/auth/realms/master` y `/auth/realms/master/*`, bloqueando certificados no
  verificados o revocados.
- `Temporary mTLS gate - assermetry.com` esta activa con accion `Block` en
  posicion 2 y cubre el resto del hostname con las mismas condiciones de
  certificado. No se registran identificadores internos de Cloudflare.
- Sin certificado cliente, `/`, `/auth/admin/master/console/` y el discovery
  del realm `TrustNews` devolvieron `403`. Security Events atribuyo la ruta
  administrativa a la regla permanente y las dos rutas publicas a la temporal.
- El PKCS#12 operativo se importo de nuevo en el almacen personal de Windows.
  El certificado esta vigente y conserva su clave privada. No declara una
  extension EKU, corrigiendo la evidencia documental anterior; Cloudflare lo
  acepto realmente en las tres rutas.
- Con el certificado presentado explicitamente mediante Schannel, las tres
  rutas devolvieron `522`: ambas reglas permitieron el trafico autenticado y el
  origen siguio inaccesible porque el firewall permanece cerrado.
- No se modificaron el firewall, Kubernetes, Traefik, DNS ni las reglas WAF.
  El siguiente paso es inventariar `externalTrafficPolicy` y la configuracion
  actual de cabeceras reenviadas antes de definir `trustedIPs` en Traefik.

**Estado del 2026-08-19 - Paso 8.2 completado**

- El cluster tiene un nodo, un pod Traefik preparado y un nodo con endpoint
  local de Traefik. K3s no configura `node-external-ip` ni mediante
  `config.yaml` ni mediante systemd, por lo que se acepto
  `externalTrafficPolicy: Local` para preservar la IP de origen.
- El perfil local conserva exclusivamente `k8s/traefik/values.yaml`. El perfil
  `traefik-prod` incorpora ademas `k8s/traefik/values-prod.yaml`, con
  `externalTrafficPolicy: Local`, `forwardedHeaders.insecure: false` y las 22
  redes IPv4 e IPv6 oficiales de Cloudflare vigentes durante la preparacion.
- El render del chart Traefik `41.0.2` confirmo el Service en modo `Local` y el
  argumento `websecure.forwardedHeaders.trustedIPs` con 22 entradas, sin
  modificar el perfil local.
- Se ejecuto una sola vez el pipeline manual con `PROFILE=traefik-prod` y
  finalizo correctamente. El rollout dejo un pod Traefik preparado y sin
  reinicios. No se desplegaron `infra-prod`, `apis-frontend-prod` ni
  `blockchain-prod`.
- La release Helm quedo `deployed`, usa el chart `41.0.2`, almacena 22 redes de
  confianza y su manifest contiene el argumento esperado. El ReplicaSet activo
  y el pod en ejecucion confirmaron `trustedIPs=true`, 22 entradas e
  `insecure=false`; `KC_PROXY_HEADERS` permanece en `xforwarded`.
- Una primera comprobacion de shell informo incorrectamente cero entradas. La
  release, el manifest, el ReplicaSet, el pod y el gate del pipeline confirmaron
  que fue un falso negativo del diagnostico y no deriva del despliegue.
- La prueba mTLS posterior mantuvo `522` en `/`, la consola administrativa y el
  discovery de `TrustNews`, confirmando que Traefik quedo preparado mientras el
  firewall continua cerrado. No se registran identificadores de pipeline,
  release, pod, IP ni certificados.
- El siguiente paso es anadir en Hetzner una unica regla inbound `TCP/443` con
  las mismas 22 redes oficiales de Cloudflare. No ampliar el origen a
  `0.0.0.0/0` ni `::/0`.

**Estado del 2026-08-19 - Paso 8.3 completado**

- Se descargaron nuevamente las redes oficiales de Cloudflare: 15 IPv4 y 7
  IPv6, 22 entradas en total. Hetzner permite ahora `TCP/443` exclusivamente
  desde esas redes; no se anadieron `0.0.0.0/0` ni `::/0`.
- Desde la red inicial, sin certificado cliente, `/`, la consola administrativa
  y el discovery de `TrustNews` devolvieron `403`. Presentando el certificado
  mTLS operativo, las tres rutas devolvieron `200`; el `522` previo desaparecio.
- El discovery mantuvo el issuer y los endpoints OIDC canonicos bajo
  `https://assermetry.com/auth/realms/TrustNews`.
- El intento de acceso directo a la IP del origen en `443/tcp`, `80/tcp` y
  `6443/tcp` devolvio `HTTP 000` y termino por timeout. Por tanto, la red de
  prueba no puede evitar Cloudflare. No se registran la IP ni datos del
  certificado.

**Estado del 2026-08-19 - Paso 8.4 completado**

- `GET /backend/auth/is-admin` sin mTLS fue bloqueado por Cloudflare con `403`.
  Con mTLS pero sin JWT alcanzo el Gateway y devolvio `403` con
  `Not authenticated`.
- Keycloak emitio un token `client_credentials` nuevo para `TrustNewsApi` y el
  Gateway lo acepto: `GET /backend/auth/is-admin` devolvio `200` e
  `is_admin:false`, resultado esperado para la cuenta de servicio. Un primer
  intento `401` se debio a la entrada del secreto y se descarta como incidencia
  de la aplicacion; el secreto no se regenero ni se registro.
- El operador confirmo en navegador el flujo OIDC sobre el dominio real con
  certificado mTLS: login, mantenimiento de sesion, refresh, roles, logout y
  redireccion funcionaron.
- Los smoke tests funcionales de los modos `LIGHT` y `BLOCKCHAIN` finalizaron
  correctamente desde la interfaz. No se registran usuarios, tokens, secrets,
  contenidos ni identificadores de orden.

**Estado del 2026-08-19 - Paso 8.5 completado**

- La revision posterior a los smoke tests mostro todos los pods preparados y
  en ejecucion, cero reinicios y todos los Deployments y StatefulSets
  disponibles.
- El nodo presento aproximadamente `5%` de CPU, `80%` de memoria usada y
  `1.7 GiB` disponibles. Habia `381 MiB` de swap ocupada, pero
  `MemoryPressure`, `DiskPressure` y `PIDPressure` estaban en `False`; el nodo
  permanecio `Ready`. El consumo de memoria queda como observacion a vigilar,
  no como bloqueo de esta fase.
- Traefik permanecio con una replica preparada, disponible y actualizada,
  `externalTrafficPolicy=Local` y un endpoint local preparado. El warning
  anterior `UnAvailableLoadBalancer` se considera transitorio y resuelto por el
  estado actual.
- Se observo un warning `DNSConfigForming` por superar el limite de nameservers;
  Kubernetes aplico tres resolvers y los flujos funcionales continuaron
  operativos. Queda como observacion no bloqueante para revision posterior.

**Control operativo de pausa introducido el 2026-08-19**

- La regla Cloudflare `Maintenance lock - assermetry.com` esta activa con accion
  `Block` y ocupa la primera posicion del ruleset.
- Su expresion cubre todo el hostname `assermetry.com`. Cuando esta activa debe
  bloquear tambien a clientes con certificado mTLS valido; se desactiva solo
  durante una ventana de pruebas autorizada.
- Las reglas `Permanent mTLS - Keycloak administration` y
  `Temporary mTLS gate - assermetry.com` permanecen activas por debajo. Por
  tanto, desactivar el lock no elimina la exigencia mTLS de la fase privada.
- Este lock detiene el trafico en el edge, pero no cierra por si mismo el
  `TCP/443` del firewall de Hetzner. Para una pausa prolongada, el cierre fuerte
  sigue siendo retirar exclusivamente esa regla inbound y restaurarla con las
  22 redes verificadas al reanudar.
- La posicion y activacion fueron confirmadas por el operador. Queda pendiente
  aportar una comprobacion HTTP posterior que atribuya el `403` a esta regla.

**Decision de acceso vigente desde el 2026-08-20**

- La regla `Temporary mTLS gate - assermetry.com` se retirara como requisito
  general de usuario durante el Paso 8.6.
- La regla `Permanent mTLS - Keycloak administration` permanecera activa para
  las rutas administrativas.
- Los usuarios se autenticaran mediante OIDC sin certificado cliente. No se
  habilita autorregistro: todas las identidades se provisionan expresamente.
- El lock de mantenimiento seguira siendo el mecanismo de pausa que bloquea el
  hostname completo.

**Siguiente gate - Paso 8.6 pendiente**

- Desactivar de forma controlada la regla mTLS general manteniendo activos el
  lock y la regla mTLS administrativa permanente.
- Desde una red alternativa y sin certificado cliente, validar frontend,
  discovery OIDC, login, refresh, logout, Light y Blockchain.
- Sin JWT, comprobar que las APIs protegidas rechazan la peticion. Con un JWT
  valido, comprobar que Gateway aplica usuario, roles y cliente esperados.
- Sin certificado administrativo, comprobar `403` en `/auth/admin` y
  `/auth/realms/master`; con un certificado administrativo valido, comprobar
  que se supera mTLS sin eludir la autenticacion de Keycloak.
- Revocar un certificado administrativo desechable y demostrar su rechazo. La
  prueba valida el ciclo de credenciales administrativas, no el acceso de
  usuarios.
- Comprobar que el lock bloquea todo el hostname incluso para usuarios y
  administradores validos, y dejarlo en el estado operativo decidido.
- Los reinicios controlados, las dependencias caidas y las pruebas funcionales
  sistematicas se trasladan a `v0.0.13` y versiones posteriores.

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: el rollout requerido de `traefik-prod` esta completado.
  No redesplegar componentes para la prueba desde una red alternativa.
- Externo: el firewall permite `443/tcp` solo desde las 22 redes comprobadas de
  Cloudflare. Mantener el lock durante el cambio, desactivar solo la regla mTLS
  general y conservar la regla mTLS administrativa.

**Pruebas**

- Sin certificado cliente: frontend y OIDC deben ser alcanzables; las APIs
  protegidas deben requerir JWT.
- Con credenciales OIDC validas: probar login, refresh, logout, roles y los
  flujos funcionales completos desde varias redes.
- En administracion: probar sin certificado, con certificado valido y con un
  certificado administrativo desechable revocado.
- Comprobar `Full (strict)`, issuer exacto y cabeceras reenviadas; verificar que
  la IP directa de Hetzner, `80/tcp`, `6443/tcp` y el resto de puertos no permiten
  evitar Cloudflare.
- Probar el lock como cierre general y la regla mTLS como cierre exclusivo de
  administracion.

Este es el primer momento en que se modifica el firewall de Hetzner:

```text
443/tcp  permitido solo desde rangos oficiales de Cloudflare
80/tcp   cerrado
2222/tcp restringido para SSH con clave
6443/tcp cerrado publicamente
resto    cerrado
```

1. **Completado:** Traefik confia cabeceras reenviadas solo desde proxies
   conocidos y `KC_PROXY_HEADERS=xforwarded` permanece en Keycloak.
2. **Completado desde la red inicial:** la IP directa de Hetzner no permite
   saltarse Cloudflare en `443/tcp`, `80/tcp` ni `6443/tcp`.
3. **Evidencia historica completada:** la regla mTLS general bloqueo sin
   certificado y permitio los flujos con certificado. Esa regla es transitoria
   y se retirara en el Paso 8.6.
4. **Completado bajo el gate historico:** login, refresh, logout, roles, client
   credentials y los modos Light y Blockchain funcionaron. Deben repetirse sin
   certificado cliente en el Paso 8.6.
5. **Completado:** el discovery OIDC publica exactamente:

   ```text
   https://assermetry.com/auth/realms/TrustNews
   ```

6. **Pendiente para cerrar la Fase 8:** retirar el mTLS general, probar desde
   una red alternativa el acceso OIDC de usuario, demostrar los rechazos sin
   JWT, validar y revocar un certificado administrativo desechable, verificar
   el lock y documentar el cierre operativo.

Criterio de salida: un usuario provisionado accede y completa los flujos OIDC
sin certificado cliente; las APIs protegidas rechazan peticiones sin JWT; la
administracion exige mTLS y autenticacion de Keycloak; un certificado
administrativo revocado es rechazado; el lock cierra el hostname completo y
queda una linea base estable para iniciar `v0.0.13`.

### Entregables de v0.0.12

- Dominio, DNS, TLS de origen, issuer, Ingress y clientes OIDC alineados.
- WAF, rate limits, observabilidad y restricciones administrativas activas.
- Origen accesible en `443/tcp` solo desde Cloudflare.
- Acceso funcional OIDC sin certificado cliente validado desde dos redes.
- mTLS administrativo y revocacion de un certificado administrativo
  desechable demostrados.
- Lock de mantenimiento comprobado como cierre de un solo paso.
- Linea base tecnica identificada para iniciar las pruebas funcionales.

### Fuera de alcance de v0.0.12

- Pruebas sistematicas y correccion funcional de GUI y API.
- Entrega de credenciales persistentes a clientes.
- Pilotos con datos reales o compromisos de servicio.
- Hardening completo, backups, restauracion y alta disponibilidad.
- GO/NO-GO de produccion y apertura publica.

---

## v0.0.13 - Estabilizacion funcional y demo repetible

### Objetivo

Probar de forma sistematica la GUI y la API, corregir problemas fundamentales y
obtener una demo privada reproducible con datos sinteticos. Durante esta version
se mantiene el lock fuera de las ventanas autorizadas y el mTLS solo en las
rutas administrativas. Los recorridos de usuario se prueban mediante OIDC sin
certificado cliente. No se entregan todavia accesos persistentes a clientes.

La version se organiza en cuatro fases propias: preparacion, pruebas de GUI,
pruebas de API y correccion con ensayos de demo.

### Fase 13.1 - Preparacion reproducible de pruebas

1. Crear un conjunto fijo de datos sinteticos, sin informacion de clientes.
2. Definir identidades pseudonimas de administrador de plataforma, usuario
   normal y cliente API para al menos dos organizaciones sinteticas.
3. Preparar casos Light y Blockchain con resultados comprobables.
4. Documentar la inicializacion, limpieza y repeticion de los datos de prueba.
5. Registrar version, configuracion y resultado de cada ejecucion sin guardar
   tokens, secretos ni datos personales.
6. Fijar una linea base de latencia, errores y consumo de recursos.

Criterio de salida: cualquier ejecucion de regresion parte del mismo estado y
produce evidencia comparable.

### Fase 13.2 - Pruebas funcionales de GUI

Probar manualmente y automatizar los recorridos criticos que sean estables:

- Login, mantenimiento de sesion, refresh, logout y sesion expirada.
- Navegacion, menus y control de acceso segun rol.
- Creacion, consulta y seguimiento de ordenes.
- Flujos completos Light y Blockchain.
- Aserciones, validaciones, evidencias, validadores y enlaces entre entidades.
- Filtros, busqueda, paginacion, cuotas y limites.
- Estados vacios, carga, error, timeout y reintento.
- Espanol e ingles.
- Chrome, Edge y Firefox, resoluciones habituales de portatil y una
  comprobacion movil basica.
- Ausencia de errores relevantes en consola y de mensajes que expongan trazas,
  secretos o detalles internos.

Criterio de salida: los recorridos principales son repetibles, los mensajes son
comprensibles y no quedan defectos bloqueantes para una demo.

### Fase 13.3 - Pruebas funcionales de API

Las pruebas se ejecutan por la via interna autorizada; OpenAPI permanece
bloqueado en el dominio productivo.

- Autenticacion valida, ausente, expirada y manipulada.
- Autorizacion de administrador, usuario y service account.
- Derivacion server-side del cliente a partir del token verificado o de una
  asociacion interna inmutable; nunca confiar en un `client_id` enviado por el
  frontend.
- Rechazo o ignorado seguro de cualquier intento de sustituir el `client_id` o
  identificador de organizacion en parametros, body o cabeceras.
- Usuario A del cliente 1 no puede leer, enumerar, modificar ni inferir datos
  del cliente 2.
- El aislamiento se aplica en listados, detalle, ordenes, aserciones,
  validaciones, evidencias, busquedas, exportaciones y enlaces indirectos.
- Un administrador de cliente no puede obtener privilegios de administrador
  global ni cambiar su asociacion de organizacion.
- Creacion, consulta y seguimiento de ordenes.
- Generacion de aserciones, evidencias y validaciones.
- Modos Light y Blockchain, recomendaciones, validadores y categorias.
- Consumo real de cuotas y comportamiento al agotarlas.
- Esquemas Pydantic, campos ausentes, parametros invalidos y tamaños limite.
- Respuestas `400`, `401`, `403`, `404`, `409`, `413`, `429` y `5xx`.
- Timeouts, reintentos y compatibilidad entre Gateway y servicios internos.
- Ausencia de datos, contadores, identificadores o metadatos de otro cliente en
  respuestas, errores y logs.

Se ampliaran los tests Python existentes hasta obtener una regresion de
contrato que pueda repetirse antes y despues de cada correccion.

Criterio de salida: los contratos criticos son estables, los errores son
coherentes y el aislamiento por organizacion se demuestra en todas las rutas,
sin depender de filtros o parametros proporcionados por el frontend.

### Fase 13.4 - Pruebas exploratorias, correccion y ensayos de demo

Cada ciclo sigue este orden: reproducir, registrar evidencia, clasificar,
corregir, repetir el caso afectado y ejecutar la regresion completa.

Clasificacion de defectos:

- **P0 bloqueante:** seguridad, corrupcion o perdida de datos, o plataforma
  inaccesible.
- **P1 critico para demo:** rompe autenticacion, ordenes, Light, Blockchain o
  cuotas; permite cambiar el cliente efectivo, acceder a datos de otra
  organizacion o elevar un administrador de cliente a administrador global.
- **P2 relevante:** degradacion visible con alternativa temporal aceptable.
- **P3 menor:** problema cosmetico o mejora no necesaria para demostrar el
  producto.

Durante esta fase existe congelacion funcional: se corrigen defectos, pero no
se incorporan X/Threads, reputacion, LLM dedicado, Cloudflare Tunnel ni otras
funcionalidades de roadmap.

El cierre incluye tres demos internas completas y consecutivas, una de ellas
desde otra red o equipo, comprobacion de observabilidad, limpieza de datos y
reactivacion final del lock.

### Criterio de salida de v0.0.13

- No quedan defectos P0 ni P1.
- Los P2 aceptados estan documentados y no rompen el recorrido principal.
- GUI y API superan una regresion reproducible.
- Login, Light y Blockchain funcionan en tres ejecuciones consecutivas.
- El aislamiento por organizacion se aplica server-side a listados, detalles,
  validaciones, evidencias, ordenes y busquedas; cualquier bypass es P1.
- La demo puede inicializarse, ejecutarse, limpiarse y cerrarse.
- Existe un guion de demo y una lista de limitaciones conocidas.
- La plataforma no se presenta como produccion ni como servicio HA.

---

## v0.0.14 - Beta cerrada por invitacion

### Objetivo

Permitir que un maximo de diez organizaciones externas evaluen la plataforma
durante un periodo definido con identidades pseudonimas y acceso OIDC
provisionado manualmente.

### Alcance minimo

- Una identidad pseudonima por evaluador y prohibicion de usuarios compartidos.
  El identificador sera opaco y no requerira nombre real ni correo personal.
- Keycloak solo almacenara el identificador tecnico, la organizacion y los roles
  imprescindibles. Logs y metricas no incluiran nombres, correos, tokens,
  credenciales ni otros datos personales evitables.
- Los usuarios acceden mediante OIDC sin certificado cliente. El mTLS se
  conserva exclusivamente para administracion.
- Un cliente confidencial distinto por organizacion cuando se habilite la API;
  no compartir el secret de `TrustNewsApi`.
- Validacion estricta de `aud`, `azp` o `client_id`, issuer, firma, vigencia y
  roles antes de entregar credenciales persistentes.
- Asociacion server-side e inmutable entre identidad y organizacion; Gateway,
  servicios y frontend no aceptan un `client_id` efectivo elegido por el usuario.
- Aislamiento entre organizaciones en listados, detalle, ordenes, aserciones,
  validaciones, evidencias, busquedas y exportaciones.
- Cuotas y limites por organizacion, auditoria minima, soporte y offboarding.
- Guia de evaluacion, tres tareas concretas y recogida estructurada de feedback.

### Limite operativo de la beta

- Un cliente equivale a una organizacion externa con evaluacion activa.
- Se permiten como maximo diez clientes activos simultaneamente; las identidades
  internas y los tenants sinteticos de prueba no consumen ese limite.
- No hay autorregistro ni alta automatica. Cada organizacion, identidad, rol y
  cuota se aprueba y provisiona manualmente.
- Al llegar al cliente numero diez se cierran las nuevas altas y se abre una
  lista de espera.
- Superar el limite requiere una decision deliberada, nueva revision de
  capacidad y aislamiento y actualizacion del roadmap; no se amplia de forma
  implicita.

### Politica minima de datos de evaluacion

- No introducir secretos, contrasenas, tokens, claves API ni otras credenciales.
- No introducir datos personales salvo necesidad y autorizacion expresas.
- No introducir informacion regulada o confidencial sin una autorizacion y un
  tratamiento acordados previamente.
- Cada evaluacion define fecha de fin, retencion y limpieza de sus datos.
- Los participantes aceptan que la beta puede interrumpirse y que los datos
  sinteticos o desechables no tienen recuperacion garantizada.
- Si un dato debe conservarse, se exige un backup minimo antes de incorporarlo.
  Los datos irremplazables no entran hasta demostrar una restauracion.

### Pruebas y criterio de salida

- Un usuario de la organizacion A no puede acceder ni inferir recursos de B en
  ninguna ruta, aunque manipule el `client_id` o enlaces directos.
- El backend resuelve la organizacion desde el token verificado o una asociacion
  server-side y aplica el mismo gate a GUI y API.
- Un administrador de cliente no puede elevarse a administrador global.
- Un usuario desactivado y un token incorrecto o caducado pierden acceso.
- Los limites no rompen login, refresh ni polling legitimos.
- El alta numero once queda bloqueada y se deriva a la lista de espera.
- Al menos dos evaluaciones externas se completan y existe un candidato a
  design partner con problema, metrica y posible piloto definidos.

---

## v0.0.15 - Piloto con design partners

### Objetivo

Validar durante cuatro a ocho semanas uno o dos casos de uso especializados con
alcance, datos, soporte y metricas acordados antes de desarrollar.

### Alcance minimo

- Caso de uso y criterio de exito firmados antes del piloto.
- Datos delimitados, procedimiento de exportacion y eliminacion y cadencia
  semanal de seguimiento.
- Pruebas de carga representativas, reinicios controlados y degradacion de una
  dependencia.
- Endurecimiento del canal CI, minimo privilegio de Geth y artefactos
  reproducibles en los componentes afectados.
- Aplicar el gate de persistencia antes de aceptar datos que deban conservarse.
- Medicion de latencia, coste por validacion, calidad percibida, uso repetido y
  carga de soporte.

### Gate de persistencia de datos

- Los datos sinteticos o desechables no requieren recuperacion garantizada; el
  participante debe conocer y aceptar el riesgo de perdida.
- Los datos de cliente que deban conservarse requieren un backup minimo antes
  de su incorporacion.
- Los datos irremplazables no pueden entrar hasta que exista una restauracion
  probada en un destino aislado.

La reputacion de validadores y el LLM dedicado solo se incorporaran si un caso
de uso validado los necesita. La integracion con X/Threads permanece en backlog
hasta demostrar que resuelve un flujo o canal comercial concreto.

Criterio de salida: al menos un piloto termina con evidencia de valor y existe
una decision explicita de continuar, cambiar el producto o detener ese caso de
uso.

---

## v0.0.16 - Preparacion de produccion

### Objetivo

Convertir la plataforma validada con clientes en un servicio operable. Es una
version de estabilizacion: no debe incorporar nuevas funcionalidades comerciales
salvo las imprescindibles para cerrar un riesgo de produccion.

### Alcance minimo

- Validacion estricta de identidad y autorizacion en todos los flujos.
- Confianza criptografica del pipeline y gates obligatorios.
- Minimo privilegio de RPC, `NetworkPolicy` y aislamiento interno.
- Imagenes y dependencias inmutables, inventario o SBOM y escaneo disponible.
- Requests, limits, capacidad, alertas y decision explicita sobre el nodo unico.
- SLO, RTO y RPO acordados.
- Backups cifrados externos y restauracion aislada demostrada.
- Rollback de aplicacion, configuracion y datos.
- Pruebas de carga, soak, fallos y recuperacion.
- Runbooks de incidentes, credenciales, certificados, soporte y bajas.
- Revision de privacidad, retencion, condiciones comerciales y seguridad.

Cloudflare Tunnel se considera una mejora opcional de esta version. Solo se
ejecutara si el analisis de riesgo y operacion justifica sustituir el inbound
actual; no constituye por si solo una version de producto.

Criterio de salida: no quedan riesgos de produccion sin resolver o aceptar
formalmente, y existe evidencia de restauracion, no solo ficheros de backup.

---

## v0.9.0 - Release Candidate

### Objetivo y criterio de salida

- Congelacion de funcionalidades.
- Ensayo completo de despliegue, migracion y rollback.
- Restauracion repetida y cronometrada.
- Regresion funcional, pruebas negativas de seguridad, carga y soak.
- Revision de observabilidad, soporte y procedimientos operativos.
- GO/NO-GO formal con responsables y excepciones registradas.

Cualquier fallo critico produce `NO-GO` y una nueva release candidate.

---

## v1.0.0 - Produccion controlada

Produccion no implica autorregistro ni acceso anonimo. El servicio puede seguir
siendo invite-only mediante identidades OIDC provisionadas; el mTLS permanece
reservado para administracion.

La version solo recibe `GO` cuando:

- Dos organizaciones especializadas han completado una evaluacion o piloto.
- Al menos una tiene un compromiso contractual de produccion.
- Existe un caso de uso repetible y una propuesta economica sostenible.
- Backup, restauracion, seguridad, capacidad y soporte estan aceptados.
- Se conocen responsables, horarios, escalado y limites del servicio.
- El rollback de apertura o cierre ha sido probado.

La regla mTLS general ya no forma parte del modelo de usuario. La proteccion
mTLS administrativa, WAF, lock, rate limits, logs y alertas permaneceran
activos.

---

## Plan transversal de despliegue, comunicacion y venta

### Secuencia de despliegue

1. Demo interna con datos sinteticos y operador presente.
2. Demo externa guiada con una identidad OIDC temporal y sin certificado
   cliente.
3. Evaluacion cerrada con credenciales persistentes y fecha de fin.
4. Piloto con alcance, metricas y soporte pactados.
5. Release candidate sin nuevas funcionalidades.
6. Produccion controlada para clientes contratados.

Antes de cada demo o evaluacion se congelan cambios durante 24 a 48 horas, se
activa el lock para desplegar, se ejecutan preflight, regresion y smoke, y solo
entonces se abre la ventana autorizada. Al terminar se cierra el acceso, se
revocan credenciales temporales y se limpian los datos previstos.

### Comunicacion y material comercial

- One-pager centrado en un problema y un perfil de cliente concretos.
- Presentacion breve, guion de demo y guia de evaluacion.
- Documento que explique que valida Assermetry y que no garantiza.
- Ficha de seguridad y tratamiento de datos, incluyendo retencion, limpieza y
  ausencia de recuperacion garantizada para datos desechables de beta.
- FAQ y limitaciones conocidas.
- Propuesta de piloto con alcance, duracion, metricas, soporte y precio.

El proceso comercial sera dirigido y no un lanzamiento publico:

```text
descubrimiento -> demo guiada -> evaluacion -> design partner -> piloto -> produccion
```

Se mediran tiempo hasta la primera validacion util, finalizacion de tareas,
utilidad percibida, repeticion, coste y latencia por validacion, carga de soporte
y conversion entre etapas. El mensaje comercial se centrara en trazabilidad,
evidencia, diversidad de validadores y auditabilidad, no en afirmar que la
blockchain garantiza la verdad.

---

## Anexo A - Requisitos tecnicos diferidos del plan anterior

Los bloques siguientes conservan su numeracion original para trazabilidad. Ya
no forman parte de `v0.0.12`: alimentan principalmente `v0.0.16`, el GO/NO-GO
de `v0.9.0` y, en su caso, `v1.0.0`.

### A.1 - Hardening interno, identidad y cadena de suministro

**Motivo y objetivo**

La revision de seguridad posterior al cierre considera adecuado el perimetro,
pero declara `NO-GO` para una produccion inmediata. Esta fase
corrige los hallazgos que no estaban asignados a una fase posterior: validacion
incompleta de tokens, confianza debil del canal CI, superficie RPC de Geth,
ausencia de segmentacion entre pods, artefactos no inmutables y riesgo
operativo del nodo unico.

Durante toda la fase deben permanecer disponibles el lock
`Maintenance lock - assermetry.com` y la proteccion mTLS administrativa
permanente. La regla mTLS general no forma parte del modelo de usuario. Cada
bloque se valida fuera de produccion y
se despliega por separado, con diff renderizado, copia de la configuracion
anterior y rollback identificado.

**Fuera de alcance de esta fase**

- Backups cifrados y restauraciones: pertenecen a `v0.0.16`, o se adelantan a
  `v0.0.15` si el piloto incorpora datos que deban conservarse. Los datos
  irremplazables no entran sin una restauracion probada.
- Red alternativa y revocacion del certificado administrativo desechable:
  pertenecen al cierre de la Fase 8. Las dependencias caidas y la recuperacion
  progresan desde `v0.0.13`.
- Sustituir la exposicion del origen por Cloudflare Tunnel es una mejora
  opcional de `v0.0.16`.
- La existencia de estas tareas posteriores no permite cerrar esta fase ni
  declarar `GO` antes de corregir los controles incluidos a continuacion.

**Bloque A.1.1 - Inventario reproducible y plan de cambio**

1. Congelar una linea base de manifests renderizados, imagenes y digests,
   configuracion efectiva del Gateway, argumentos de cada nodo Geth, grafo de
   jobs del pipeline, Services y flujos de red entre namespaces.
2. Inventariar los metodos JSON-RPC usados realmente por la aplicacion y
   confirmar que las transacciones se firman localmente antes de retirar
   `personal`, desbloqueos o APIs auxiliares.
3. Capturar tokens de prueba sin registrar su valor y anotar solo `iss`, `aud`,
   `azp` o `client_id`, tipo de flujo y roles esperados para `TrustNewsWeb` y
   `TrustNewsApi`.
4. Identificar para cada bloque el perfil de despliegue, recursos afectados,
   prueba de salud y procedimiento exacto para volver a la revision anterior.
5. Mantener secretos, tokens, claves privadas, kubeconfig y huellas fuera del
   repositorio y de los logs del pipeline.

Criterio de salida A.1.1: existe una matriz de flujos y consumidores que permite
endurecer sin asumir dependencias, y cada cambio tiene rollback verificable.

**Bloque A.1.2 - Validacion estricta de JWT en Gateway**

1. Definir `TrustNewsApi` como audiencia del recurso protegido y configurar en
   Keycloak el mapper o client scope necesario para que los tokens validos de
   los flujos web y `client_credentials` contengan esa audiencia.
2. Mantener la validacion de firma, algoritmo, `iss`, expiracion y vigencia, y
   activar la validacion de `aud`; eliminar
   `options={"verify_aud": False}`.
3. Validar tambien el cliente presentador mediante `azp` o `client_id` contra
   una lista explicita. No aceptar tokens de cualquier otro cliente del realm
   aunque su firma e issuer sean validos.
4. Aplicar autorizacion por rol y tipo de principal despues de validar el
   token. Las rutas de usuario y las de service account no deben adquirir
   permisos entre si por accidente.
5. No registrar headers ni claims antes de verificarlos. Tras la validacion,
   registrar solo campos operativos permitidos y no tokens, secretos, PII ni
   claims arbitrarios controlados por el cliente.
6. Conservar una sola implementacion de `/auth/is-admin` y eliminar la ruta
   duplicada sin cambiar su contrato.
7. Probar positivamente login web, refresh, roles y
   `TrustNewsApi client_credentials`; probar negativamente audiencia ausente o
   incorrecta, `azp` no permitido, token de otro cliente del mismo realm,
   issuer incorrecto, expiracion, firma alterada y ausencia de token.

Criterio de salida A.1.2: solo se aceptan tokens emitidos para la API y por un
cliente autorizado; los smokes Light y Blockchain siguen funcionando y los
logs no contienen datos JWT sin verificar.

**Bloque A.1.3 - Confianza criptografica del pipeline**

1. Sustituir `--insecure-skip-tls-verify=true` por la CA real del API de K3s,
   entregada como variable protegida de tipo fichero o extraida de un kubeconfig
   protegido. Configurar `tls-server-name` solo si el endpoint del tunel no
   coincide con un SAN, usando un nombre que el certificado incluya realmente.
2. Guardar la clave publica o la entrada `known_hosts` esperada del servidor en
   una variable protegida y verificarla antes de abrir el tunel. No usar la
   salida de `ssh-keyscan` obtenida en esa misma conexion como raiz de
   confianza.
3. Forzar `StrictHostKeyChecking=yes` y un `UserKnownHostsFile` dedicado; ante
   CA ausente, certificado invalido o clave SSH distinta, el pipeline debe
   fallar cerrado.
4. Revisar los `needs.optional`: un gate de seguridad requerido por el perfil
   seleccionado no puede omitirse. La opcionalidad solo se conserva cuando el
   job no existe por sus `rules` y otro gate obligatorio demuestra el mismo
   requisito.
5. Probar el grafo para cada perfil productivo y ejecutar pruebas negativas con
   CA incorrecta, nombre TLS no valido y clave SSH distinta. Ninguna debe llegar
   a ejecutar `kubectl`, Helm o Skaffold.

Criterio de salida A.1.3: el runner autentica tanto el host SSH como el API de
Kubernetes, no hay saltos TLS inseguros y los gates aplicables son obligatorios.

**Bloque A.1.4 - Minimo privilegio en los RPC de Geth**

1. Separar las necesidades de bootnode, miner y endpoint RPC. Publicar por HTTP
   o WebSocket unicamente los modulos y metodos que consume la aplicacion.
2. Retirar `admin` y `personal` de `--http.api` y `--ws.api`. Deshabilitar
   WebSocket si no tiene consumidores y restringir `--http.vhosts` a los
   nombres internos realmente usados.
3. Eliminar `--http.corsdomain=*`; dejar CORS deshabilitado para llamadas
   servidor a servidor o fijar solo los origenes imprescindibles.
4. Eliminar `--allow-insecure-unlock` y cualquier desbloqueo remoto. Si el
   minado o una operacion heredada necesita una cuenta desbloqueada, migrar ese
   uso a IPC local, firma previa de transacciones o un signer dedicado antes de
   retirar el flag; no romper el consenso eliminandolo sin esta prueba.
5. Mantener los Services como `ClusterIP`, sin Ingress ni NodePort para RPC, y
   limitar sus consumidores mediante las politicas del bloque A.1.5.
6. Verificar desde un pod autorizado sincronizacion, peers, bloques, contrato,
   categorias y transacciones firmadas. Desde un pod no autorizado, y para los
   metodos `admin_*`, `personal_*` y desbloqueo, esperar denegacion.

Criterio de salida A.1.4: no quedan APIs administrativas, comodines de origen o
host ni desbloqueo inseguro accesibles por RPC; Blockchain conserva su
funcionalidad.

**Bloque A.1.5 - Segmentacion interna con NetworkPolicy**

1. Confirmar mediante una politica canario que el CNI de K3s aplica
   `NetworkPolicy`; no desplegar un `default-deny` si el plugin no lo hace.
2. Etiquetar namespaces y pods de forma estable y construir la matriz minima de
   origen, destino, protocolo y puerto. Usar selectores, no IP de pods.
3. Aplicar por namespace, de forma progresiva, denegacion por defecto de
   ingress y egress. Autorizar explicitamente DNS hacia CoreDNS antes de cerrar
   egress.
4. Permitir solo los flujos necesarios: Traefik hacia frontend, Gateway y
   Keycloak; Gateway y APIs hacia sus dependencias; Keycloak hacia PostgreSQL;
   workers hacia MongoDB, Kafka, IPFS y los RPC concretos; y los flujos de
   observabilidad requeridos.
5. Aislar especialmente Geth, MongoDB, PostgreSQL, Kafka, IPFS, Kafdrop,
   Mongo Express, Grafana y servicios administrativos. Un frontend o pod de
   prueba no debe alcanzar directamente datos, consolas ni RPC.
6. Tras cada namespace, ejecutar smokes funcionales y pruebas negativas desde
   un pod sin etiquetas autorizadas. Ante fallo, revertir solo el bloque de
   politicas recien aplicado y completar la matriz antes de reintentarlo.

Criterio de salida A.1.5: existe `default-deny` efectivo con allowlists minimas,
la aplicacion funciona y se demuestra que un pod no autorizado no puede moverse
lateralmente hacia servicios sensibles.

**Bloque A.1.6 - Imagenes y artefactos inmutables**

1. Inventariar imagenes de runtime, init containers, bases de Dockerfile y
   charts. Eliminar `latest`, referencias sin version y tags que puedan cambiar,
   incluidos `busybox`, IPFS y las bases de aplicacion.
2. Fijar dependencias externas por digest y conservar una version legible como
   metadato. Fijar Keycloak a la version exacta probada y su digest; mantener el
   chart de Traefik versionado y registrar tambien los digests renderizados.
3. Publicar las imagenes propias con digest inmutable y hacer que el despliegue
   productivo consuma el digest construido por el pipeline, no un tag
   reutilizable.
4. Generar inventario o SBOM y ejecutar el escaneo disponible antes del
   despliegue. Definir un proceso controlado de actualizacion que cambie version
   y digest de forma revisable.
5. Anadir un gate sobre el render productivo que rechace `latest`, imagenes sin
   tag y, para los componentes exigidos por la politica, referencias sin digest.
6. Repetir render, despliegue y rollback demostrando que una misma revision
   resuelve siempre los mismos artefactos.

Criterio de salida A.1.6: el inventario productivo identifica exactamente cada
binario desplegado y el pipeline impide introducir referencias flotantes.

**Bloque A.1.7 - Capacidad y disponibilidad declaradas**

1. Completar `requests` y `limits` donde falten, revisar memoria, swap,
   almacenamiento y margen necesario para rollouts, y fijar alertas antes de
   alcanzar presion del nodo.
2. Medir un rollout y los smokes completos con la carga actual. No continuar si
   aparecen `MemoryPressure`, OOM, evicciones, falta de disco o degradacion
   persistente.
3. Documentar que una replica en un unico nodo mejora recuperacion de proceso,
   pero no proporciona alta disponibilidad. Definir SLO, RTO y tolerancia real
   a la perdida del nodo.
4. Si el servicio debe sobrevivir al fallo de un nodo, ampliar a varios nodos y
   almacenamiento replicado o servicios de datos externos antes del `GO`. Si se
   mantiene nodo unico, registrar la aceptacion explicita del SPOF y no
   presentar la plataforma como HA. Esto no sustituye los backups del bloque
   A.4 de `v0.0.16`.
5. Resolver o aceptar expresamente el warning `DNSConfigForming` y dejar
   evidencia de salud posterior al ultimo rollout.

Criterio de salida A.1.7: existe margen operativo medido y una decision explicita
sobre disponibilidad; los riesgos no se deducen del numero de pods preparados.

**Orden de despliegue y rollback**

1. Preparar y validar localmente Gateway, tests JWT, manifests, politicas y
   gates de render.
2. Corregir primero la confianza del pipeline, porque los cambios posteriores
   no deben desplegarse por un canal que no autentica sus extremos.
3. Desplegar por separado Gateway/Keycloak, Geth, `NetworkPolicy` e imagenes
   fijadas. No agrupar todos los cambios en una unica ventana.
4. Tras cada bloque, comprobar rollouts, reinicios, eventos, recursos y smokes
   OIDC, API, Light y Blockchain. Mantener el lock durante las comprobaciones.
5. Si falla un bloque, volver a su revision anterior sin retirar el mTLS
   administrativo, abrir el firewall ni retirar las politicas ya aceptadas.

**Criterio de salida global**

El bloque A.1 solo se considera cubierto cuando se aporta evidencia de todos
los criterios A.1.1 a A.1.7, las pruebas negativas fallan cerrado y los flujos funcionales siguen
operativos. Deben cumplirse, como minimo, estas condiciones:

- Gateway valida `aud` y el presentador autorizado, y no registra claims sin
  verificar ni mantiene la ruta administrativa duplicada.
- CI valida CA y nombre del API de Kubernetes, fija la clave SSH esperada y no
  permite omitir gates de seguridad aplicables.
- Geth no expone `admin`, `personal`, desbloqueo inseguro ni comodines de CORS o
  virtual hosts.
- Las `NetworkPolicy` bloquean movimiento lateral y permiten solo los flujos
  inventariados.
- Produccion usa artefactos inmutables y el gate rechaza referencias flotantes.
- Capacidad y disponibilidad tienen evidencia y una decision de riesgo
  documentada.
- Cloudflare conserva el lock de mantenimiento y la regla mTLS administrativa.

Cualquier incumplimiento mantiene el estado `NO-GO` y bloquea `v0.9.0`.

### A.2 - Checklist GO/NO-GO reutilizable para produccion

Este gate se reutilizara y actualizara en `v0.9.0`; no es una fase de
`v0.0.12`.

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar ni cambiar configuracion.
- Externo: no cambiar el modelo de acceso; esta fase solo decide `GO` o `NO-GO`.

**Pruebas**

- Repetir sin certificado cliente el smoke OIDC de usuario, Light, Blockchain,
  cuotas y dependencias.
- Repetir pruebas negativas sin JWT, contra la IP directa, sin certificado en
  rutas administrativas, OpenAPI y servicios internos.
- Revisar evidencias de rollback, renovacion TLS, WAF, rate limits,
  logs y alertas; comprobar que el equipo puede activar el lock.

La produccion recibe `GO` solo si:

- El perimetro privado y el bloque A.1 estan cerrados con sus evidencias y sin
  excepciones abiertas.
- DNS, proxy Cloudflare y TLS `Full (strict)` son correctos.
- El origen solo admite rangos Cloudflare y no responde por acceso directo.
- Issuer, redirects, login, refresh, logout y client credentials funcionan.
- Modos Light y Blockchain, cuotas y servicios dependientes funcionan.
- Administracion, OpenAPI y servicios internos permanecen bloqueados.
- El rollback de la apertura ha sido probado.
- WAF, rate limiting, logs y alertas estan activos.
- El equipo conoce y ha probado el lock general y el acceso mTLS administrativo.

Cualquier incumplimiento produce `NO-GO`; no se compensa retirando controles.

### A.3 - Procedimiento de apertura anterior (sustituido)

El procedimiento anterior aplazaba la retirada del mTLS general hasta una
apertura publica. Queda sustituido por la decision de la Fase 8: los usuarios
provisionados acceden mediante OIDC sin certificado, el mTLS protege solo la
administracion y el lock de mantenimiento cierra todo el hostname. Esta seccion
no contiene pasos ejecutables y se conserva unicamente para explicar el cambio
de criterio.

### A.4 - Backups y recuperacion para v0.0.16

**Estado**

- Posicion en el plan: **antes de `v0.9.0` y de cualquier produccion real**.
- Estado global de la fase: **pendiente; no implementada**.
- Las pruebas funcionales actuales no implican que los backups ni los ensayos de
  restauracion se hayan realizado.

**Despliegue**

- Kubernetes local: si, pero solo como destino aislado para ensayar la
  restauracion; no sustituir el entorno local de desarrollo en uso.
- Kubernetes Hetzner: no redesplegar la aplicacion. Obtener los backups del
  entorno real. Si se prueba alli una restauracion, usar recursos temporales y
  PVC o namespaces distintos de produccion.

**Pruebas**

- Verificar cifrado, hash, fecha, tamaño y legibilidad de cada backup fuera del
  cluster.
- Restaurar MongoDB y PostgreSQL de Keycloak en el destino aislado y comprobar
  recuentos, usuarios, clientes OIDC y login.
- Restaurar o verificar genesis, keystores, contrato, ABI y categorias; comparar
  direccion y bytecode con la linea base.
- Ensayar rollback de manifests e imagenes y documentar tiempo, comandos y
  resultado. Nunca probar una restauracion destructiva sobre los PVC activos.

1. Crear y probar restauraciones de MongoDB y PostgreSQL de Keycloak.
2. Respaldar genesis, keystores, contrasenas Ethereum, direccion y ABI del
   contrato, categorias y configuracion de nodos.
3. Mantener una copia cifrada fuera de Hetzner de secrets Kubernetes, variables
   CI/CD, claves API, claves Ethereum, secrets OIDC y credenciales Cloudflare.
4. Ensayar el rollback de manifests e imagenes.

Criterio de salida: existe evidencia de restauracion, no solo ficheros de backup.

### A.5 - Invariantes que permanecen fuera de alcance

- Renombrar el realm `TrustNews` o los clientes OIDC existentes.
- Publicar bases de datos, Kafka, IPFS API, RPC, paneles o APIs administrativas.
- Añadir `www.assermetry.com` sin una redireccion canonica probada.
- Sustituir los runbooks operativos por este documento de version.

---

## Anexo B - Cloudflare Tunnel opcional para v0.0.16

### Objetivo

Sustituir la entrada publica desde las redes compartidas de Cloudflare por un
Named Tunnel iniciado desde el cluster. El estado final no requiere ningun
puerto web inbound en Hetzner:

```text
Cliente
    | HTTPS, WAF y lock; mTLS solo para administracion
    v
Cloudflare Edge
    | Cloudflare Tunnel iniciado en sentido saliente
    v
cloudflared
    | HTTPS interno con validacion del certificado de origen
    v
Traefik ClusterIP
    +-- /         -> frontend
    +-- /backend  -> Gateway
    +-- /auth     -> Keycloak
```

El contrato publico no cambia. Se mantienen `https://assermetry.com`, el realm
`TrustNews`, los clientes `TrustNewsWeb` y `TrustNewsApi`, el issuer, los
redirects, las rutas y las reglas WAF. Cloudflare Tunnel esta disponible en el
plan Free y no exige un plan Cloudflare Access de pago para publicar el
hostname.

Referencias:

- https://developers.cloudflare.com/tunnel/
- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/
- https://developers.cloudflare.com/tunnel/advanced/origin-parameters/

### Estado, alcance y esfuerzo

- Estado: **planificada; no implementada ni autorizada para despliegue**.
- No forma parte de la Fase 8 ni de la estabilizacion `v0.0.13`. Solo se
  iniciara en `v0.0.16` si existe una decision explicita que justifique el
  cutover y evita mezclar cambios de perimetro con pruebas funcionales.
- Esfuerzo estimado: **12 a 18 horas tecnicas**, normalmente repartidas entre
  dos o tres ventanas para permitir observacion y rollback.
- Alcance de codigo: moderado, aproximadamente 6 a 10 ficheros de
  infraestructura, CI/CD y documentacion.
- No se esperan cambios en frontend, APIs, logica funcional, modelos, Keycloak,
  realm, clientes OIDC, issuer ni base de datos.
- La mayor complejidad es conservar de forma segura la IP real del cliente, los
  rate limits y la confianza de cabeceras reenviadas.

### Invariantes de seguridad

1. No almacenar el token del tunel, credenciales ni identificadores internos en
   Git, logs, artifacts o documentacion.
2. No usar `noTLSVerify`. El salto `cloudflared -> Traefik` debe validar la
   raiz Origin CA y `originServerName=assermetry.com`.
3. No activar `forwardedHeaders.insecure`. Traefik debe confiar unicamente en
   el origen interno elegido para los conectores.
4. El lock de mantenimiento y la regla mTLS administrativa permanecen
   disponibles durante toda la migracion.
5. No retirar el inbound `TCP/443` hasta que el tunel haya superado las pruebas
   extremo a extremo y exista un rollback preparado.
6. Tras el cierre, no dejar rutas alternativas por LoadBalancer, NodePort,
   hostPort, IP publica o DNS historico.
7. Dos replicas de `cloudflared` reducen el riesgo de fallo del proceso, pero en
   el cluster actual de un solo nodo no aportan alta disponibilidad del host.

### Decisiones tecnicas previas

1. Desplegar `cloudflared` como workload dedicado: ServiceAccount sin
   privilegios, Secret externo para el token, dos replicas, probes, limites de
   recursos, `securityContext` restrictivo y `--no-autoupdate`.
2. Mantener Traefik como unico router para conservar `/`, `/backend` y `/auth`.
   El tunel no debe conectar directamente a cada API ni eludir middlewares,
   limites de cuerpo, observabilidad o reglas Ingress.
3. Usar el Service interno HTTPS de Traefik. Montar en `cloudflared` solo la
   raiz Origin CA necesaria para verificar el certificado; no montar su clave.
4. Elegir y probar una estrategia para `X-Forwarded-For` y
   `CF-Connecting-IP`. Si se confia en un CIDR de pods, compensarlo con
   aislamiento y NetworkPolicy, verificando antes su enforcement real en K3s.
5. Mantener inicialmente el LoadBalancer de Traefik para rollback. Tras el
   periodo de observacion, cambiar produccion a `ClusterIP` y retirar
   `externalTrafficPolicy` y las allowlists que ya no correspondan.
6. Mantener el perfil local sin `cloudflared` y sin dependencias de Cloudflare.

### Plan de implementacion

1. **Linea base y rollback**
   - Exportar de forma segura DNS, WAF, firewall, Helm y Traefik sin registrar
     IP, tokens ni identificadores sensibles.
   - Capturar los checks actuales: frontend y OIDC sin certificado, API sin JWT
     rechazada, API autenticada aceptada, administracion sin mTLS `403`, issuer
     exacto y smokes Light/Blockchain.
   - Preparar el orden de rollback antes de desplegar el conector.

2. **Configuracion de Cloudflare**
   - Crear un Named Tunnel sin asociar aun el hostname productivo.
   - Crear el token con el menor alcance disponible y guardarlo fuera de Git.
   - Definir el servicio HTTPS hacia Traefik con hostname y CA verificados.
   - No crear un hostname de prueba sin lock, OIDC y una proteccion
     administrativa equivalente a la actual.

3. **Manifests de Kubernetes**
   - Crear workload, ConfigMap no sensible, referencia al Secret, probes,
     recursos, afinidad y seguridad de `cloudflared`.
   - Crear NetworkPolicy solo despues de comprobar que K3s la aplica.
   - Incluir dos replicas y demostrar que reiniciar una no interrumpe el tunel.

4. **Traefik y cabeceras**
   - Añadir valores productivos especificos para el camino del tunel.
   - Conservar `forwardedHeaders.insecure=false`.
   - Limitar `trustedIPs` al origen interno definido para `cloudflared`.
   - Verificar en logs y rate limits la IP real y que otro pod no puede
     falsificarla.

5. **CI/CD y observabilidad**
   - Añadir un perfil productivo y gates de render sin afectar al perfil local.
   - Validar replicas, probes, Secret referenciado, TLS, ausencia de
     `noTLSVerify` y configuracion segura de cabeceras.
   - Integrar logs y metricas de `cloudflared` y alertar si no hay conectores
     saludables.

6. **Pre-cutover**
   - Desplegar `cloudflared` sin modificar todavia el registro A productivo.
   - Confirmar en Cloudflare que las conexiones estan saludables.
   - Mantener el lock activo y guardar el estado DNS anterior para rollback.

7. **Cutover protegido**
   - Asociar `assermetry.com` al Named Tunnel durante una ventana controlada.
   - Desactivar solo el lock; mantener OIDC para usuarios y mTLS
     administrativo.
   - Probar frontend, discovery, login, refresh, logout, roles,
     `TrustNewsApi`, Gateway, Light, Blockchain, polling, limites e IP real.

8. **Cierre del origen**
   - Reactivar el lock mientras se cambia el perimetro.
   - Retirar en Hetzner la regla inbound `TCP/443` con las 22 redes.
   - Cambiar Traefik a `ClusterIP` tras el periodo de rollback rapido.
   - Confirmar que `443`, `80` y `6443` directos no responden mientras el
     dominio funciona por el tunel.

9. **Soak y cierre**
   - Probar reinicio de una replica y perdida y recuperacion de conectores.
   - Repetir smokes y revisar errores, latencia, memoria y reinicios.
   - Probar el rollback completo antes de cerrar la version.

### Rollback

1. Activar el lock de mantenimiento.
2. Restaurar Traefik como LoadBalancer con los valores previos.
3. Restaurar `TCP/443` en Hetzner con las 22 redes verificadas.
4. Restaurar el registro DNS proxificado anterior.
5. Confirmar frontend y discovery sin certificado, Gateway con JWT y
   administracion mediante mTLS.
6. Desactivar el lock solo si las comprobaciones son correctas.
7. Retirar el tunel despues de recuperar el camino anterior, nunca antes.

El rollback no cambia issuer, Keycloak, clientes, redirects ni aplicacion.

### Estimacion detallada

| Trabajo | Horas |
| --- | ---: |
| Diseño final, inventario y rollback | 1-2 |
| Manifests de `cloudflared` y NetworkPolicy | 3-4 |
| Traefik, TLS interno y cabeceras | 2-4 |
| Tunnel, DNS y secretos en Cloudflare | 1-2 |
| CI/CD, observabilidad y documentacion | 1-2 |
| Cutover, pruebas de fallo y rollback | 4 |
| **Total estimado** | **12-18** |

La horquilla superior es probable si NetworkPolicy o la IP real requieren
ajustes. Una migracion basica puede funcionar antes, pero no termina hasta
demostrar cabeceras seguras, cierre del origen y rollback.

### Criterio de salida

- `assermetry.com` funciona exclusivamente por el Named Tunnel.
- Hetzner no admite ningun puerto web inbound.
- Traefik no expone un LoadBalancer publico innecesario.
- No se usa `noTLSVerify` ni confianza indiscriminada de cabeceras.
- WAF, mTLS administrativo, autenticacion, rate limits y observabilidad se
  conservan.
- Frontend, OIDC, API, Light y Blockchain superan las pruebas.
- La perdida de un conector y el rollback completo estan demostrados.
