# Versiones del despliegue Kubernetes

Este documento describe el objetivo, alcance, dependencias, orden de despliegue
y criterios de aceptacion de cada version de la plataforma Kubernetes de
Assermetry. Los comandos operativos se mantienen en:

- [`k8s-common.md`](k8s-common.md): configuracion compartida.
- [`skaffold-local.md`](skaffold-local.md): despliegue local con `kind`.
- [`skaffold-server.md`](skaffold-server.md): despliegue productivo en Hetzner.

---

## v0.0.12 - Exposicion controlada de Assermetry en Internet

### Objetivo

Publicar la instalacion de Hetzner en `https://assermetry.com`, conservando la
posibilidad de desplegar y validar la misma aplicacion en local.

La apertura al publico sera el ultimo paso. Antes de ella, el servicio completo
debe funcionar en el dominio definitivo y el acceso HTTPS por `443/tcp` debe
estar restringido mediante un certificado personal mTLS. Retirar esa exigencia
sera el unico cambio necesario para abrir Assermetry al publico.

### Estado actual

La version `v0.0.12` ha cerrado la **Fase 0 - Inventario y linea base**. Los
cambios de repositorio de la **Fase 1 - Adaptacion de aplicacion y manifests**
estan implementados y renderizados; queda desplegar en Hetzner los cambios
compatibles con `prod` y repetir las pruebas por tunel para cerrar la fase.
Existe una version estable en Hetzner accesible mediante tunel SSH, pero todavia
no se ha activado el dominio publico ni deben cambiarse sus URLs OIDC.

Configuracion activa mientras se completa esta fase:

```text
Local:          https://localhost:7443
Hetzner/tunel:  https://localhost:9443
Dominio futuro: https://assermetry.com (inactivo)
```

Los perfiles Skaffold actuales continúan usando `overlays/local` y
`overlays/prod`, ambos con `host: localhost`. Los overlays `prod-domain` dejan
preparados el host, Keycloak y el issuer de `assermetry.com`, pero no estan
referenciados por Skaffold y no deben activarse hasta superar las fases previas
al despliegue definitivo.

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
Cloudflare Proxy / Access / WAF
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
- El certificado cliente mTLS, emitido por una CA privada, autoriza
  temporalmente a cada tester antes de la apertura publica.

Tener solo el certificado TLS del servidor no restringe el acceso. El gate
privado previo a la apertura requiere que Cloudflare Access rechace cualquier
cliente sin un certificado mTLS valido.

### Regla de oro de seguridad

- El acceso por mTLS debe estar activo antes del primer momento en que
  `443/tcp` sea alcanzable desde Internet, en la **Fase 8**, y mantenerse hasta
  la apertura publica de la **Fase 10** tras el GO/NO-GO.
- No se debe abrir `443/tcp` al trafico publico general hasta que la Fase 8 haya
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
4. El DNS proxificado, Access mTLS y el WAF deben configurarse antes de permitir
   que Cloudflare alcance el origen. Debe verificarse previamente que el plan de
   Cloudflare contratado soporta la politica mTLS elegida.
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

| Fase | Kubernetes local | Kubernetes Hetzner | Cambio externo |
| --- | --- | --- | --- |
| 0 | No | No; se prueba lo ya desplegado | No |
| 1 | Si, antes de Hetzner | Si, solo con `prod`; `prod-domain` sigue inactivo | No |
| 2 | Si, solo para restauracion aislada | No se redespliega; se obtienen backups reales | Copia cifrada externa |
| 3 | No | No | Dominio, Cloudflare y DNS |
| 4 | No | No | CA cliente y Cloudflare Access mTLS |
| 5 | No | Si, `cert-manager` y certificado del origen | ACME DNS-01 |
| 6 | Si cambian Gateway o Traefik | Si cambian manifests u observabilidad | WAF, rate limits y alertas |
| 7 | No; solo renderizado de `prod-domain` | Si, despliegue definitivo con `prod-domain` | No |
| 8 | No | No se redespliega Kubernetes | Firewall Hetzner y pruebas por Cloudflare |
| 9 | No | No | Decision GO/NO-GO |
| 10 | No | No | Retirar mTLS de Cloudflare Access |

`No` significa que esa fase no debe provocar un despliegue en ese cluster. Las
consultas, renderizados, backups o pruebas indicadas siguen siendo obligatorios.

#### Fase 0 - Inventario y linea base

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

#### Fase 1 - Adaptacion de aplicacion y manifests

Finalidad: preparar y verificar la configuracion que necesitara el dominio
definitivo sin cambiar todavia la identidad OIDC del despliegue activo. En esta
fase `prod` sigue representando el acceso cerrado por
`https://localhost:9443`; `prod-domain` representa la configuracion futura de
`https://assermetry.com`.

