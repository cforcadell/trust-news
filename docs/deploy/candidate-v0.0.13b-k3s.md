# Candidato v0.0.13b para Hetzner/K3s

**Estado: desplegada en Hetzner/K3s, con salud OK según el operador; aceptación
pendiente.** Esta ficha separa el resultado
estático del repositorio de la evidencia que solo puede producir un pipeline
protegido y el clúster K3s. No autoriza despliegue ni apertura de demos.

**Lectura de la bitácora:** los párrafos y tablas fechados conservan el estado
conocido en cada momento y no son instrucciones actuales. Para la situación
actual y las puertas pendientes, consultar [version.md](../version.md) y
[working.md](../../working.md). El operador comunicó copias MongoDB y
PostgreSQL fuera de Hetzner; la restauración aislada aún no está demostrada.
Las comprobaciones posteriores del operador incluyen S03 y Kafka en K3s, sin
que ello fije por sí solo el candidato exacto ni cierre su aceptación.

Actualización 2026-11-14: antes de esta actualización documental, el checkout local estaba limpio en
`554a2382397275649774eb8cf659b9d1145504b9`. El operador comunica que
sincronizó el script corregido a Hetzner; la salida que aportó muestra
`create-secrets.sh --phase infra` completo y el preflight de Secrets `infra`
correcto en K3s (S03 Keycloak y Kafka TLS). Esto acredita esa fase de Secrets
en la sesión del host. El preflight CI `infra-prod` del mismo SHA arrancó en
GitLab y falló antes del despliegue: el comprobador Kafka usaba
`base64 --decode`, opción no admitida por BusyBox en el contenedor Alpine del
job. El Secret era legible, pero sus claves se informaron erróneamente como
ausentes y la CA como inválida. La corrección local cambia a `base64 -d`;
figura ahora en el checkout local limpio `41dc2989325db70b1c545a7726d100883911a127`.
El operador aportó después el log completo de preflight CI `infra-prod`:
checkout `41dc2989` de `postTFM`, acceso K3s y TLS servido verificados, S03
y Kafka OK, y `Job succeeded`. El prefijo coincide con el HEAD local completo
indicado arriba; el log no muestra ID del job ni valores de variables
seleccionadas. Siguen pendientes respaldo recuperable, despliegue y aceptación
funcional. No se ha confirmado un snapshot completo ni una restauración.

Inventario PVC aportado por el operador el 2026-11-14: contexto K3s `default`,
nueve PVC `Bound`. `infra` contiene MongoDB, Keycloak/PostgreSQL, Kafka,
IPFS, Grafana y Loki; `blockchain` conserva tres PVC de Geth. Este inventario
no confirmó la clase de almacenamiento, el contenido de las copias ni una
restauración probada.

Lectura posterior del operador: los nueve PVC usan StorageClass `local-path`
con provisioner `rancher.io/local-path`. Falta comprobar las rutas PV y su
sistema de archivos en el nodo antes de afirmar que un snapshot del servidor
las cubriría. No se confirmó ninguna copia externa ni restauración.

Las nueve rutas PV aportadas después están bajo `/var/lib/rancher/k3s/storage`;
falta identificar el montaje que contiene ese directorio. El operador afirma
tener una copia MongoDB, sin ubicación externa, fecha, integridad ni
restauración verificadas. Tampoco se ha acreditado una copia de
Keycloak/PostgreSQL. `findmnt -T /var/lib/rancher/k3s/storage` devolvió
`/dev/sda1` como sistema de archivos raíz (`ext4`). Los PV apuntan bajo ese
directorio; falta descartar montajes anidados y confirmar un snapshot
disponible y la consistencia de los datos de ese corte.

