# Versiones del despliegue Kubernetes

Este documento describe el objetivo, alcance, dependencias, orden de despliegue
y criterios de aceptacion de cada version de la plataforma Kubernetes de
Assermetry. Los comandos operativos se mantienen en:

- [`k8s-common.md`](deploy/k8s-common.md): configuracion compartida.
- [`skaffold-local.md`](deploy/skaffold-local.md): despliegue local con `kind`.
- [`skaffold-server.md`](deploy/skaffold-server.md): despliegue productivo en Hetzner.
- [`issues.md`](issues.md): incidencias detectadas y propuestas de mejora por version.

---

## v0.0.12 - Exposicion controlada de Assermetry en Internet

### Objetivo

Publicar la instalacion de Hetzner en `https://assermetry.com`, conservando la
posibilidad de desplegar y validar la misma aplicacion en local.

La apertura al publico se realizara en la Fase 9. Antes de ella, el servicio
completo debe funcionar en el dominio definitivo y el acceso HTTPS por
`443/tcp` debe estar restringido mediante un certificado personal mTLS.
Desactivar la regla mTLS general sera el unico cambio necesario para abrir los
flujos de usuario; la asociacion mTLS, el certificado cliente y la regla
administrativa permanente se conservaran.

### Estado actual

La version `v0.0.12` ha cerrado la **Fase 0 - Inventario y linea base**, la
**Fase 1 - Adaptacion de aplicacion y manifests** y la **Fase 2 - Dominio,
Cloudflare y DNS**. En la Fase 2 se completaron la configuracion tecnica, las
comprobaciones externas y la verificacion del 2FA en Porkbun y Cloudflare. La
**Fase 3 - Acceso privado por certificado cliente** esta cerrada: la emision,
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
requiere vigilancia durante el despliegue definitivo. La **Fase 6 - Despliegue
definitivo todavia cerrado** esta en curso. El pipeline GitLab `#2770049730`
sobre el commit `4a7e9185` completo `build`, el gate TLS, `infra-prod` y el
bootstrap de MongoDB; el rollback no se ejecuto. Una repeticion sobre el commit
`77e189ef` confirmo el rollout de Keycloak y sus valores `KC_HOSTNAME_*`, pero
fallo al consultar discovery sin las cabeceras del proxy. La prueba se ha
corregido y debe repetirse antes de `apis-frontend-prod`. El firewall permanece
cerrado. La **Fase 10 - Backups y recuperacion** queda pendiente y sera la
ultima fase en ejecutarse.
Hetzner esta en un estado transitorio controlado: Keycloak usa ya las URLs del
dominio definitivo, mientras Gateway e Ingress conservan `prod` hasta el
segundo pipeline. El dominio publico todavia no esta activado.

Configuracion activa:

```text
Local:          https://localhost:7443
Hetzner/tunel:  https://localhost:9443 (Ingress actual; Keycloak usa dominio final)
Cloudflare:     https://assermetry.com (proxy activo; origen cerrado)
```

Los perfiles locales continúan usando `overlays/local`. `infra-prod` referencia
el overlay `prod-domain` de Keycloak y ya fue desplegado por el pipeline
`#2770049730`. `apis-frontend-prod` referencia los overlays `prod-domain` de
Gateway e Ingress, pero ese segundo perfil aun no se ha desplegado: los Ingress
activos conservan `host: localhost` y el Gateway conserva el issuer de tunel.
El firewall permanece cerrado.

### Contrato publico de la version

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

### Arquitectura de produccion

```text
Navegador o cliente
        |
        | HTTPS + certificado cliente obligatorio durante las pruebas
        v
Cloudflare Proxy / Application Security mTLS / WAF
        |
        | HTTPS Full (strict)
        v
Firewall Hetzner: 443 solo desde rangos de Cloudflare
        |
        v
Traefik (K3s)
        +-- /         -> frontend
        +-- /backend  -> Gateway
        +-- /auth     -> Keycloak
```

