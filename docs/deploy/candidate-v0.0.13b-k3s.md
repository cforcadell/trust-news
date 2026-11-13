# Candidato v0.0.13b para Hetzner/K3s

**Estado: preparación; candidato no fijado.** Esta ficha separa el resultado
estático del repositorio de la evidencia que solo puede producir un pipeline
protegido y el clúster K3s. No autoriza despliegue ni apertura de demos.

## Fotografía local, 2026-11-11

| Campo | Resultado comprobado | Para fijar el candidato |
| --- | --- | --- |
| Rama y base | `postTFM`, `HEAD=3c50add31740f710951926f993d3f700a52bf7c4`; 18 rutas modificadas o eliminadas antes de crear esta ficha | Elegir y revisar el diff; publicar un SHA inmutable autorizado. El HEAD actual no contiene la corrección de GUI ni el certificado local. |
| SHA en GitLab | La referencia local `gitlab/postTFM` está en `62c5df69217a6fa8af7c3249da7c286bf2b487fa`; puede estar desactualizada | Verificar la rama protegida en GitLab antes de crear un pipeline. No inferir el remoto a partir de esta referencia local. |
| Imágenes | `infra-prod`: `keycloak`, `gateway`; `apis-frontend-prod`: `generate-asertions`, `validate-asertions`, `news-handler`, `news-chain`, `ipfs-api`, `evidence-search`, `source-router`, `gateway`, `admin`, `web-classic` | Guardar por perfil el `build.json` del job `build` del **mismo SHA**, con imagen y digest. El artefacto caduca al día. Comparar con `imageID` de cada contenedor tras el despliegue. `news-chain` se construye incluso con Blockchain OFF; eso no implica que se ejecute. |
| Perfiles del clúster existente | `infra-prod` y después `apis-frontend-prod` si se incorpora S03/S07a; `traefik-prod` solo ante cambio de chart/configuración Traefik | Ejecutar cada perfil en una ventana serial, con pipeline y artefacto propios del mismo SHA. `setup` corresponde a clúster limpio. No ejecutar `blockchain-prod` ni `news-chain-prod` para LIGHT/SMART OFF. |
| Render estático | Los cinco overlays de `infra-prod`, los trece de `apis-frontend-prod` y el de `blockchain-prod` renderizan; `s03-runtime` usa issuer público `https://assermetry.com/auth/realms/TrustNews`, JWKS interno HTTPS y CA montada; Evidence Search declara `SMART`; Geth declara cero réplicas | Repetir el render en el SHA publicado y comparar con la configuración que realmente reciban los pods. Los Secrets S03/S07a se provisionan fuera del repositorio en K3s. |
| Blockchain | `.gitlab-ci.yml` tiene `BLOCKCHAIN_ENABLED=OFF` por defecto; el modo se aplica con `set-blockchain-mode.sh` tras el perfil API | Seleccionar `OFF` explícitamente y comprobar `apis/blockchain-mode=false`, valor efectivo dentro de Gateway/News Handler/validadores, cero pendientes BLOCKCHAIN antes del corte, y cero réplicas de Geth y `news-chain` después. |
| Preflight CI | `PIPELINE_ACTION=preflight` solo admite `infra-prod` y `apis-frontend-prod`. Comprueba acceso Kubernetes y certificado servido por Traefik con CA y hostname; para API captura revisiones. No construye ni despliega. | Ejecutarlo en el SHA protegido final y conservar ID, hora, perfil y resultado. En `deploy`, el job vuelve a comprobar S03 por fase. Comprobar aparte presencia de Secrets S07a por nombres/claves y cadena/SAN, sin mostrar valores. |
| Lock y concurrencia | La guía documenta un Maintenance lock de Cloudflare; su estado actual no está comprobado. La CI no define `resource_group`. | El operador verifica y registra el estado del lock antes de la ventana, mantiene el acceso externo cerrado durante el cambio y evita pipelines concurrentes. Registrar responsable y criterio para abrir/cerrar la ventana. |
| Observación | La guía prevé Loki/Grafana, estado Ready, rutas, errores y coste | Fijar periodo de observación, responsable y umbrales antes de desplegar. Conservar solo métricas y resultados redactados, sin tokens, cuerpos, IP ni identificadores de Cloudflare. |
| Rollback | `rollout-revisions.sh` captura las revisiones de diez Deployments API y `frontend-web`; el job `rollback` intenta restaurarlas si falla `apis-frontend-prod`. Antes del rollout, la CI ejecuta `realign-source-routing-mongodb.sh --apply`, que puede modificar MongoDB. | Conservar snapshot y artefacto del pipeline anterior, imagen/digest, manifiestos, Secrets anteriores validados y respaldo de datos. El job no revierte ConfigMaps, Ingress, Kafka, Keycloak, MongoDB ni PVC; preparar recuperación por componente y datos antes de la ventana. No considerar probado en K3s el rollback automático por un fallo real. |