El operador mostró una copia MongoDB del 14-11-2026 con manifiesto y checksum
en el propio servidor; sigue sin acreditarse almacenamiento externo ni
restauración. Se prepararon localmente motores parametrizados de copia y
restauración PostgreSQL con el mismo contrato de artefacto que MongoDB, y se
añadieron al inventario de sincronización a Hetzner. El log aportado del job
`sync-scripts` sobre `35c2a995` confirma su instalación con SHA-256 y termina
en `Job succeeded`. El operador ejecutó después el backup PostgreSQL de
`keycloak` en la VM: `keycloak-20261114T183013Z.archive.gz`. El restore sin
`--apply` verificó el archivo y el destino `infra/keycloak-db-0` sin modificar
datos. El operador confirma los respaldos MongoDB y PostgreSQL fuera de
Hetzner y pide continuar con esa confirmación operativa. No se ha ensayado una
restauración aislada. El nuevo preflight CI `infra-prod` sobre `35c2a995`
pasó: acceso K3s, TLS servido, S03 y Kafka, con `Job succeeded`. El prefijo
coincide con el HEAD local completo `35c2a9955503b2605e1ba5b527c6e1505c3ec5ec`.
El preflight `apis-frontend-prod` del mismo SHA falló antes de desplegar:
faltan los siete Secrets de clientes S03 y `apis/s07a-kafka-ca`; las
credenciales de aplicación comprobadas pasaron. El orden de
`secrets-hetzner.md` exige primero desplegar `infra-prod`, reconciliar clients
con Keycloak y aprovisionar `--phase apis`; el preflight API se pidió antes de
esa fase. Antes de desplegar infraestructura siguen pendientes la confirmación
actual del snapshot y del maintenance lock.

El operador aportó después el log del job `deploy` de `infra-prod` en
`35c2a995`: descargó el artefacto `build.json`, pasó el preflight de Secrets
e inició `skaffold deploy`; varios recursos de `infra` quedaron configurados.
El job terminó fallando al estabilizar Kafdrop porque no pudo resolver
`kafka.infra.svc.cluster.local`. Mongo Express mostró también un fallo de
resolución de `mongodb` antes de aparecer Ready, y Loki quedó pendiente por
CPU insuficiente. El log no acredita el estado final de CoreDNS, Kafka,
Keycloak ni los demás pods. Es un despliegue parcial; se requiere diagnóstico
vivo antes de otro deploy o de pasar a `apis-frontend-prod`.

La lectura viva posterior aportada por el operador muestra nodo y CoreDNS
Ready, endpoint de CoreDNS presente, todos los Deployments y StatefulSets de
`infra` Ready y endpoints de Kafka, MongoDB y Keycloak DB presentes. Kafdrop
reinició dos veces y quedó Ready. Esto indica convergencia posterior al
fallo, pero el job no llegó a su verificación final ni a la reconciliación
web de Keycloak. Antes de reintentar el mismo job con `build.json`, confirmar
snapshot y maintenance lock; no pasar aún a `apis-frontend-prod`.

El operador confirmó después snapshot y maintenance lock activos. El retry
del job `infra-prod` en el mismo SHA descargó `build.json`, pero volvió a
fallar cuando Kafdrop no pudo resolver el Service headless de Kafka mientras
el broker aún se creaba. Esto es compatible con una carrera de arranque. Se
preparó localmente una espera de Kafka en el
Deployment Kafdrop, coherente con las esperas ya declaradas para los otros
servicios dependientes. También se añadió al inventario de sincronización el
reconciliador S03 existente y su configuración no secreta, necesarios para
la fase `apis`. Estos cambios requieren un nuevo SHA publicado, sus
preflights y un despliegue controlado; no están activos en K3s.

El operador publicó después, por su cuenta, el SHA
`d743b545fbfccf86e99b815c67de7459b1281848` con esos cinco archivos;
el checkout local está limpio. El log de preflight `infra-prod` de este SHA
se corta justo después de `Preflight de Secrets OK`, sin estado final del job.
El preflight `apis-frontend-prod` del mismo SHA falla antes de desplegar por
los siete Secrets S03 de clientes y `apis/s07a-kafka-ca` ausentes. La fase API
sigue pendiente de reconciliación de clientes tras completar `infra-prod`.

El operador aportó el log posterior del job `deploy infra-prod` en
`d743b545`: Skaffold estabilizó todos los recursos, incluido Kafdrop con su
espera nueva. La verificación CI falló al ejecutar
`reconcile-keycloak-web-prod.sh`: `kubectl exec` seleccionó por defecto
`s03-tls-proxy` y allí no existe `kcadm`. El job no alcanzó la
reconciliación web, la comprobación del issuer ni los demás checks de
infraestructura. Se preparó localmente la selección explícita del contenedor
`keycloak` en el motor existente. No está publicada ni ejecutada; requiere
otro SHA y la repetición de sus gates.

