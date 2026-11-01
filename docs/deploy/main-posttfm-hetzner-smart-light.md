# v0.0.13: despliegue LIGHT en Hetzner desde `postTFM`

**Revisión documental: 2026-11-01. Estado de v0.0.13: Deploying; no consta despliegue ni validación viva en Hetzner de esta revisión.** El alcance incorporado y lo pendiente están en [version.md](../version.md) e [issues.md](../issues.md). Esta guía compara el commit local `postTFM` (`da356fd`) con la referencia local `origin/main` (`3a7f519`); antes de operar hay que hacer `git fetch` y repetir la comparación. La rama local `main` apunta a `736cf67` (2025-07-05) y no sirve de base actual. Las referencias divergen (3 commits solo en `origin/main`, 53 solo en `postTFM`): la promoción requiere reconciliación, pruebas y revisión.

**Modo previsto de Evidence Search: SMART.** El commit `da356fd` y el ConfigMap actual seleccionan SMART; el overlay productivo hereda ese valor. Las campañas locales [SMART](../../tests/data/evaluation/artifacts/e2e-20261031-181209/report.md) y [DIRECT](../../tests/data/evaluation/artifacts/e2e-20261101-101658/report.md) son diagnósticas; DIRECT obtuvo 12/22 unidades e2e estrictas y tres fallos de ejecución frente a 19/22 y cero fallos técnicos en SMART. Cambió también la configuración observada de generación. Ninguna campaña acredita por sí sola aceptación en Hetzner. Un cambio futuro a DIRECT requiere otra revisión versionada y validación.

Los comandos de esta guía son instrucciones para el operador, no una constancia de ejecución. Los scripts de copia/restauración se añaden al repositorio; no se cambian manifiestos, secretos ni servicios durante esta revisión.

## Resultado ejecutivo

| Objetivo | Estado en `postTFM` | Consecuencia |
| --- | --- | --- |
| Blockchain desactivada por defecto | `.gitlab-ci.yml` fija `BLOCKCHAIN_ENABLED=OFF`; `set-blockchain-mode.sh` también usa `OFF` si falta la variable. Los StatefulSets de Geth y el Deployment `news-chain` declaran cero réplicas. | Para desplegar LIGHT, usar explícitamente `PROFILE=apis-frontend-prod`, `BLOCKCHAIN_ENABLED=OFF`. Comprobar el ConfigMap y los pods después; no basta el valor de CI. |
| Modo de Evidence Search | El commit y el checkout actual fijan SMART. El overlay productivo incluye la base sin sobrescribirla; el Deployment declara dos réplicas. | Verificar SMART en el SHA, ConfigMap y ambos pods; un cambio de modo requiere nueva revisión y prueba. |
| Adquisición documental | `EVIDENCE_ALLOW_PROVIDER_EXTRACT: "false"`. SMART usa `raw_content` completo de Search si es válido y luego HTTP directo; DIRECT usa HTTP directo. | Ninguno añade el fallback `provider_extract` tras un 403 con esta configuración. Habilitarlo requeriría cambio versionado, medición de coste y aceptación. |
| Estado de v0.0.13 | Alcance de desarrollo documentado; release Deploying. | Desplegar para validar no equivale a publicarla ni etiquetarla. Persisten incidencias P1 y pruebas de aceptación. |

## Alcance real del diff

Comparación de contenido `git diff origin/main postTFM`: **326 archivos cambiados**, unas 38 362 líneas añadidas y 48 099 retiradas. Es un salto funcional y de configuración, no una mera conmutación de dos flags. Para revisar lo que aporta *solo* la rama desde la base común, usar `git diff origin/main...postTFM`; para saber qué recibirá `main` al fusionar, revisar también `git diff origin/main postTFM` y los 3 commits exclusivos de `main`.