**Despliegue**

- Kubernetes local: si. Desplegar primero los perfiles locales vigentes y no
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
   con los clientes OIDC en la Fase 7.
4. Dejar preparados para la activacion coordinada de la Fase 7 los valores de
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

#### Fase 2 - Backups y recuperacion

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

#### Fase 3 - Dominio, Cloudflare y DNS

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

1. Registrar `assermetry.com` con renovacion automatica, bloqueo de transferencia
   y 2FA.
2. Delegar los nameservers a Cloudflare.
3. Crear el registro `A` de `@` hacia Hetzner con proxy activado.
4. Configurar TLS `Full (strict)`, HTTPS obligatorio y TLS minimo 1.2.
5. No publicar `www` en esta version salvo que se añada y pruebe expresamente la
   redireccion canonica.

Criterio de salida: DNS resuelve a Cloudflare y el origen sigue cerrado al
trafico general.

#### Fase 4 - Acceso privado por certificado cliente

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar ni abrir `443/tcp`.
- Externo: crear la CA, certificados de tester y politica mTLS en Cloudflare
  Access.

**Pruebas**

- Verificar localmente cadena de confianza, uso extendido `clientAuth`, fechas y
  revocabilidad de cada certificado, y probar la importacion del PKCS#12.
- Confirmar que Cloudflare solo contiene el certificado publico de la CA y que
  la clave privada no esta en Git, Kubernetes, Hetzner ni Cloudflare.
- Revisar que la aplicacion Access cubre `assermetry.com/*`, incluidas `/auth` y
  `/backend`, y que no existe una regla bypass.
- Comprobar el procedimiento de revocacion y reactivacion de la politica. La
  prueba HTTP extremo a extremo con y sin certificado se realiza en la Fase 8.

1. Crear fuera del servidor una CA privada dedicada al acceso temporal.
2. Emitir un certificado `clientAuth` individual por tester, con validez corta,
   revocacion identificable y exportacion PKCS#12 protegida por contrasena.
3. No subir la clave privada de la CA a Git, GitLab, Hetzner, Kubernetes ni
   Cloudflare; Cloudflare solo recibe el certificado publico de la CA.
4. Crear una aplicacion Cloudflare Access que cubra `assermetry.com/*` y exija
   certificado cliente valido en todas las rutas, incluidas `/auth` y
   `/backend`.
5. Instalar el certificado individual en los dispositivos de prueba.

Criterio de salida: la politica existe antes de que `443/tcp` sea alcanzable y
puede revocarse o reactivarse sin redesplegar la aplicacion.

#### Fase 5 - TLS del origen antes de abrir 443

**Despliegue**

- Kubernetes local: no es necesario desplegar `cert-manager` ni el certificado
  publico; se mantiene el certificado local existente.
- Kubernetes Hetzner: si. Instalar `cert-manager`, el `Issuer` o `ClusterIssuer`
  y el `Certificate` del origen sin abrir `443/tcp`.

**Pruebas**

- Comprobar `Certificate Ready=True`, `Order` y `Challenge` finalizados, y que el
  Secret `trustnews-origin-tls` pertenece a `cert-manager`.
- Inspeccionar SAN, emisor, cadena, fechas y clave publica del certificado.
- Mediante tunel o port-forward y SNI `assermetry.com`, comprobar que Traefik
  presenta ese certificado.
- Confirmar que una renovacion o emision de prueba DNS-01 no requiere abrir
  `80/tcp` ni `443/tcp` y que el token Cloudflare solo puede editar la zona DNS.

1. Instalar `cert-manager`.
2. Usar ACME DNS-01 con un token Cloudflare limitado a la zona DNS de
   `assermetry.com`; no usar la API key global.
3. Emitir `assermetry-origin-cert` para `assermetry.com` en `kube-system`,
   manteniendo `trustnews-origin-tls` como nombre del Secret para evitar cambios
   innecesarios en `TLSStore`.
4. Dejar a `cert-manager` como unico propietario del Secret. No ejecutar
   `apply_tls_secret` sobre un Secret gestionado por `cert-manager`.
5. Verificar `Certificate Ready=True`, cadena, hostname y renovacion.

Criterio de salida: Traefik presenta un certificado valido para
`assermetry.com` y Cloudflare puede usar `Full (strict)`.

#### Fase 6 - WAF, restricciones permanentes y observabilidad

**Despliegue**

- Kubernetes local: desplegar y probar solo si cambian Gateway, Traefik,
  middlewares o configuracion de logs; las reglas Cloudflare no se despliegan en
  local.
- Kubernetes Hetzner: desplegar los manifests de seguridad u observabilidad que
  hayan cambiado, manteniendo `prod` y el acceso por tunel.