El operador aportó después logs de `35f781eb`: el job `deploy infra-prod`
estabilizó los nueve recursos, reconcilió el cliente web de Keycloak con
`PASS` y verificó el issuer OIDC; `verify_mongodb_alignment` terminó con
`aligned: true`. `sync-scripts` instaló el reconciliador S03 y su inventario.
En el host Hetzner, el reconciliador creó siete clientes de servicio con
`s03_keycloak_reconciliation=PASS`. El operador trasladó sus `.env` a
`~/trust-news/secrets/clients` y ejecutó la fase `apis` con esa ruta explícita.
La salida aportada de `check_configured_secrets.sh --phase apis` pasó para
nueve servicios S03, Kafka y los Secrets de aplicación, sin mostrar valores.
El directorio operativo de Hetzner no es un checkout Git. Falta el preflight
CI `apis-frontend-prod` del mismo SHA antes de su despliegue.

El log posterior de preflight CI `apis-frontend-prod` en `35f781eb` terminó
con `Job succeeded`: TLS servido verificado, Secrets S03/Kafka y de aplicación
correctos, y snapshot de revisiones capturado para 11 Deployments. Ese job
no construyó ni desplegó APIs. Sigue pendiente el pipeline `deploy` del mismo
SHA con Blockchain OFF y la verificación efectiva posterior en K3s.

El job `deploy apis-frontend-prod` de `35f781eb` pasó Secrets y capturó 11
revisiones; comprobó MongoDB alineado, cero órdenes BLOCKCHAIN pendientes y
preparó el modo OFF. Skaffold aplicó parte de los manifiestos, pero falló en
los tres Services `validate-service-{1,2,3}` porque el puerto `8070` no tenía
nombre junto al puerto `s03-https:9443`. No se alcanzó la verificación final.
El job automático `rollback` restauró las revisiones de los 11 Deployments y
terminó correctamente, pero no esperó a que estuvieran disponibles ni revirtió
Services o ConfigMaps. La captura posterior muestra `news-handler` en `0/1`
con `CrashLoopBackOff`; los tres Services de validación conservan solo
`8070/TCP`. El log del contenedor revela `security_protocol=SSL` sin
`ssl_context` al crear `AIOKafkaProducer`. La imagen efectiva restaurada es
`v0.0.13-4-g5a1e011@sha256:4267ee68…` y el ConfigMap establece `SSL`.
El código fuente actual pasa ese contexto mediante el motor Kafka compartido;
falta identificar la revisión/imagen nueva antes de decidir la recuperación.
La corrección local añade `name: http` a los tres Services prod,
coherente con sus equivalentes locales. El render del perfil muestra 11
Services, sin puertos múltiples anónimos ni nombres duplicados. Mantener el
lock, recuperar `news-handler` y después publicar un nuevo SHA y repetir los
gates; no reutilizar el deploy fallido.

El siguiente despliegue necesita también que el gate de órdenes pendientes
funcione con `news-handler` caído. El script local ahora consulta MongoDB
directamente, tomando base y colección de `news-handler-config`; se verificó
con `kubectl` simulado para cero y dos pendientes. Falta publicar y validar
esa versión en K3s antes de considerarla operativa.

## Fotografía local, 2026-11-11