| Área | Cambios relevantes para el despliegue y la aceptación |
| --- | --- |
| Flujo de órdenes | Separación LIGHT/BLOCKCHAIN, propagación del modo por Gateway, News Handler y validadores; gate de órdenes auditables nuevas al apagar Blockchain. Kafka y los servicios LIGHT permanecen activos. |
| Extracción/LLM | Proveedor estructurado compartido, cambios de esquema/prompt y metadatos de aserción; el overlay productivo de Generate Assertions pasa de Gemini a OpenRouter `openai/gpt-5-nano`. Revalidar calidad y latencia; una prueba aislada del modelo no representa la ruta GUI completa. |
| Búsqueda y evidencia | Nuevo Source Router dinámico y taxonomía; proveedores de búsqueda desacoplados; Evidence Search incorpora motor `DIRECT`/`PROVIDER`/`SMART`, descarga HTML/PDF, trazas de adquisición, snapshots, historial negativo, cachés y presupuesto de reintentos. Se sustituyen colecciones antiguas de rutas/caché. |
| Validación y consenso | Contrato de citas `context_id`, abstención/errores explícitos, scoring, timeouts/reintentos acotados y captura diagnóstica. Los validadores LIGHT dependen de Kafka, Router y Evidence Search; con `OFF` no esperan a Geth. |
| API/seguridad/GUI | JWT con audiencia y cliente, aislamiento de órdenes/validaciones, rutas administrativas; frontend bajo `/gui` con middleware StripPrefix y coincidencia estricta de prefijos Traefik; cambios de estados, fechas, evidencia, idiomas y vista de costes. La migración a `/gui` implica validar Traefik, ingress, redirecciones y Keycloak juntos. |
| Infraestructura | Perfil productivo incorpora Source Router, recursos/probes y dos réplicas de Evidence Search; pipeline añade preflight de TLS, realineación MongoDB antes del rollout, cambio de modo Blockchain y comprobaciones de `/gui`. Persisten riesgos de autenticación SSH/K3s del CI. |
| Pruebas/artefactos | Nuevas suites API, frontend, E2E, evaluación, viewer y comparador DIRECT/SMART. La presencia de un test o un artefacto no acredita que el commit actual haya pasado contra Hetzner. |

Archivos de referencia: [Skaffold](../../skaffold.yaml), [CI](../../.gitlab-ci.yml), [modo Blockchain](../../scripts/k8s/set-blockchain-mode.sh), [motor de adquisición](../../api/evidence-search/app/acquisition.py), [ConfigMap Evidence Search](../../k8s/apis/evidence-search/base/configmap.yaml), [runbook de servidor](skaffold-server.md).

## Lectura de los manifiestos productivos

`apis-frontend-prod` incluye el overlay productivo de Evidence Search y el nuevo Source Router, además de los tres validadores, Gateway, News Handler, Generate Assertions, frontend e ingress. El Deployment `evidence-search` toma la configuración mediante `envFrom`; un cambio de ConfigMap solo llega a procesos nuevos. El pipeline aplica manifiestos y el operador debe **verificar/reiniciar si procede** los pods: no inferir el modo del YAML o de un ConfigMap actualizado con pods antiguos. Evidence Search declara 2 réplicas, `requests` de 250m/256Mi, límite de 1 CPU/1Gi y probes `/health`; `/health` no comprueba Exa, MongoDB ni la calidad de los resultados.

Con SMART, el motor acepta `raw_content` completo de Search (mínimo 120 caracteres, sin página de bloqueo) y solo si no sirve intenta HTTP directo. DIRECT ignora ese texto y descarga la URL. `EVIDENCE_REQUIRE_KNOWN_FRESHNESS=false` admite texto de proveedor cuya fecha de captura es **desconocida**. `EVIDENCE_DOCUMENT_REUSE_MAX_AGE_SECONDS=0` impide reutilizar snapshots documentales. `SEARCH_INCLUDE_RAW_CONTENT=true` solicita texto al proveedor, aunque DIRECT no lo usa como documento. `EVIDENCE_ALLOW_PROVIDER_EXTRACT=false` evita la extracción externa adicional por URL. En métricas, 2xx no implica texto útil: la campaña DIRECT registró 27 respuestas 202 vacías.

Con `BLOCKCHAIN_ENABLED=OFF`, el script crea/actualiza `apis/blockchain-mode` con `false`, reinicia Gateway/News Handler/validadores, comprueba que no haya órdenes BLOCKCHAIN pendientes y escala Geth y `news-chain` a cero. **No** elimina Kafka ni los PVC. El perfil de aplicación todavía construye la imagen `news-chain` y aplica otros componentes, incluido IPFS; `OFF` significa que la ejecución Blockchain está deshabilitada, no que desaparezcan todos sus artefactos. El apagado puede fallar si hay órdenes auditables en curso. En una instalación sin ConfigMap previo, las referencias son opcionales y los procesos Python tienen `false` como valor por defecto, pero se debe confirmar el `false` efectivo tras el pipeline.

### Riesgos que exigen decisión antes de pulsar `deploy`