Hay dos certificados con finalidades diferentes:

- El certificado TLS del origen autentica `assermetry.com` y cifra la conexion
  entre Cloudflare y Traefik.
- El certificado cliente mTLS, emitido por la CA gestionada de Cloudflare,
  autoriza temporalmente a cada tester antes de la apertura publica.

Tener solo el certificado TLS del servidor no restringe el acceso. El gate
privado previo a la apertura requiere una regla WAF de Application Security que
rechace cualquier cliente sin un certificado mTLS valido.

### Regla de oro de seguridad

- El acceso por mTLS debe estar activo antes del primer momento en que
  `443/tcp` sea alcanzable desde Internet, en la **Fase 7**, y mantenerse hasta
  la apertura publica de la **Fase 9** tras el GO/NO-GO. Despues de la apertura,
  mTLS sigue siendo obligatorio en `/auth/admin` y
  `/auth/realms/master`.
- No se debe abrir `443/tcp` al trafico publico general hasta que la Fase 7 haya
  sido probada con Cloudflare y mTLS.
- Si aparece una incidencia durante la apertura, el rollback inmediato consiste en
  reactivar la politica mTLS sin cambiar DNS, Kubernetes, Keycloak ni
  certificados.

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

1. No se debe confundir TLS con control de acceso. Antes de abrir `443/tcp`, el
   certificado del origen y el mTLS de cliente deben estar activos y probados.
2. El issuer externo y la URL interna de JWKS tienen responsabilidades
   distintas. El Gateway valida `iss` contra la URL publica, pero puede obtener
   las claves por la red interna de Kubernetes.
3. No se debe añadir `:443` al issuer canonico. Keycloak y Gateway deben producir
   y validar exactamente la misma cadena sin el puerto HTTPS implicito.
4. El DNS proxificado, Application Security mTLS y su regla WAF deben
   configurarse antes de permitir que Cloudflare alcance el origen. En el plan
   Free se usaran certificados emitidos por la CA gestionada de Cloudflare; la
   CA propia mediante Cloudflare Access queda descartada porque requiere
   Enterprise.
5. El firewall no puede abrir `443/tcp` a `0.0.0.0/0`. Solo aceptara los rangos
   oficiales vigentes de Cloudflare. Esos rangos requieren un procedimiento de
   actualizacion.
6. Bloquear `/auth/admin/*` no basta por si solo: tambien se debe bloquear el
   realm `master`, la documentacion del Gateway y cualquier servicio operativo.
7. Los cambios de seguridad y de issuer deben probarse primero por tunel, luego
   en el dominio real protegido por mTLS y finalmente sin mTLS.
8. La apertura necesita un rollback de un solo paso: reactivar la politica mTLS,
   sin cambiar DNS, Kubernetes, Keycloak ni certificados.

### Plan ordenado de despliegue

Cada fase es un gate. No se inicia la siguiente hasta cumplir sus criterios de
salida.

#### Matriz de despliegue por fase