| Campo | Resultado comprobado | Para fijar el candidato |
| --- | --- | --- |
| Rama y base | `postTFM`, `HEAD=3c50add31740f710951926f993d3f700a52bf7c4`; 18 rutas modificadas o eliminadas antes de crear esta ficha | Elegir y revisar el diff; publicar un SHA inmutable autorizado. El HEAD actual no contiene la corrección de GUI ni el certificado local. |
| SHA en GitLab | La referencia local `gitlab/postTFM` está en `62c5df69217a6fa8af7c3249da7c286bf2b487fa`; puede estar desactualizada | Verificar la rama protegida en GitLab antes de crear un pipeline. No inferir el remoto a partir de esta referencia local. |
| Imágenes | `infra-prod`: `keycloak`, `gateway`; `apis-frontend-prod`: `generate-asertions`, `validate-asertions`, `news-handler`, `news-chain`, `ipfs-api`, `evidence-search`, `source-router`, `gateway`, `admin`, `web-classic` | Guardar por perfil el `build.json` del job `build` del **mismo SHA**, con imagen y digest. El artefacto caduca al día. Comparar con `imageID` de cada contenedor tras el despliegue. `news-chain` se construye incluso con Blockchain OFF; eso no implica que se ejecute. |
| Perfiles del clúster existente | `infra-prod` y después `apis-frontend-prod` si se incorpora S03/S07a; `traefik-prod` solo ante cambio de chart/configuración Traefik | Ejecutar cada perfil en una ventana serial, con pipeline y artefacto propios del mismo SHA. `setup` corresponde a clúster limpio. No ejecutar `blockchain-prod` ni `news-chain-prod` para LIGHT/SMART OFF. |
| Render estático | Los cinco overlays de `infra-prod`, los trece de `apis-frontend-prod` y el de `blockchain-prod` renderizan; `s03-runtime` usa issuer público `https://assermetry.com/auth/realms/TrustNews`, JWKS interno HTTPS y CA montada; Evidence Search declara `SMART`; Geth declara cero réplicas | Repetir el render en el SHA publicado y comparar con la configuración que realmente reciban los pods. Los Secrets S03/S07a se provisionan fuera del repositorio en K3s. |
| Blockchain | `.gitlab-ci.yml` tiene `BLOCKCHAIN_ENABLED=OFF` por defecto; el modo se aplica con `set-blockchain-mode.sh` tras el perfil API | Seleccionar `OFF` explícitamente y comprobar `apis/blockchain-mode=false`, valor efectivo dentro de Gateway/News Handler/validadores, cero pendientes BLOCKCHAIN antes del corte, y cero réplicas de Geth y `news-chain` después. |
| Preflight CI | `PIPELINE_ACTION=preflight` solo admite `infra-prod` y `apis-frontend-prod`. Comprueba acceso Kubernetes, certificado servido por Traefik con CA y hostname, Secrets con `scripts/check_configured_secrets.sh` y, para API, captura revisiones. No construye ni despliega. | Ejecutarlo en el SHA protegido final y conservar ID, hora, perfil y resultado. El motor comprueba S03, S07a (incluida cadena y SAN) y los Secrets de aplicación, sin mostrar valores; `deploy` repite la fase antes de mutar recursos. |
| Lock y concurrencia | La guía documenta un Maintenance lock de Cloudflare; su estado actual no está comprobado. La CI no define `resource_group`. | El operador verifica y registra el estado del lock antes de la ventana, mantiene el acceso externo cerrado durante el cambio y evita pipelines concurrentes. Registrar responsable y criterio para abrir/cerrar la ventana. |
| Observación | La guía prevé Loki/Grafana, estado Ready, rutas, errores y coste | Fijar periodo de observación, responsable y umbrales antes de desplegar. Conservar solo métricas y resultados redactados, sin tokens, cuerpos, IP ni identificadores de Cloudflare. |
| Rollback | `rollout-revisions.sh` captura las revisiones de diez Deployments API y `frontend-web`; el job `rollback` restauró las 11 revisiones tras el fallo real de `apis-frontend-prod` en `35f781eb`. No esperó disponibilidad: `news-handler` quedó `0/1` en la captura posterior. Antes del rollout, la CI ejecuta `realign-source-routing-mongodb.sh --apply`, que puede modificar MongoDB. | Conservar snapshot y artefacto del pipeline anterior, imagen/digest, manifiestos, Secrets anteriores validados y respaldo de datos. El job no revierte Services, ConfigMaps, Ingress, Kafka, Keycloak, MongoDB ni PVC; preparar recuperación por componente y datos antes de la ventana. El éxito del job no acredita recuperación funcional. |

## Revisión local del candidato, 2026-11-13