1. **Migración de MongoDB previa al rollout.** El job `deploy` ejecuta `realign-source-routing-mongodb.sh --apply` y luego `--check`. Si falta el marcador `source-routing-storage-v2`, el script hace `drop()` de `source_routes_v2`, `domain_profiles_v1` y `evidence_search_cache_v2`; además elimina cuatro colecciones antiguas. No borra órdenes, pero sí puede borrar rutas/perfiles/caché y dejar la aplicación anterior sin sus colecciones durante el cambio. Inventariar las colecciones y crear/verificar la copia de MongoDB del paso 3 **antes** de lanzar el job. No asumir que `--check` es un dry-run de `--apply`.
2. **Rollback parcial.** El job `rollback` solo intenta `kubectl rollout undo deployment -n apis`; no revierte la migración MongoDB ni el frontend/ingress/Traefik/Keycloak. Tampoco replica la preparación del túnel SSH de `.kube_access`, por lo que su ejecución correcta no está demostrada. El rollback real debe ser un plan ensayado por componente y por datos; no depender de ese job como garantía.
3. **CI y red.** La CI aún usa `ssh-keyscan` sin una clave de host verificada y `--insecure-skip-tls-verify=true` para K3s (ISSUE-003/004). Resolverlos o aprobar expresamente el riesgo/restricción de una demo privada antes de usar el pipeline. El preflight del certificado TLS de origen no compensa esos dos puntos.
4. **Modo y aceptación documental.** El commit candidato selecciona SMART. Las campañas locales comparten gold y commit declarado, pero cambiaron parámetros observados de generación y no se ejecutaron en Hetzner. La caída observada con DIRECT y los documentos primarios inaccesibles bloquean afirmar mejora o estabilidad de ese modo. Verificar SMART efectivo en destino, repetir con configuración comparable y registrar las incidencias 017/021/026.
5. **Credenciales.** El helper `launch_e2e.sh` contiene una credencial **local**, no de Hetzner, y no forma parte del despliegue productivo. Tratarla por separado; no presentarla como requisito de acceso al servidor.

## Procedimiento paso a paso: actualización de un Hetzner existente