- Externo: configurar WAF y rate limiting de Cloudflare primero en deteccion.

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

1. Activar WAF inicialmente en modo deteccion y revisar falsos positivos.
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

5. Preparar logs y alertas para Access, WAF, Traefik, Gateway, Keycloak,
   certificados, reinicios, disco y respuestas 401, 403, 429 y 5xx.
6. Confirmar que MongoDB, PostgreSQL, Kafka, Kafdrop, Mongo Express, IPFS API,
   RPC Ethereum, admin-service y Kubernetes API no tienen Ingress ni NodePort.

Criterio de salida: las protecciones que deben sobrevivir a la retirada del mTLS
estan activas y observables.

#### Fase 7 - Despliegue definitivo todavia cerrado

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

1. Verificar el certificado instalado en la Fase 5 y desplegar `TLSStore` y los
   recursos de seguridad que lo consumen.
2. Cambiar los paths de los perfiles productivos desde `overlays/prod` a
   `overlays/prod-domain` en un cambio revisable y coordinado.
3. Desplegar `infra-prod` con Keycloak alineado con el issuer definitivo.
4. Desplegar `blockchain-prod` solo si hay cambios o si falta el despliegue;
   verificar peers, bloques, contrato y categorias.
5. Desplegar `apis-frontend-prod` con Gateway, frontend, workers e Ingress
   productivos.
6. Antes de tocar el firewall, validar mediante tunel y resolucion local de
   `assermetry.com` que TLS, redirects e issuer son correctos.

Criterio de salida: la aplicacion completa usa ya la configuracion final, pero
el origen todavia no acepta trafico de Internet.

#### Fase 8 - Abrir 443 solo a Cloudflare y probar con mTLS

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no redesplegar Kubernetes salvo que una prueba descubra un
  defecto. Cambiar exclusivamente el firewall para permitir `443/tcp` desde los
  rangos oficiales de Cloudflare.
- Externo: mantener Cloudflare Access mTLS activo; este es el primer acceso al
  dominio real.

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
   dependencias caidas, restauracion y rollback.

Criterio de salida: toda la produccion funciona sobre el dominio real y nadie
sin certificado cliente puede acceder a ningun flujo de usuario.

#### Fase 9 - GO/NO-GO para apertura

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar ni cambiar configuracion.
- Externo: no retirar todavia mTLS; esta fase solo decide `GO` o `NO-GO`.

**Pruebas**

- Repetir sobre el dominio real protegido por mTLS el smoke de autenticacion,
  Light, Blockchain, cuotas y dependencias.
- Repetir pruebas negativas sin certificado, contra la IP directa, rutas
  administrativas, OpenAPI y servicios internos.
- Revisar evidencias de restauracion, rollback, renovacion TLS, WAF, rate limits,
  logs y alertas; comprobar que el equipo puede reactivar mTLS.
- No ejecutar una nueva restauracion destructiva: validar la evidencia obtenida
  en la Fase 2 y repetir solo si ha quedado obsoleta.

La apertura recibe `GO` solo si:

- DNS, proxy Cloudflare y TLS `Full (strict)` son correctos.
- El origen solo admite rangos Cloudflare y no responde por acceso directo.
- Issuer, redirects, login, refresh, logout y client credentials funcionan.
- Modos Light y Blockchain, cuotas y servicios dependientes funcionan.
- Administracion, OpenAPI y servicios internos permanecen bloqueados.
- Backups, restauracion y rollback han sido probados.
- WAF, rate limiting, logs y alertas estan activos.
- El equipo conoce y ha probado el procedimiento para reactivar el mTLS.

Cualquier incumplimiento produce `NO-GO`; no se compensa retirando controles.

#### Fase 10 - Apertura publica, ultimo paso

**Despliegue**

- Kubernetes local: no desplegar.
- Kubernetes Hetzner: no desplegar ni cambiar firewall, Ingress, Keycloak,
  Gateway, issuer o certificados.
- Externo: retirar unicamente la exigencia temporal de mTLS en Cloudflare Access.

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

El unico cambio de apertura es desactivar la politica temporal de Cloudflare
Access que exige certificado cliente.

No se modifican DNS, proxy, certificado TLS, firewall, Ingress, Keycloak,
Gateway, issuer, frontend, WAF ni rate limits.

Tras retirarla:

1. Probar desde un navegador limpio y sin certificado el acceso, login, refresh,
   logout y los principales flujos funcionales.
2. Confirmar que las rutas administrativas, documentacion y servicios internos
   siguen bloqueados.
3. Vigilar errores, latencia, WAF y rate limits durante la ventana de apertura.
4. Si aparece una incidencia, reactivar inmediatamente la exigencia mTLS. Este
   rollback vuelve a cerrar el servicio sin cambios de DNS ni redespliegue.

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