| Fase | Estado | Alcance breve | Kubernetes local | Kubernetes Hetzner | Cambio externo |
| --- | --- | --- | --- | --- | --- |
| 0 | **Cerrada** | Inventariar el sistema estable y fijar una linea base funcional y recuperable | No | No; se prueba lo ya desplegado | No |
| 1 | **Cerrada** | Preparar aplicacion, OIDC, manifests y overlays para el dominio sin activarlo | **OK** | **OK**; se valido `prod` y `prod-domain` no se activo durante esta fase | No |
| 2 | **Cerrada** | Registrar el dominio, delegar DNS a Cloudflare y asegurar el perimetro inicial | No | No | Dominio, Cloudflare y DNS |
| 3 | **Cerrada** | Proteger temporalmente el dominio con certificado cliente mTLS durante las pruebas | No | No | Certificado cliente y regla WAF mTLS activos; rollback probado; revocacion y reemplazo no ejecutados por decision de alcance |
| 4 | **Cerrada** | Instalar y rotar manualmente un certificado Cloudflare Origin CA sin abrir puertos publicos | Render validado; Secret local y `localhost` intactos | Origin CA instalado y validado por tunel | Certificado emitido; origen filtrado en 80/443 y alerta activa |
| 5 | **Cerrada** | Implantar protecciones permanentes, limites, registros y alertas antes de publicar | Validada | Validada | WAF, rate limits y alertas activos y comprobados |
| 6 | **En curso (`infra-prod` desplegado; validacion Keycloak pendiente)** | Activar la configuracion definitiva del dominio en K3s manteniendo el origen cerrado | Render validado; no desplegar en local | Gate TLS e `infra-prod` completados; validar Keycloak antes de `apis-frontend-prod` | No |
| 7 | **Pendiente** | Permitir HTTPS solo desde Cloudflare y validar la aplicacion completa bajo mTLS | No | No se redespliega Kubernetes | Firewall Hetzner y pruebas por Cloudflare |
| 8 | **Pendiente** | Revisar evidencias y decidir formalmente si el sistema puede abrirse al publico | No | No | Decision GO/NO-GO |
| 9 | **Pendiente** | Retirar el gate mTLS temporal y habilitar el acceso publico con rollback inmediato | No | No | Desactivar la regla WAF mTLS temporal |
| 10 | **Pendiente; no implementada** | Obtener backups cifrados y demostrar una restauracion funcional aislada | Si, solo para restauracion aislada | No se redespliega; se obtienen backups reales | Copia cifrada externa |

**Hito actual para versionado:** el pipeline `#2770049730` desplego
`infra-prod` desde `4a7e9185` y supero el gate TLS y el bootstrap. El siguiente
gate es validar el rollout y el discovery OIDC de Keycloak. No se ha desplegado
`apis-frontend-prod` ni se ha abierto el firewall.

`No` significa que esa fase no debe provocar un despliegue en ese cluster. Las
consultas, renderizados, backups o pruebas indicadas siguen siendo obligatorios.

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

#### Fase 3 - Acceso privado por certificado cliente (cerrada)

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

- Verificar cadena, uso extendido `clientAuth`, fechas e identificador de cada
  certificado, probar su importacion como PKCS#12 y documentar el procedimiento
  de revocacion.
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
- La prueba HTTP extremo a extremo con la aplicacion se realiza en la Fase 7.

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
   limitada hasta el 5 de agosto de 2028. Se comprobaron sujeto, emisor, fechas,
   uso extendido `clientAuth` y correspondencia criptografica entre certificado
   y clave privada.
4. Se creo un PKCS#12 cifrado y se valido su estructura antes de importarlo en el
   almacen personal del usuario de Windows. El certificado importado conserva
   la clave privada y el uso `Client Authentication`.
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
   existe un unico tester, la clave privada esta cifrada y bajo su control, y
   mTLS solo se utilizara temporalmente durante las pruebas previas a la apertura
   publica.
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
5. Durante la apertura publica se desactivara la regla WAF temporal segun la
   Fase 9. No retirar la politica de seleccion de Edge, el certificado del
   almacen de Windows ni su copia privada operativa mientras protejan la
   administracion permanente. Mantener los procedimientos de renovacion,
   revocacion y reemplazo.
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
  origen en la Fase 7.

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
   la Fase 7.
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
  `/auth/realms/master`; la regla general actual seguira siendo el gate
  temporal para el resto de la aplicacion. En la apertura se desactivara solo
  la regla temporal. La administracion por tunel SSH directo a Traefik no pasa
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
  6 de agosto de 2026 al 5 de agosto de 2028, con clave privada y EKU
  `Client Authentication` (`1.3.6.1.5.5.7.3.2`). Tanto la politica como el
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
   hostname y la regla general temporal. En la Fase 9 se desactivara solo esta
   ultima. La administracion por SSH usara Traefik directamente, preservando el
   hostname canonico `assermetry.com`; el firewall impedira que Internet
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