## Revisión local del candidato, 2026-11-13

| Área | Resultado de solo lectura | Consecuencia para el candidato |
| --- | --- | --- |
| Checkout | Rama `postTFM`, `HEAD=3c50add31740f710951926f993d3f700a52bf7c4`; 19 rutas versionadas modificadas/eliminadas (`+400/-784`) y esta ficha aún sin seguimiento. | El SHA de `HEAD` no incluye los cambios locales revisados. Delimitar los cambios que entrarán al candidato antes de fijarlo. |
| Runtime frontend | Cambios en navegación responsive y gate visual hasta completar autenticación; logout y restauración de página ocultan la aplicación. | Revisar el diff y la aceptación de GUI/login como parte del SHA exacto. |
| TLS local | `fullchain.pem` actual es autofirmado para `localhost` con SAN `DNS:localhost`. `overlays/local` genera `trustnews-origin-tls` desde ese certificado y `privkey.pem`; `overlays/prod` no contiene ese generador. `web_classic/Dockerfile` solo copia `./app` a la imagen. | El certificado/keypair pertenecen al camino local y no deben sustituir TLS/Secrets de K3s. |
| Clave TLS local | `web_classic/certs/privkey.pem` se usa solo con `overlays/local` para `localhost`; no se usa en Hetzner. El 13-11-2026 se generó un par local nuevo y la ruta se retiró del índice y añadió a `.gitignore`. La key anterior sigue en la historia Git local (commit observado `78638d9`, 2026-01-24); no se consultó el remoto en vivo. | Mantener el par solo en el entorno local. No hace falta rotar TLS de Hetzner por esta key; el origen K3s usa su Secret independiente. La eliminación del índice no borra objetos históricos. |
| Documentación | README y runbooks enlazan las guías nuevas; se eliminaron `docs/quick_start_local.md` y `docs/quick_start_hetzner.md`. | Confirmar que la migración conserva todos los procedimientos necesarios para la ventana. |
| Recuperación | `working.md` registra que aún no existen copias de MongoDB ni Keycloak/PostgreSQL en preproducción; la CI puede aplicar `realign-source-routing-mongodb.sh --apply` antes del rollout API. | No abrir la ventana de despliegue hasta disponer de respaldo recuperable y del procedimiento de restauración de datos/configuración. |

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
   mismo SHA. Registrar los dos resultados. Comprobar respaldo recuperable,
   Secrets S03/S07a por nombres y claves, certificados y estado del lock. Un
   preflight correcto no prueba que el despliegue posterior funcione.
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

**Bloqueo actual:** faltan el SHA publicado que incluya el diff elegido, sus
imágenes/digests, la verificación viva de K3s y los dos preflights del candidato.
También están pendientes la revisión de la clave local versionada y un respaldo
recuperable para los datos que la CI puede modificar. No se ha tocado Hetzner
ni GitLab para elaborar esta ficha.