| Área | Resultado de solo lectura | Consecuencia para el candidato |
| --- | --- | --- |
| Checkout | Rama `postTFM`, `HEAD=3c50add31740f710951926f993d3f700a52bf7c4`; 19 rutas versionadas modificadas/eliminadas (`+400/-784`) y esta ficha aún sin seguimiento. | El SHA de `HEAD` no incluye los cambios locales revisados. Delimitar los cambios que entrarán al candidato antes de fijarlo. |
| Runtime frontend | Cambios en navegación responsive y gate visual hasta completar autenticación; logout y restauración de página ocultan la aplicación. | Revisar el diff y la aceptación de GUI/login como parte del SHA exacto. |
| TLS local | `fullchain.pem` actual es autofirmado para `localhost` con SAN `DNS:localhost`. `overlays/local` genera `trustnews-origin-tls` desde ese certificado y `privkey.pem`; `overlays/prod` no contiene ese generador. `web_classic/Dockerfile` solo copia `./app` a la imagen. | El certificado/keypair pertenecen al camino local y no deben sustituir TLS/Secrets de K3s. |
| Clave TLS local | `web_classic/certs/privkey.pem` se usa solo con `overlays/local` para `localhost`; no se usa en Hetzner. El 13-11-2026 se generó un par local nuevo y la ruta se retiró del índice y añadió a `.gitignore`. La key anterior sigue en la historia Git local (commit observado `78638d9`, 2026-01-24); no se consultó el remoto en vivo. | Mantener el par solo en el entorno local. No hace falta rotar TLS de Hetzner por esta key; el origen K3s usa su Secret independiente. La eliminación del índice no borra objetos históricos. |
| Documentación | README y runbooks enlazan las guías nuevas; se eliminaron `docs/quick_start_local.md` y `docs/quick_start_hetzner.md`. | Confirmar que la migración conserva todos los procedimientos necesarios para la ventana. |
| Recuperación | Fotografía del 13-11: entonces no había copias acreditadas; posteriormente el operador comunicó copias externas de MongoDB y PostgreSQL. La CI puede aplicar `realign-source-routing-mongodb.sh --apply` antes del rollout API. | Verificar el respaldo y el procedimiento de recuperación para la ventana; la restauración aislada sigue sin demostrarse. |

## Secuencia de fijación y ventana, sin ejecución en esta ficha

Actualización 2026-11-13: el operador confirma cerradas las pruebas locales del
camino declarativo S03 en kind. El preflight local actual pasó para nueve
servicios. Esto no fija un candidato ni acredita Hetzner/K3s.

1. Cerrar la revisión del diff, resolver el tratamiento de la clave TLS local
   versionada y seleccionar el SHA que formará el candidato. Publicarlo en la
   rama protegida solo con autorización del operador. Registrar SHA completo,
   hora UTC y responsable. Cualquier cambio posterior exige otro candidato.
2. En GitLab, seleccionar `PIPELINE_ACTION=preflight`, primero con
   `PROFILE=infra-prod` y luego con `PROFILE=apis-frontend-prod`, ambos en el
   mismo SHA. El preflight ejecuta `scripts/check_configured_secrets.sh` en
   cada fase antes de `deploy`; registrar ambos resultados. Comprobar respaldo
   recuperable y estado del lock. Un preflight correcto no prueba que el
   despliegue posterior funcione.
3. Cuando la ventana esté autorizada, mantener el lock activo y ejecutar el
   pipeline protegido de `infra-prod` con `BLOCKCHAIN_ENABLED=OFF`. Conservar
   su `build.json`; comprobar Keycloak, Kafka TLS, JWKS y pods Ready. Después
   ejecutar `apis-frontend-prod` en el **mismo SHA** y con `OFF`, conservando
   su propio `build.json` y snapshot de revisiones. No solapar pipelines.
4. Comparar cada digest construido con el `imageID` de los contenedores
   desplegados. Leer solo variables no sensibles permitidas dentro de los pods:
   `EVIDENCE_EXTRACTION_MODE`, `BLOCKCHAIN_ENABLED`, `S03_ENABLED`,
   `KEYCLOAK_ISSUER_URL`, `KEYCLOAK_JWKS_URL`, `KAFKA_SECURITY_PROTOCOL` y
   rutas de CA. Comprobar Ready, TLS/JWKS, Kafka TLS, lock y rutas positivas y
   denegadas. El valor de un ConfigMap no sustituye la observación del pod.
5. Observar errores, rechazos, latencia, cuotas y coste durante la ventana
   acordada. Ante una desviación, mantener el lock y decidir rollback con el
   snapshot previo. Restaurar ConfigMaps/Ingress/Secrets/datos con sus
   procedimientos específicos cuando proceda; comprobar de nuevo la entrada
   y el modo OFF antes de retirar el lock. Una restauración de Deployments no
   revierte escrituras ni migraciones de MongoDB.

## Evidencia que debe adjuntarse al candidato final

Comandos de lectura para la ventana **después** del despliegue autorizado;
ejecutarlos solo tras comprobar el contexto K3s. No imprimen valores de
Secrets ni cabeceras de autenticación:

```bash
kubectl config current-context
kubectl -n apis get configmap blockchain-mode \
  -o jsonpath='{.data.BLOCKCHAIN_ENABLED}{"\n"}'
kubectl -n apis exec deployment/evidence-search -c evidence-search -- \
  python -c 'import os; print("EVIDENCE_EXTRACTION_MODE=" + os.getenv("EVIDENCE_EXTRACTION_MODE", "<absent>"))'
kubectl -n apis exec deployment/news-handler -c news-handler -- \
  python -c 'import os; print("BLOCKCHAIN_ENABLED=" + os.getenv("BLOCKCHAIN_ENABLED", "<absent>")); print("KAFKA_SECURITY_PROTOCOL=" + os.getenv("KAFKA_SECURITY_PROTOCOL", "<absent>"))'
kubectl -n apis get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{range .status.containerStatuses[*]}{.name}{"="}{.imageID}{" "}{end}{"\n"}{end}'
kubectl -n frontend get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{range .status.containerStatuses[*]}{.name}{"="}{.imageID}{" "}{end}{"\n"}{end}'
kubectl -n blockchain get statefulset \
  -o custom-columns=NAME:.metadata.name,REPLICAS:.spec.replicas
kubectl -n apis get deployment news-chain --ignore-not-found \
  -o custom-columns=NAME:.metadata.name,REPLICAS:.spec.replicas
```

Repetir la lectura de variables en **cada réplica** si el Deployment tiene
más de una; `kubectl exec deployment/...` selecciona solo un pod. Comparar los
`imageID` con los digests del `build.json` del perfil correspondiente.

| Evidencia | Valor esperado |
| --- | --- |
| SHA GitLab protegido y diff revisado | Un SHA único para los dos perfiles; árbol de build sin cambios locales |
| `build.json` de cada perfil y digests efectivos | Imagen, digest construido e `imageID` observado por contenedor; coincidencia explicada para `gateway`, construido en ambos perfiles |
| Render y configuración efectiva | Issuer, JWKS, CA, SMART, Kafka SSL y Blockchain OFF observados en el destino |
| Preflight CI | Dos jobs del mismo SHA, IDs/horas/resultado; TLS servido con CA y hostname verificados |
| Lock, observación y rollback | Estado antes/durante/después, responsable, snapshot anterior, artefactos retenidos, umbrales y resultado de recuperación |

**Bloqueo registrado el 13-11-2026:** faltan el SHA publicado que incluya el
diff elegido, sus imágenes/digests, la verificación viva de K3s y los dos
preflights del candidato.
También están pendientes la revisión de la clave local versionada y un respaldo
recuperable para los datos que la CI puede modificar. No se ha tocado Hetzner
ni GitLab para elaborar esta ficha.

## Auditoría local de cierre, 2026-11-15

Esta entrada actualiza el estado de la ficha; las fotografías anteriores se
conservan como historial. El checkout local está en `postTFM`,
`b860ab991f10e8b66107e3fa9c59cd810e3c5fb3`. `origin/postTFM` coincide
localmente, pero esa referencia no acredita el remoto actual. La referencia
local `gitlab/postTFM` sigue en `62c5df6`; la consulta de solo lectura al
remoto GitLab no terminó porque este entorno no resolvió `gitlab.com`. No hay
etiqueta `v0.0.13b` local. El árbol conserva cambios documentales sin commit
en `docs/version.md`, `working.md`, `docs/releases.md`,
`docs/next_releases.md` y esta ficha para asignar el alta OAuth API a
v0.0.13c y registrar la auditoría.

En el código del HEAD están `name: http` en el puerto 8070 de los tres
Services de validación de producción, el contexto TLS compartido para Kafka
usado por News Handler y la consulta directa a MongoDB del gate de órdenes
BLOCKCHAIN pendientes. El operador confirma que v0.0.13b está desplegada en
Hetzner/K3s; falta vincular ese despliegue a un SHA y sus imágenes efectivas,
por lo que esta revisión estática no acredita qué versión corre allí. La clave
TLS local `web_classic/certs/privkey.pem` no está versionada y figura en
`.gitignore`.
El contexto Kubernetes activo en esta máquina es `kind-trust-news`; no se
consultó K3s. Tampoco se ejecutaron pruebas ni pipelines en esta auditoría.