#### Fase 6 - Despliegue definitivo todavia cerrado (en curso; infra desplegada)

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
- La causa queda aislada al metodo de prueba: el `port-forward` consultaba
  `127.0.0.1` sin las cabeceras `X-Forwarded-*` que Traefik sobrescribe y que
  Keycloak espera con `KC_PROXY_HEADERS=xforwarded`. El gate corregido emula
  `Host`, proto y puerto externos y muestra solo el issuer observado. No se
  despliega `apis-frontend-prod` hasta superar su repeticion.
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
3. **Desplegado; discovery pendiente:** `infra-prod` se aplico desde `4a7e9185`.
   La repeticion sobre `77e189ef` confirmo el rollout de Keycloak y sus dos URLs
   externas; fallo la prueba directa de discovery sin cabeceras de proxy. El
   gate corregido debe confirmar ahora el issuer definitivo.
4. Desplegar `blockchain-prod` solo si hay cambios o si falta el despliegue;
   verificar peers, bloques, contrato y categorias.
5. **Pendiente, despues de validar Keycloak:** desplegar `apis-frontend-prod`
   con Gateway, frontend, workers e Ingress productivos.
6. Antes de tocar el firewall, validar mediante tunel y resolucion local de
   `assermetry.com` que TLS, redirects e issuer son correctos.

Criterio de salida: la aplicacion completa usa ya la configuracion final, pero
el origen todavia no acepta trafico de Internet.

#### Fase 7 - Abrir 443 solo a Cloudflare y probar con mTLS (pendiente)

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no redesplegar Kubernetes salvo que una prueba descubra un
  defecto. Cambiar exclusivamente el firewall para permitir `443/tcp` desde los
  rangos oficiales de Cloudflare.
- Externo: mantener Application Security mTLS y su regla WAF activos; este es
  el primer acceso al dominio real.

**Pruebas**

- Sin certificado cliente: esperar denegacion en `/`, `/backend` y `/auth`.
- Con certificado cliente: probar TLS, login, refresh, logout, roles, client
  credentials y los flujos funcionales completos desde varias redes.
- Comprobar `Full (strict)`, issuer exacto y cabeceras reenviadas; verificar que
  la IP directa de Hetzner, `80/tcp`, `6443/tcp` y el resto de puertos no permiten
  evitar Cloudflare.
- Probar certificado caducado o revocado, reinicio de pods, dependencia caida y
  reactivacion del cierre mTLS.

Este es el primer momento en que se modifica el firewall de Hetzner:

```text
443/tcp  permitido solo desde rangos oficiales de Cloudflare
80/tcp   cerrado
2222/tcp restringido para SSH con clave
6443/tcp cerrado publicamente
resto    cerrado
```

1. Configurar Traefik para confiar cabeceras reenviadas solo desde proxies
   conocidos y mantener `KC_PROXY_HEADERS=xforwarded` en Keycloak.
2. Confirmar que la IP directa de Hetzner no permite saltarse Cloudflare.
3. Desde un dispositivo sin certificado, verificar respuesta 403 en `/`,
   `/backend` y `/auth`.
4. Desde dispositivos con certificado, probar login, refresh, logout, roles,
   client credentials, modo Light, modo Blockchain, ordenes, cuotas, IPFS,
   validadores y exploradores.
5. Comprobar el discovery OIDC. `issuer` debe ser exactamente:

   ```text
   https://assermetry.com/auth/realms/TrustNews
   ```

6. Probar desde varias redes, caducidad del certificado cliente, reinicios,
   dependencias caidas, rollback y recuperacion ante fallos.

Criterio de salida: toda la produccion funciona sobre el dominio real y nadie
sin certificado cliente puede acceder a ningun flujo de usuario.

#### Fase 8 - GO/NO-GO para apertura (pendiente)

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar ni cambiar configuracion.
- Externo: no retirar todavia mTLS; esta fase solo decide `GO` o `NO-GO`.

**Pruebas**

- Repetir sobre el dominio real protegido por mTLS el smoke de autenticacion,
  Light, Blockchain, cuotas y dependencias.