Este flujo presupone K3s, namespaces, los secretos de la instalación anterior, Traefik y `infra-prod` existentes; el nuevo `source-router-enc` se prepara en el paso 2. Una instalación desde cero debe seguir [skaffold-server.md](skaffold-server.md#62-controlled-installation-or-reconstruction) en orden `setup → secretos → traefik-prod → infra-prod → apis-frontend-prod` e incluir `source-router-enc` como indica el paso 2; no iniciar `blockchain-prod` ni `news-chain-prod` para un despliegue LIGHT. El operador necesita acceso protegido a GitLab, SSH/K3s y estado acordado del lock/mTLS de Cloudflare. No guardar secretos, tokens, IP o certificados en este documento ni en artefactos de pruebas.

### 1. Congelar la revisión y revisar el diff

Desde el checkout del operador:

```bash
git fetch origin main postTFM
git fetch gitlab postTFM
git switch postTFM
git status --short
git log -1 --format='%H %ci %s'
git log -1 --format='%H %ci %s' origin/main
git rev-list --left-right --count origin/main...postTFM
git --no-pager diff --stat origin/main postTFM
git --no-pager diff --check origin/main postTFM -- .gitlab-ci.yml skaffold.yaml k8s
```

`--no-pager` imprime la salida completa de `diff --stat` y vuelve al prompt; si ya se abrió el visor que muestra `:` o `:...skipping...`, salir con `q`. La salida mostrada (`da356fd` frente a `3a7f519`, con 3 y 53 commits exclusivos) coincide con la referencia de esta guía. El árbol sigue sucio: hay documentación modificada o sin seguimiento y scripts nuevos. Revisar y registrar esos cambios en un commit antes de publicar el SHA para el despliegue; `git diff --check` solo comprueba espacios y no equivale a un árbol limpio. Si hubo cambios en `main`, integrar y probar su contenido antes de enviar a GitLab; no forzar un push ni fusionar a ciegas. Registrar el SHA final y el estado limpio. Verificar que `gitlab/postTFM` apunta al commit que se pretende desplegar; si no, publicar **ese** commit con `git push gitlab postTFM` tras revisión. No usar `git push origin postTFM` por inercia: `origin` tiene dos destinos de push configurados.

### 2. Comprobaciones locales sin tocar Hetzner

```bash
kubectl kustomize k8s/apis/evidence-search/overlays/prod
kubectl kustomize k8s/apis/validate-asertions/overlays/prod/worker-1 --load-restrictor=LoadRestrictionsNone
kubectl kustomize k8s/ingress/overlays/prod-domain
node tests/frontend/e2e/run-regression.js --validate
```

Inspeccionar en la salida renderizada `EVIDENCE_EXTRACTION_MODE: SMART`, `EVIDENCE_ALLOW_PROVIDER_EXTRACT: "false"`, dos réplicas de Evidence Search, referencia a `blockchain-mode` y ruta `/gui`. Un árbol sucio no sirve como revisión de release. Los manifiestos de validadores requieren `--load-restrictor=LoadRestrictionsNone` por sus referencias fuera del overlay. Ejecutar `tests/run-local-regression.sh` y las suites de evaluación pertinentes; guardar el resultado del SHA exacto. La validación estática no sustituye un E2E.

#### Preparar secretos y accesos a APIs del candidato

Comparar estos requisitos con los Secrets **reales** de `apis` antes de lanzar `deploy`. El overlay productivo no genera los Secrets desde Git; un ConfigMap correcto no proporciona las credenciales. Usar ficheros privados fuera del repositorio y el procedimiento idempotente de [secretos productivos](skaffold-server.md#3-secrets-productivos). Los nombres y claves siguientes corresponden a los manifiestos de este candidato:

| Consumidor | Secret en `apis` | Claves necesarias con la configuración productiva | Cambio respecto a `origin/main` |
| --- | --- | --- | --- |
| Source Router | `source-router-enc` | `OPENROUTER_API_KEY` y `EXA_API_KEY` **o** `API_KEY_PROVIDER` con una credencial Exa | Secret nuevo: el Deployment no arranca si falta. Usa OpenRouter para clasificar y Exa para descubrir fuentes en MISS/STALE. |
| Generate Assertions | `api-keys` | `OPENROUTER_API_KEY` | El Secret ya existía, pero el overlay productivo cambia `AI_PROVIDER` de Gemini a OpenRouter (`openai/gpt-5-nano`). Comprobar que la clave de OpenRouter está presente y habilitada para ese modelo. |
| Evidence Search | `search-secret` | `EXA_API_KEY` **o** `API_KEY_PROVIDER` con una credencial Exa | El Secret ya existía y `SEARCH_PROVIDER=exa` sigue siendo el valor productivo. La clave específica `EXA_API_KEY` tiene prioridad sobre la genérica. |
| Source Router y Evidence Search | `mongodb-app-secret` | Credenciales de la base de aplicación ya documentadas en el runbook | Se reutiliza el Secret existente; no se crea otra cuenta MongoDB para Source Router. |

`TAVILY_API_KEY` solo hace falta si se cambia explícitamente `SEARCH_PROVIDER` a `tavily` en el consumidor correspondiente; también admite `API_KEY_PROVIDER` si contiene una credencial Tavily. Los proveedores adicionales de LLM y sus claves no son requisitos de este perfil. `EVIDENCE_ALLOW_PROVIDER_EXTRACT=false` evita llamadas adicionales de extracción por URL, pero SMART sí puede usar el texto devuelto por la búsqueda Exa. Confirmar en las cuentas de Exa y OpenRouter permisos, modelo disponible, cuota y presupuesto suficientes para Source Router, Generate Assertions y las dos réplicas de Evidence Search; no se añade una API pública, un Ingress ni un puerto nuevo para Source Router.

Preparar en un directorio privado del operador un fichero para cada Secret que haya que crear o actualizar. Por ejemplo, `source-router.env` debe contener la clave de OpenRouter y una clave Exa según el primer renglón de la tabla; `generate-asertions.env` y `search.env` deben contener las claves de sus respectivos renglones **además de cualquier clave existente que se quiera conservar**. Antes de actualizar un Secret existente, inventariar sus claves y preparar un fichero completo para evitar perder configuración anterior. Usar valores reales, nunca `replace-me`. Después, con el kubeconfig de producción y `PRIVATE_SECRETS_DIR` apuntando al directorio privado:

```bash
kubectl create secret generic source-router-enc -n apis \
  --from-env-file="$PRIVATE_SECRETS_DIR/source-router.env" \
  --dry-run=client -o yaml | kubectl apply -f -

# Solo si faltan las claves requeridas o hay que rotarlas:
kubectl create secret generic api-keys -n apis \
  --from-env-file="$PRIVATE_SECRETS_DIR/generate-asertions.env" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic search-secret -n apis \
  --from-env-file="$PRIVATE_SECRETS_DIR/search.env" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Establecer `PRIVATE_SECRETS_DIR` con la ruta privada del operador antes de ejecutar esos comandos; proteger los ficheros y no subirlos a Git ni a artefactos de CI. Verificar presencia de Secrets y nombres de claves sin imprimir valores:

```bash
kubectl describe secret source-router-enc api-keys search-secret mongodb-app-secret -n apis
```

Revisar también que las claves no estén vacías ni sean valores de ejemplo. El runbook común [k8s-common.md](k8s-common.md#9-source-router-and-evidence-search) todavía llama al Secret del router `source-router-llm-secret`; para **este** Deployment el nombre efectivo es `source-router-enc`. El script de [reconciliación Keycloak](../../scripts/k8s/infra/reconcile-keycloak-web-prod.sh) añade el client scope `trustnews-gateway-audience` y el mapper que emite `aud=TrustNewsGateway` para `TrustNewsWeb` y `TrustNewsApi` al final del pipeline. Es configuración de OIDC, no una nueva API key ni un client secret. Antes del cambio comprobar que ambos clientes existen en el realm `TrustNews`; después, obtener tokens nuevos y verificar audiencia, cliente y rutas protegidas en el paso 6. Si la reconciliación falla, no abrir el tráfico.

### 3. Preparar la ventana de cambio y la recuperación

- Activar el **maintenance lock** de Cloudflare antes de detener escrituras o apagar el nodo; confirmar la regla mTLS temporal y registrar el estado deseado para la ventana. No quitar el mTLS general de v0.0.13. Confirmar acceso a Hetzner Console y un medio de recuperación independiente de SSH antes de iniciar la ventana.
- Inspeccionar pods, PVC, capacidad, secretos de búsqueda/MongoDB, cuota del proveedor y estado de Kafka/Keycloak. Confirmar que la revisión anterior y sus imágenes siguen disponibles.
- Inventariar las colecciones que tocará `realign-source-routing-mongodb.sh`. Crear y verificar el backup de la base de aplicación MongoDB con el procedimiento siguiente. Si falla la copia o no puede guardarse fuera del servidor, **no ejecutar el job**; un rollback de Deployments no restaurará los datos.
- Si Blockchain estaba `ON`, no asumir que puede apagarse inmediatamente. Comprobar órdenes auditables pendientes y esperar a que terminen; el pipeline abortará si las hay. No forzar escalado manual de Geth.
- Decidir y registrar el tratamiento de ISSUE-003/004. Si no existe aceptación o corrección, el despliegue de producción no tiene puerta de seguridad cerrada.

Con un kubeconfig operativo hacia K3s (o el túnel SSH de [quick_start_hetzner.md](../quick_start_hetzner.md#3-acceso-ssh-y-kubernetes)), las lecturas mínimas son:

```bash
kubectl get nodes
kubectl get pods -A
kubectl get pvc -A
kubectl get pv -o wide
kubectl get cm blockchain-mode -n apis --ignore-not-found
kubectl get deploy evidence-search source-router news-handler gateway -n apis --ignore-not-found
kubectl get statefulset -n blockchain
```

#### Copia de MongoDB antes del deploy

Ejecutar desde un equipo de operador con `kubectl` y espacio suficiente **fuera del CX33**. El script lee `MONGO_APP_DATABASE` del pod `infra/mongodb`, usa las credenciales que ya tiene el contenedor, exporta esa base con `mongodump --archive` y comprime el flujo en el equipo del operador. No vuelca `admin`, `config` ni `local`; los Secrets y usuarios de la instalación deben conservarse por separado. La salida contiene datos potencialmente sensibles: guardar con permisos restringidos y cifrarla si se transporta o almacena en otro servicio. Mantener el maintenance lock y detener/esperar a los productores que escriben en MongoDB para obtener un corte lógico coherente; si se pausa un componente, registrar sus réplicas originales. El script no detiene escrituras por sí mismo.

```bash
mkdir -p -m 700 "$HOME/mongodb-release-backups"
backup_file="$HOME/mongodb-release-backups/pre-v0.0.13-$(date -u +%Y%m%dT%H%M%SZ).archive.gz"
scripts/k8s/backup-mongodb.sh --namespace infra --output "$backup_file"
scripts/k8s/restore-mongodb.sh --namespace infra --input "$backup_file"
```

El último comando **solo valida** gzip, SHA-256, nombre de base y destino; no cambia datos. Conservar juntos `*.archive.gz`, `*.manifest` y `*.sha256`, registrar ruta, hash, hora UTC, SHA de Git y almacenamiento externo. Comprobar que el backup terminó antes de apagar el servidor. Una prueba de restauración aislada es la verificación más fuerte; el chequeo de integridad no demuestra que toda la aplicación pueda arrancar. Verificar la clase de almacenamiento del PVC MongoDB: los snapshots del servidor no incluyen Cloud Volumes adjuntos.

Para restaurar, mantener el lock, detener las escrituras y escoger un MongoDB de destino con la misma `MONGO_APP_DATABASE`. Probar primero en un entorno aislado y revisar el nombre de base/objetivo mostrado por el comando sin `--apply`. La operación real **borra la base de aplicación completa**, restaura las colecciones e índices del archivo y recrea el usuario de aplicación con los Secrets del pod de destino. Pierde todas las escrituras posteriores al backup; no fusiona datos. No ejecutarla sobre una aplicación de versión incompatible ni sin decisión explícita de recuperación:

```bash
scripts/k8s/restore-mongodb.sh --namespace infra --input "$backup_file"
scripts/k8s/restore-mongodb.sh --namespace infra --input "$backup_file" --apply --replace-database
```

No usar `init-mongodb-server.sh` como paso de restore: incluye la realineación de colecciones y podría volver a modificarlas. Si el restore se interrumpe después del borrado, mantener la aplicación bloqueada y repetir con un archivo verificado o recuperar el destino aislado.

#### Apagar, tomar snapshot y arrancar el CX33

Después del backup MongoDB, mantener el lock activo y confirmar que no hay órdenes en curso ni escrituras pendientes. Conservar el acceso a Hetzner Console; el SSH se interrumpirá al apagar. Desde una sesión SSH autenticada con clave, solicitar un apagado limpio del sistema invitado:

```bash
ssh -i "$HETZNER_KEY" -p 2222 "$HETZNER_USER@$HETZNER_HOST"
sudo systemctl poweroff
```

Las dos líneas representan pasos consecutivos: la segunda se ejecuta **dentro** de la sesión del CX33. Esperar en Hetzner Console a que el servidor figure como **Off**; no tomar el snapshot mientras se está apagando. En el proyecto correcto, abrir **Snapshots → Take Snapshot**, seleccionar el CX33 y describirlo con fecha UTC, SHA de Git y propósito `pre-v0.0.13`. Esperar a que la creación termine y la imagen esté disponible. Registrar su identificador fuera del repositorio y activar la protección contra borrado si se usa en este proyecto. Solo entonces volver a encender el **mismo servidor** desde Console y esperar a que SSH y K3s estén disponibles. Hetzner [recomienda apagar el servidor para garantizar la consistencia de la imagen](https://docs.hetzner.com/cloud/servers/backups-snapshots/faq/); el snapshot cubre el disco del servidor, **no** los Cloud Volumes adjuntos. El backup lógico de MongoDB sigue siendo necesario para recuperar esa base sin reconstruir el disco completo.

Comprobar la identidad SSH contra la huella previamente confiada; una clave de host inesperada exige investigar antes de continuar. No aceptar automáticamente una huella nueva. Abrir **una nueva sesión SSH con clave** y ejecutar `kubectl get nodes`, `kubectl get pods -A` y `kubectl get pvc -A`; el nodo debe estar `Ready` y los volúmenes y servicios críticos recuperados. Mantener el lock durante la actualización del host.

#### Actualizar paquetes del sistema y comprobar el endurecimiento

En la sesión SSH, identificar primero la distribución y espacio libre. **Si el CX33 usa Debian o Ubuntu**, actualizar paquetes con `apt`; revisar la simulación antes de aplicarla y atender los cambios de archivos de configuración, especialmente SSH y red. No hacer aquí un salto de versión de distribución ni actualizar K3s por separado: requieren otro plan y validación. Para otra distribución, usar su gestor equivalente y registrar los paquetes modificados.

```bash
cat /etc/os-release
df -h /
free -h
swapon --show
sudo apt-get update
sudo apt-get -s upgrade
sudo apt-get upgrade
apt list --upgradable
sudo sshd -t
sudo sshd -T | awk '$1=="port" || $1=="pubkeyauthentication" || $1=="passwordauthentication" || $1=="kbdinteractiveauthentication" || $1=="permitrootlogin" {print}'
```

El mensaje de bienvenida de Ubuntu puede mostrar actualizaciones pendientes y `System restart required`: son señales de mantenimiento, **no** pruebas de que SSH o el firewall estén bien configurados. Si aparece una actualización de seguridad adicional con **ESM Apps** desactivado, identificar el paquete con `pro security-status --esm-apps` y registrar cómo se resolverá esa actualización antes de dar por cerrado el control de seguridad. `apt-get upgrade` sin ese servicio no instala el parche ESM; la activación de Ubuntu Pro o una alternativa para ese paquete requiere una decisión separada. [Ubuntu explica el aviso de ESM del MOTD](https://documentation.ubuntu.com/pro-client/en/latest/explanations/motd_messages/) y [el comando para identificar paquetes afectados](https://ubuntu.com/pro/tutorial).

Comprobar el resultado efectivo esperado: **`port 2222`, `pubkeyauthentication yes`, `passwordauthentication no`, `kbdinteractiveauthentication no` y `permitrootlogin no`**. Si existen reglas `Match` en `sshd_config`, repetir `sshd -T -C` con usuario, host y dirección de origen reales: la salida global puede no representar la política de esa conexión. Conservar la sesión abierta mientras se prueba **otra conexión** con la clave autorizada desde el equipo del operador. Probar también sin clave desde otra terminal: debe rechazarse sin ofrecer login por contraseña o teclado interactivo; si aparece un prompt de contraseña, cancelarlo y detener el despliegue. Una sesión existente o `sshd -t` correcto no prueban por sí solos que el acceso nuevo siga funcionando. [Ubuntu documenta el orden efectivo de `sshd_config` y la comprobación previa al reinicio](https://ubuntu.com/server/docs/how-to/security/openssh-server/).

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -i "$HETZNER_KEY" -p 2222 "$HETZNER_USER@$HETZNER_HOST" 'id -un'
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive -o NumberOfPasswordPrompts=1 -p 2222 "$HETZNER_USER@$HETZNER_HOST" true
```

La segunda prueba debe terminar con autenticación denegada; **no introducir una contraseña** si se solicita. Revisar si `apt list --upgradable` deja paquetes pendientes y resolverlos o documentar la razón antes de continuar. Revisar además en Hetzner Console el firewall del CX33: `2222/tcp` solo desde los orígenes administrativos/runner autorizados, `443/tcp` solo desde rangos Cloudflare verificados y `22/tcp`, `80/tcp`, `6443/tcp` y puertos internos cerrados desde Internet. En el host, revisar `sudo ss -lntp` y las reglas del firewall que realmente use (`ufw`/`nftables`); una lista de sockets no sustituye la prueba desde una red externa. Confirmar que la API K3s solo se alcanza por el túnel SSH del [quick start](../quick_start_hetzner.md#3-acceso-ssh-y-kubernetes) y que Cloudflare conserva lock y mTLS.

Si `/run/reboot-required` existe, ejecutar `sudo systemctl reboot` durante esta ventana, esperar el regreso del CX33 y repetir **todas** las comprobaciones de SSH, firewall, nodo, pods y PVC antes de seguir. Registrar versión del sistema, kernel, paquetes actualizados, snapshot y resultados, sin credenciales ni huellas en Git. **No iniciar el pipeline de despliegue** si no se recuperó K3s, se alteró el acceso por clave, se habilitó login sin clave, cambió la exposición de puertos o el snapshot no está disponible. Resolver el problema con el lock activo y el acceso de Console; una reversión completa al snapshot sobrescribe los cambios del disco posteriores a su captura.

### 4. Construir y desplegar desde GitLab

En GitLab, `Build > Pipelines > Run pipeline`, rama `postTFM`, variables explícitas:

```dotenv
PROFILE=apis-frontend-prod
BLOCKCHAIN_ENABLED=OFF
```

Ejecutar/esperar `build` y comprobar que su `build.json` pertenece al SHA elegido; el job `deploy` exige ese archivo aunque `needs: build` sea opcional. Esperar a que pase el preflight TLS. **Antes de lanzar `deploy`, confirmar el punto 3 completo: backup MongoDB, apagado y snapshot disponible, actualización del host y verificaciones de seguridad/K3s**. En el job, la realineación MongoDB y el gate de Blockchain ocurren *antes* de `skaffold deploy`. Luego Skaffold aplica las imágenes, `set-blockchain-mode.sh` fija OFF y escala Geth/`news-chain` a cero, se comprueban rollouts, `/gui` y la reconciliación Keycloak. No sustituir este proceso por parches `kubectl apply` o `helm upgrade` manuales.

Si el salto incluye la migración inicial de Traefik a `/gui` y aún no está aplicada en el destino, seguir la secuencia controlada del runbook con lock habilitado: pipeline separado `PROFILE=traefik-prod`, validación, y **después** el de `apis-frontend-prod`. Si Traefik `/gui` ya existe y no cambió, no redeployar `traefik-prod` innecesariamente. Para una instalación nueva, ejecutar antes los perfiles de infraestructura según el runbook, cada uno en pipeline separado.

### 5. Verificar el estado efectivo, no solo los manifiestos

Con el mismo acceso K3s, tras el pipeline:

```bash
kubectl rollout status deployment/evidence-search -n apis --timeout=180s
kubectl rollout status deployment/source-router -n apis --timeout=180s
kubectl rollout status deployment/news-handler -n apis --timeout=180s
kubectl rollout status deployment/gateway -n apis --timeout=180s
kubectl rollout status deployment/frontend-web -n frontend --timeout=180s
kubectl get cm evidence-search-config -n apis -o jsonpath='{.data.EVIDENCE_EXTRACTION_MODE}{"\n"}'
kubectl get cm blockchain-mode -n apis -o jsonpath='{.data.BLOCKCHAIN_ENABLED}{"\n"}'
kubectl get deployment evidence-search -n apis -o jsonpath='{.status.readyReplicas}{"/"}{.spec.replicas}{"\n"}'
kubectl get deployment news-chain -n apis --ignore-not-found
kubectl get statefulset -n blockchain
```

La salida esperada para esta release es SMART, `false`, `2/2` Evidence Search y cero réplicas deseadas de `news-chain` y de los StatefulSets Geth que existan. Comprobar **cada pod** de Evidence Search, porque `envFrom` se lee al arrancar:

```bash
for pod in $(kubectl get pod -n apis -l app=evidence-search -o name); do
  printf '%s: ' "$pod"
  kubectl exec -n apis "$pod" -- printenv EVIDENCE_EXTRACTION_MODE
done
kubectl get ingress frontend-ingress -n frontend
kubectl get middleware frontend-strip-gui -n frontend
```

Si SHA, ConfigMap y pod discrepan, detener la aceptación y diagnosticar el rollout; no dar por activado el modo elegido. Reanudar cualquier productor pausado para la copia de MongoDB con sus réplicas originales y verificarlo antes de la prueba funcional. Revisar errores de los deployments y las métricas de Search/HTTP, fuentes citables, latencia y coste. `/health` verde no acredita recuperación documental ni veredictos correctos.

### 6. Validar por el borde real y tomar la decisión

Con el lock en el estado acordado y un certificado temporal autorizado, comprobar `https://assermetry.com/gui/`, recursos, login/logout, issuer OIDC canónico, Gateway con/sin JWT, ausencia de Swagger/OpenAPI público y aislamiento de rutas administrativas. Ejecutar una orden LIGHT desde la GUI; comprobar que BLOCKCHAIN no se ofrece o se rechaza para nuevas órdenes, y que la respuesta final tiene fuentes/citas trazables. Verificar también desde otra red. El acceso directo por `port-forward` solo ayuda al diagnóstico: no prueba Cloudflare, Traefik ni mTLS.

Ejecutar una campaña publicada LIGHT sobre el corpus oficial con credenciales de prueba, cuota y ventana autorizadas, siguiendo [evaluation.md](../tests/evaluation.md); `--publish` consume proveedores. El runner documentado no implementa por sí mismo un certificado cliente mTLS, por lo que **no** usar `--no-verify-tls` como atajo de producción ni afirmar que una ejecución por túnel equivale a prueba del borde. Preparar un acceso de prueba que preserve TLS/mTLS o completar esa capacidad del runner antes de acreditar el E2E por el borde. Guardar SHA, imagen, hashes de casos, configuración de validadores, informe y errores sin secretos.

Para afirmar que un modo supera al otro, ejecutar campañas frías y emparejadas en una revisión/configuración comparable, una por modo, y usar `evaluation.pipeline.compare_modes` según [el plan del motor](../architecture/evidence-retrieval-engine-plan.md#2026-10-28--subfase-4a-comparador-de-campañas). Fijar modelo, temperatura, versión de configuración y gold; comparar cobertura de fuentes citables, exactitud, rechazos/abstenciones, `freshness_status`, p50/p95, llamadas y coste. Las campañas locales del 31-10 y 01-11 son evidencia de una regresión observada, no una comparación causal cerrada. Con el ConfigMap actual `provider_extract` seguirá a cero; evaluarlo requiere un cambio versionado separado.

**GO para despliegue controlado:** SHA limpio y artefactos correctos, backup MongoDB externo íntegro, snapshot del CX33 apagado disponible, actualización del host validada, acceso SSH solo por clave, firewall/K3s comprobados, migración aceptada con recuperación, CI autorizada, rollouts verdes, SMART y OFF observados en todos los pods pertinentes, borde y LIGHT funcionales. **NO GO para sacar v0.0.13 de Deploying o publicarla:** P1 sin resolver o sin aplazamiento formal, corpus no homologado, veredictos/fuentes no aceptables o pruebas requeridas en [version.md](../version.md) no acreditadas.

### 7. Fallo y reversión

Si falla antes de `skaffold deploy`, conservar el estado y diagnosticar la realineación/gate; no relanzar a ciegas. Si falla después, identificar qué cambió (MongoDB, imágenes, modo, frontend, ingress, Keycloak) antes de revertir. El job `rollback` no basta para restaurar todo el cambio y debe verificarse su acceso al clúster. Cualquier cambio entre SMART y DIRECT o de imágenes debe hacerse con un commit/configuración versionados y el pipeline protegido, salvo recuperación excepcional autorizada; **no** recuperar colecciones antiguas sobre una aplicación nueva sin comprobar compatibilidad. Mantener el lock si el borde queda inconsistente y registrar el estado final de mTLS/Cloudflare.

Volver al tag/commit anterior y restaurar **solo** MongoDB permite recuperar código, manifiestos y esa base si también existen imágenes reconstruibles, Secrets y configuración compatibles. **No reconstruye por sí solo todo el sistema**: Keycloak usa otra base PostgreSQL con PVC, Kafka/IPFS y otros componentes tienen estado propio; certificados, credenciales, reglas Cloudflare, configuración externa y contenido de otros PVC tampoco están en Git ni en este archivo. Para reconstrucción completa hacen falta inventario y copias de esos estados, versiones de imágenes fijadas y un restore ensayado en un clúster aislado. Para un rollback de esta release, conservar el mismo corte temporal entre código y datos y validar los contratos entre servicios antes de abrir el tráfico.

Solo después de validar Hetzner y cumplir la puerta de salida de Deploying en [version.md](../version.md): actualizar la evidencia de [issues.md](../issues.md), reconciliar `postTFM` con los commits exclusivos de `origin/main`, promover mediante PR/MR a `main` en ambos remotos y crear la etiqueta conforme a [gitlab-github-release-workflow.md](gitlab-github-release-workflow.md#6-release). El alcance documental está cerrado, pero no se etiqueta un commit de trabajo por el mero hecho de terminar el pipeline.
