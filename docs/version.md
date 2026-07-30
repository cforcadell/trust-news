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

La version `v0.0.12` ha cerrado la **Fase 0 - Inventario y linea base** y se
encuentra preparada para iniciar la **Fase 1 - Adaptacion de aplicacion y
manifests**. Existe una version estable en Hetzner accesible mediante tunel SSH,
pero todavia no se ha activado el dominio publico ni deben cambiarse sus URLs
OIDC.

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

- El acceso por mTLS debe mantenerse activo durante todas las fases previas a la
  apertura publica y solo debe retirarse en la **Fase 10** tras el GO/NO-GO.
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

#### Fase 0 - Inventario y linea base

Despliegue en Hetzner: no se despliega nada nuevo; se valida la instalacion
existente por tunel SSH y se documenta el estado operativo actual antes de tocar
manifests, DNS o firewall.

1. Confirmar que la version actualmente desplegada en Hetzner es recuperable.
2. Inventariar imagenes, manifests, PVC, secrets, contrato, categorias, DNS y
   reglas actuales de firewall.
3. Ejecutar pruebas funcionales por el tunel SSH existente con solo `2222/tcp`
   accesible.
4. Registrar metricas y errores conocidos para poder distinguir regresiones.

Criterio de salida: frontend, autenticacion, modos Light y Blockchain, colas,
IPFS y validadores funcionan antes de introducir el dominio.

#### Fase 1 - Adaptacion de aplicacion y manifests

Despliegue en Hetzner: los cambios de manifests y configuraciones se aplican
primero en el clúster de Hetzner por tunel SSH, sin activar aun el dominio
publico.

1. Parametrizar el Gateway con:

   ```dotenv
   KEYCLOAK_ISSUER_URL=https://assermetry.com/auth/realms/TrustNews
   KEYCLOAK_JWKS_URL=http://keycloak.infra.svc.cluster.local:8080/auth/realms/TrustNews/protocol/openid-connect/certs
   ```

2. Eliminar dependencias productivas de `localhost`, cabeceras `Host` forzadas
   y construcciones del issuer mediante hostname, puerto y path separados.
3. Preparar Keycloak en `overlays/prod-domain` con la URL publica definitiva,
   proxy headers y nombre visible `Assermetry`, sin alterar todavia `prod`.
4. Configurar `TrustNewsWeb` con root, redirects, post-logout redirects y Web
   Origins limitados a `https://assermetry.com`; no usar `*` en produccion.
5. Mantener `TrustNewsApi` confidencial, con service account y secret fuera del
   repositorio.
6. Desactivar Swagger, Redoc y OpenAPI en el Gateway productivo.
7. Mantener los parches de dominio en `k8s/ingress/overlays/prod-domain` con
   `host: assermetry.com`, conservando `websecure`, TLS y el middleware que
   elimina `/backend`; no conectarlos aun a Skaffold.
8. Mantener `/auth/admin/*`, `/auth/realms/master/*` y el admin-service fuera de
   la exposicion publica.

Criterio de salida: `local` y `prod` siguen renderizando `localhost`, los
`prod-domain` renderizan el dominio oficial de forma aislada y las pruebas por
tunel continúan funcionando.

#### Fase 2 - Backups y recuperacion

Despliegue en Hetzner: se ejecutan backups y restauraciones sobre el entorno real
que ya existe en Hetzner y se conservan copias fuera del cluster.

1. Crear y probar restauraciones de MongoDB y PostgreSQL de Keycloak.
2. Respaldar genesis, keystores, contrasenas Ethereum, direccion y ABI del
   contrato, categorias y configuracion de nodos.
3. Mantener una copia cifrada fuera de Hetzner de secrets Kubernetes, variables
   CI/CD, claves API, claves Ethereum, secrets OIDC y credenciales Cloudflare.
4. Ensayar el rollback de manifests e imagenes.

Criterio de salida: existe evidencia de restauracion, no solo ficheros de backup.

#### Fase 3 - Dominio, Cloudflare y DNS

Despliegue en Hetzner: no aplica cambio de infraestructura en esta fase; se
prepara DNS y proxy, pero el origen sigue cerrado por mTLS y firewall.

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

Despliegue en Hetzner: no aplica cambio de infraestructura; se habilita la
politica de acceso en Cloudflare y se prueba sin tocar el despliegue del
cluster.

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

Despliegue en Hetzner: se instala `cert-manager` y se publica el certificado TLS
origino en el clúster de Hetzner; esta fase no se considera cerrada hasta que el
certificado esté listo y renovable.

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

Despliegue en Hetzner: se aplican reglas de WAF, rate limiting y observabilidad
sobre la plataforma ya desplegada en Hetzner.

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

Despliegue en Hetzner: es la fase de despliegue definitivo del stack en Hetzner,
pero el origen sigue cerrado al trafico publico hasta completar la validacion
final.

1. Desplegar certificados, `TLSStore` y recursos de seguridad.
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

Despliegue en Hetzner: se abre `443/tcp` solo a Cloudflare desde Hetzner,
manteniendo el acceso por mTLS activo; este es el primer punto en el que el
servicio queda accesible de forma limitada al dominio real.

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

Despliegue en Hetzner: no aplica cambio de infraestructura; se valida el estado
real de la plataforma ya desplegada en Hetzner antes de autorizar la apertura.

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

Despliegue en Hetzner: no aplica cambio de infraestructura; la unica accion de
apertura es retirar la exigencia de mTLS en Cloudflare Access, manteniendo el
resto de la configuracion estable.

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