- Repetir pruebas negativas sin certificado, contra la IP directa, rutas
  administrativas, OpenAPI y servicios internos.
- Revisar evidencias de rollback, renovacion TLS, WAF, rate limits,
  logs y alertas; comprobar que el equipo puede reactivar mTLS.

La apertura recibe `GO` solo si:

- DNS, proxy Cloudflare y TLS `Full (strict)` son correctos.
- El origen solo admite rangos Cloudflare y no responde por acceso directo.
- Issuer, redirects, login, refresh, logout y client credentials funcionan.
- Modos Light y Blockchain, cuotas y servicios dependientes funcionan.
- Administracion, OpenAPI y servicios internos permanecen bloqueados.
- El rollback de la apertura ha sido probado.
- WAF, rate limiting, logs y alertas estan activos.
- El equipo conoce y ha probado el procedimiento para reactivar el mTLS.

Cualquier incumplimiento produce `NO-GO`; no se compensa retirando controles.

#### Fase 9 - Apertura publica (pendiente)

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar ni cambiar firewall, Ingress, Keycloak,
  Gateway, issuer o certificados.
- Externo: desactivar unicamente la regla WAF temporal que exige mTLS.

**Pruebas**

- Desde un navegador limpio y sin certificado: probar acceso, login, refresh,
  logout y los principales flujos Light y Blockchain.
- Repetir las pruebas negativas de rutas administrativas, OpenAPI, IP directa y
  servicios internos.
- Vigilar en la ventana de apertura latencia, `401`, `403`, `429`, `5xx`, WAF,
  rate limits, reinicios y disco.
- Ejecutar una prueba controlada del rollback reactivando mTLS y comprobando que
  un cliente sin certificado vuelve a quedar bloqueado; retirarlo de nuevo solo
  si la plataforma sigue estable.

El unico cambio de apertura es desactivar la regla WAF temporal que bloquea a
los clientes sin certificado valido. La asociacion mTLS del hostname, la regla
administrativa permanente y al menos un certificado cliente operativo deben
mantenerse.

No se modifican DNS, proxy, certificado TLS, firewall, Ingress, Keycloak,
Gateway, issuer, frontend, las demas reglas WAF ni los rate limits.

Tras retirarla:

1. Probar desde un navegador limpio y sin certificado el acceso, login, refresh,
   logout y los principales flujos funcionales.
2. Confirmar que las rutas administrativas, documentacion y servicios internos
   siguen bloqueados.
3. Vigilar errores, latencia, WAF y rate limits durante la ventana de apertura.
4. Si aparece una incidencia, reactivar inmediatamente la exigencia mTLS. Este
   rollback vuelve a cerrar el servicio sin cambios de DNS ni redespliegue.

#### Fase 10 - Backups y recuperacion (pendiente; no implementada)

**Estado**

- Posicion en el plan: **ultima fase de ejecucion**.
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

### Entregables de v0.0.12

- Overlays local y productivo renderizables y separados por entorno.
- Issuer y JWKS del Gateway parametrizados correctamente.
- Keycloak configurado para `assermetry.com` y marca visible `Assermetry`.
- Ingress productivos con hostname y rutas definitivas.
- Documentacion y endpoints administrativos no expuestos.
- Backups y restauraciones verificados.
- DNS proxificado, WAF, rate limiting y observabilidad activos.
- Certificado TLS del origen gestionado y renovable.
- Acceso privado mTLS probado antes de abrir al publico.
- Firewall restringido a Cloudflare y sin acceso directo al origen.
- Checklist GO/NO-GO y rollback de apertura probados.

### Fuera de alcance

- Renombrar el realm `TrustNews` o los clientes OIDC existentes.
- Publicar bases de datos, Kafka, IPFS API, RPC, paneles o APIs administrativas.
- Añadir `www.assermetry.com` sin una redireccion canonica probada.
- Sustituir los runbooks operativos por este documento de version.