La evidencia comunicada por el operador cubre parte de S03 y negativos
anónimos de S11-D. Siguen sin vincularse al **SHA desplegado** los dos preflights
CI, `build.json` y digests por perfil, imágenes/configuración efectivas y
salud en K3s, aceptación integral S02/S03/S07a, positivos y negativos
restantes de S11-D, campaña S12-D, respaldo recuperable y decisión GO/NO-GO
de una ventana concreta. El estado de v0.0.13b permanece **NO-GO para
clientes** hasta registrar esas pruebas. El siguiente paso verificable es
identificar en GitLab el SHA y los pipelines que produjeron el despliegue
existente y comparar sus artefactos con K3s. Solo si falta un preflight del
SHA efectivo habrá que planificarlo; no se presupone un nuevo despliegue.

### Evidencia posterior del pipeline de despliegue, 2026-11-15

El operador aporta captura del pipeline GitLab `#3070111046`, rama `postTFM`,
commit abreviado `722c1d57` (SHA local completo
`722c1d570f8c85f36539bea356a2848a19d7cc5a`). El pipeline figura
`Passed`; los jobs `build`, `check_phase6_origin_tls` y `deploy` aparecen
correctos, mientras `rollback` quedó sin ejecutar. El operador confirma
despliegue y salud OK en Hetzner; aclara que no ha confirmado la aceptación
completa S02/S03/S07a, S11-D ni S12-D. La captura no muestra el perfil
seleccionado ni `BLOCKCHAIN_ENABLED`; el operador aportó después el artefacto
`build.json` del job `build`. Tampoco están documentados el pipeline de
infraestructura, los `imageID` efectivos ni los resultados completos de
S11-D/S12-D. Se registra como evidencia de CI y confirmación operativa, sin
atribuirle las pruebas que no aparecen en ella.

El `build.json` aportado contiene estas imágenes y digests:

| Imagen | Tag | Digest SHA-256 |
| --- | --- | --- |
| `generate-asertions` | `722c1d5` | `f112ff69550317265f388746970a0d9a123617f0870529a038b575c70f9839c9` |
| `validate-asertions` | `722c1d5` | `363fd41d01912dba821dafc2ec05c2a5175df75cd082599aedcb7ef157090870` |
| `news-handler` | `722c1d5` | `d2793ca90184ac5410f4fb0e9a991a3fb149f0abdbd9550b0f8713d477f1631a` |
| `news-chain` | `722c1d5` | `2cdaae18d877651e019c4466cce71698c5df1b7aba3a85b45796a4a4abe36631` |
| `ipfs-api` | `722c1d5` | `fde4bf73cc83e4288094bb5b73136ed3201392426ed19497f658ae29725d5fd3` |
| `evidence-search` | `722c1d5` | `99b42047e0036ce525cb2ad83a3bc7f28e6657952d549b4f166767d2074659c7` |
| `source-router` | `722c1d5` | `a5ffb30e881531aaaf39d03d4a394e64be68423d4b99844c212f62942a98bce9` |
| `gateway` | `722c1d5` | `c45bfc8ab38c0cff17d8550c91393cc017d99cf22deaf54932972e7bedce4e39` |
| `admin` | `722c1d5` | `2570f3150b6e4edcee86c2621fc38886159d81e488a8541723efe414afae7761` |
| `web-classic` | `722c1d5` | `7ac32f673e64c5d3f234219ec18d4698906bbbdd1c9af4a23fa60e55f57aa352` |

La comparación local muestra que `722c1d57` es ancestro de
`b860ab991f10e8b66107e3fa9c59cd810e3c5fb3`; los commits intermedios
añaden scripts operativos, pruebas y documentación, sin modificar código API,
manifiestos K8s ni `.gitlab-ci.yml`. Esto permite separar el runtime del
pipeline de los cambios posteriores del motor S03, cuya sincronización y
ejecución ya están registradas por el operador en `working.md`.

El operador aportó `build.json` antes de su caducidad. El siguiente paso es
confirmar el perfil/modo del pipeline. El pipeline correcto y la salud
comunicada no sustituyen la aceptación funcional ni un GO para clientes.

### Inventario de pods e imágenes comunicado por el operador, 2026-11-15

Desde el host Hetzner, el operador informó contexto `default` y recogió
manualmente pods de los namespaces `apis` y `frontend`, porque el motor de
inventario no está instalado en `~/trust-news`. Todos los pods mostrados
figuraban `Running` y sus contenedores `ready=true`. Los `imageID` comunicados
coinciden con los diez digests de `build.json`: los nueve componentes API/web
y el digest de `gateway` usado por los sidecars `s03-tls-proxy`. `news-chain`
no aparece entre los pods, coherente con que no esté activo en este perfil.
La salida no incluye el namespace `blockchain`, por lo que no determina por sí
sola si hay workloads Geth u otros componentes allí. Es una comprobación
operativa comunicada, no una consulta independiente. Aún falta documentar el
perfil del pipeline y confirmar `BLOCKCHAIN_ENABLED` y los modos efectivos
LIGHT/SMART en K3s; después se continúa con las pruebas de aceptación.

### Configuración efectiva comunicada por el operador, 2026-11-15

En el contexto Hetzner `default`, el operador informó `apis/blockchain-mode`
con `BLOCKCHAIN_ENABLED=false`, `news-handler` con `BLOCKCHAIN_ENABLED=false`
y `KAFKA_SECURITY_PROTOCOL=SSL`, y `evidence-search` con
`EVIDENCE_EXTRACTION_MODE=SMART`. Los StatefulSets `geth-bootnode`,
`geth-miner` y `geth-rpc-endpoint`, así como el Deployment `news-chain`,
figuraban con cero réplicas. Esto confirma las lecturas indicadas, no la
configuración de Gateway y validadores ni el modo de cada réplica de
Evidence Search. El perfil seleccionado en el pipeline sigue sin evidencia.

En una consulta posterior, Gateway y los tres workers de validación
devolvieron `BLOCKCHAIN_ENABLED=false`; las dos réplicas de Evidence Search
devolvieron `EVIDENCE_EXTRACTION_MODE=SMART`. Evidence Search mostró
`BLOCKCHAIN_ENABLED=<absent>`, variable que no corresponde a su modo operativo.
Con estas lecturas queda cubierto el estado efectivo de Blockchain OFF en
Gateway, News Handler y validadores, más SMART en cada réplica de Evidence
Search. La salida sigue siendo evidencia operativa aportada por el operador.

### Prueba local del motor S02, 2026-11-15

Se ejecutó `PYTHONPATH=api .venv/bin/pytest -q
tests/api/test_public_fetch.py`: **9 passed**. La prueba cubre política de
destinos, DNS mixto y cambios de respuesta, redirección a loopback, límites de
cuerpo/tiempo y TLS con comprobación de hostname/SNI. La prueba TLS abre un
servidor efímero en `127.0.0.1`; el primer intento bajo el aislamiento local
no pudo enlazar el socket y pasó al repetirse con permiso para loopback. Es
evidencia del motor en el checkout local, no ejecución en Hetzner/K3s ni
aceptación de extremo a extremo de S02. El `kubectl` disponible en esta sesión
usa `kind-trust-news`, por lo que no se consultó ni modificó el clúster remoto.

### Confirmación operativa de S02 en Hetzner, 2026-11-15

El operador indica que S02 también queda verificado en Hetzner/K3s. Se registra
como confirmación del operador; no se aportó un resultado detallado o artefacto
que permita asociar los casos ejecutados al SHA/digests. La suite local
`tests/api/test_public_fetch.py` (9 passed) es evidencia separada y no se usa
como sustituto de esa aceptación preproductiva. Próximo paquete: aceptación S03
en Hetzner/K3s.

### Prueba local de autorización S03, 2026-11-15

A petición del operador se ejecutó `PYTHONPATH=api .venv/bin/pytest -q
tests/api/test_s03_security.py`: **5 passed**. Se probaron las denegaciones
401 sin identidad, sin identidad humana, con cliente de servicio incorrecto y
con firma/issuer/audience/cliente/expiración JWT inválidos; el caso de recurso
de otro propietario devolvió 403 y el acceso propio 200. La política de ruta
usó verificadores e identidades simulados; la prueba de JWT usó una clave RSA
efímera. Esto valida localmente el motor, no tokens de Keycloak ni las rutas
desplegadas en Hetzner/K3s. El contexto de esta sesión sigue siendo
`kind-trust-news`; por ello la aceptación S03 de preproducción permanece
pendiente.
