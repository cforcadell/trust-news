# v0.0.13: despliegue LIGHT en Hetzner desde `postTFM`

**Revisión documental: 2026-11-02. Estado de v0.0.13: Deploying; el operador comunicó el despliegue en Hetzner y aportó comprobaciones correctas de pods, rollouts, SMART y Blockchain OFF. La validación funcional por el borde y la aceptación siguen abiertas.** El alcance incorporado y lo pendiente están en [detalle de v0.0.13](../releases/v0.0.13.md) e [issues.md](../issues.md). La comparación inicial de esta guía usó `postTFM` (`20b8bb2`) y la referencia local `origin/main` (`3a7f519`); el candidato posterior es `ad40321369bfd901022df19995369d719c65ba3a`. Antes de promover hay que hacer `git fetch` y repetir la comparación. La rama local `main` apuntaba a `736cf67` (2025-07-05) y no sirve de base actual. En la comparación inicial, las referencias divergían (3 commits solo en `origin/main`, 54 solo en `postTFM`): la promoción requiere reconciliación, pruebas y revisión.

**Modo previsto de Evidence Search: SMART.** El commit `20b8bb2` y el ConfigMap actual seleccionan SMART; el overlay productivo hereda ese valor. Las campañas locales [SMART](../../tests/data/evaluation/artifacts/e2e-20261031-181209/report.md) y [DIRECT](../../tests/data/evaluation/artifacts/e2e-20261101-101658/report.md) son diagnósticas; DIRECT obtuvo 12/22 unidades e2e estrictas y tres fallos de ejecución frente a 19/22 y cero fallos técnicos en SMART. Cambió también la configuración observada de generación. Ninguna campaña acredita por sí sola aceptación en Hetzner. Un cambio futuro a DIRECT requiere otra revisión versionada y validación.

Los comandos de esta guía son instrucciones para el operador, no una constancia de ejecución. El repositorio editable está en la VM con Kind; Hetzner no recibe un archivo por el mero hecho de modificarlo allí. Los scripts de copia/restauración y la transición versionada a Blockchain `OFF` solo existen en Hetzner después de una sincronización explícita o de la copia realizada por la CI desde un commit publicado.

## Resultado ejecutivo

| Objetivo | Estado en `postTFM` | Consecuencia |
| --- | --- | --- |
| Blockchain desactivada por defecto | `.gitlab-ci.yml` fija `BLOCKCHAIN_ENABLED=OFF`; `set-blockchain-mode.sh` también usa `OFF` si falta la variable. Los StatefulSets de Geth y el Deployment `news-chain` declaran cero réplicas. | Para desplegar LIGHT, usar explícitamente `PROFILE=apis-frontend-prod`, `BLOCKCHAIN_ENABLED=OFF`. Comprobar el ConfigMap y los pods después; no basta el valor de CI. |
| Modo de Evidence Search | El commit y el checkout actual fijan SMART. El overlay productivo incluye la base sin sobrescribirla; el Deployment declara dos réplicas. | Verificar SMART en el SHA, ConfigMap y ambos pods; un cambio de modo requiere nueva revisión y prueba. |
| Adquisición documental | `EVIDENCE_ALLOW_PROVIDER_EXTRACT: "false"`. SMART usa `raw_content` completo de Search si es válido y luego HTTP directo; DIRECT usa HTTP directo. | Ninguno añade el fallback `provider_extract` tras un 403 con esta configuración. Habilitarlo requeriría cambio versionado, medición de coste y aceptación. |
| Estado de v0.0.13 | Alcance de desarrollo documentado; release Deploying. | Desplegar para validar no equivale a publicarla ni etiquetarla. Persisten incidencias P1 y pruebas de aceptación. |

## Alcance real del diff

Comparación de contenido `git diff origin/main postTFM`: **328 archivos cambiados**, unas 38 658 líneas añadidas y 48 090 retiradas. Es un salto funcional y de configuración, no una mera conmutación de dos flags. Para revisar lo que aporta *solo* la rama desde la base común, usar `git diff origin/main...postTFM`; para saber qué recibirá `main` al fusionar, revisar también `git diff origin/main postTFM` y los 3 commits exclusivos de `main`.

| Área | Cambios relevantes para el despliegue y la aceptación |
| --- | --- |
| Flujo de órdenes | Separación LIGHT/BLOCKCHAIN, propagación del modo por Gateway, News Handler y validadores; gate de órdenes auditables nuevas al apagar Blockchain. Kafka y los servicios LIGHT permanecen activos. |
| Extracción/LLM | Proveedor estructurado compartido, cambios de esquema/prompt y metadatos de aserción; el overlay productivo de Generate Assertions pasa de Gemini a OpenRouter `openai/gpt-5-nano`. Revalidar calidad y latencia; una prueba aislada del modelo no representa la ruta GUI completa. |
| Búsqueda y evidencia | Nuevo Source Router dinámico y taxonomía; proveedores de búsqueda desacoplados; Evidence Search incorpora motor `DIRECT`/`PROVIDER`/`SMART`, descarga HTML/PDF, trazas de adquisición, snapshots, historial negativo, cachés y presupuesto de reintentos. Se sustituyen colecciones antiguas de rutas/caché. |
| Validación y consenso | Contrato de citas `context_id`, abstención/errores explícitos, scoring, timeouts/reintentos acotados y captura diagnóstica. Los validadores LIGHT dependen de Kafka, Router y Evidence Search; con `OFF` no esperan a Geth. |
| API/seguridad/GUI | JWT con audiencia y cliente, aislamiento de órdenes/validaciones, rutas administrativas; frontend bajo `/gui` con middleware StripPrefix y coincidencia estricta de prefijos Traefik; cambios de estados, fechas, evidencia, idiomas y vista de costes. La migración a `/gui` implica validar Traefik, ingress, redirecciones y Keycloak juntos. |
| Infraestructura | Perfil productivo incorpora Source Router, recursos/probes y dos réplicas de Evidence Search; pipeline añade preflight de TLS, realineación MongoDB antes del rollout, cambio de modo Blockchain y comprobaciones de `/gui`. Persisten riesgos de autenticación SSH/K3s del CI. |
| Pruebas/artefactos | Nuevas suites API, frontend, E2E, evaluación, viewer y comparador DIRECT/SMART. La presencia de un test o un artefacto no acredita que el commit actual haya pasado contra Hetzner. |

Archivos de referencia: [Skaffold](../../skaffold.yaml), [CI](../../.gitlab-ci.yml), [modo Blockchain](../../scripts/k8s/set-blockchain-mode.sh), [sincronización de scripts operativos](../../scripts/ci/sync-remote-files.sh), [motor de adquisición](../../api/evidence-search/app/acquisition.py), [ConfigMap Evidence Search](../../k8s/apis/evidence-search/base/configmap.yaml), [runbook de servidor](skaffold-server.md).

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

### Entornos de ejecución

| Etiqueta | Ubicación y contenido | Qué se ejecuta allí |
| --- | --- | --- |
| **VM-KIND** | VM de desarrollo con el checkout `/home/adminu/blockchain/tfm`. Aquí están los cambios sin publicar y el clúster Kind local. | Git, revisión del diff, pruebas locales y `sync-remote-files.sh`. Un `kubectl` sin cambiar de contexto puede apuntar a Kind; comprobarlo antes de tocar producción. |
| **HETZNER** | Host `trust-news-prod`. El directorio operativo es `/home/sysadmin/trust-news/scripts/k8s`; no es un checkout completo ni se actualiza al guardar archivos en VM-KIND. | Mantenimiento del host y, después de copiar los scripts, operaciones contra el K3s local de producción. |
| **GITLAB-RUNNER** | Checkout efímero del commit de la pipeline dentro del contenedor del job. | Build, Skaffold, migraciones y cambio de modo mediante el túnel SSH a K3s. Al terminar el job ese checkout no constituye una instalación persistente en Hetzner. |

Los bloques siguientes indican su entorno. Antes de cualquier `kubectl` en **VM-KIND**, comprobar `kubectl config current-context`; no usar el contexto Kind para interpretar el estado de Hetzner. En **HETZNER**, `kubectl` usa el K3s del host. La CI usa su propio kubeconfig y túnel.

### 1. Congelar la revisión y revisar el diff

**[VM-KIND]** Desde `/home/adminu/blockchain/tfm`:

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

`--no-pager` imprime la salida completa de `diff --stat` y vuelve al prompt; si ya se abrió el visor que muestra `:` o `:...skipping...`, salir con `q`. La última comparación observada (`20b8bb2` frente a `3a7f519`, con 3 y 54 commits exclusivos) terminó sin errores y con el árbol limpio. Después de cualquier edición de esta guía, revisar y registrar los cambios antes de publicar el SHA de despliegue; `git diff --check` solo comprueba espacios y no equivale a un árbol limpio. Si hubo cambios en `main`, integrar y probar su contenido antes de enviar a GitLab; no forzar un push ni fusionar a ciegas. Registrar el SHA final y el estado limpio. Verificar que `gitlab/postTFM` apunta al commit que se pretende desplegar; si no, publicar **ese** commit con `git push gitlab postTFM` tras revisión. No usar `git push origin postTFM` por inercia: `origin` tiene dos destinos de push configurados.

### 2. Validar el candidato local y preparar secretos productivos

**[VM-KIND, contexto local Kind]** Estas comprobaciones solo renderizan o validan contenido del checkout:

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

Preparar en un directorio privado del operador un fichero para cada Secret que haya que crear o actualizar. Por ejemplo, `source-router.env` debe contener la clave de OpenRouter y una clave Exa según el primer renglón de la tabla; `generate-asertions.env` y `search.env` deben contener las claves de sus respectivos renglones **además de cualquier clave existente que se quiera conservar**. Antes de actualizar un Secret existente, inventariar sus claves y preparar un fichero completo para evitar perder configuración anterior. Usar valores reales, nunca `replace-me`.

**[VM-KIND con túnel y kubeconfig de producción]** Estos comandos sí modifican Hetzner. Confirmar primero que el contexto resuelve el API de producción, no Kind, y que `PRIVATE_SECRETS_DIR` apunta al directorio privado:

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
- Si Blockchain estaba `ON`, no asumir que puede apagarse inmediatamente. Comprobar órdenes auditables pendientes y esperar a que terminen; el pipeline abortará si las hay. La única excepción de escalado previo es la acción controlada `--stop-chain-runtime` documentada más abajo.
- Decidir y registrar el tratamiento de ISSUE-003/004. Si no existe aceptación o corrección, el despliegue de producción no tiene puerta de seguridad cerrada.

**[HETZNER]** En la sesión SSH del host, las lecturas mínimas contra su K3s son:

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

El backup que protege frente a la pérdida del servidor se crea desde **VM-KIND**, con un túnel/kubeconfig de producción y espacio suficiente fuera del CX33. El script lee `MONGO_APP_DATABASE` del pod `infra/mongodb`, usa las credenciales que ya tiene el contenedor, exporta esa base con `mongodump --archive` y comprime el flujo en VM-KIND. No vuelca `admin`, `config` ni `local`; los Secrets y usuarios de la instalación deben conservarse por separado. La salida contiene datos potencialmente sensibles: guardar con permisos restringidos y cifrarla si se transporta o almacena en otro servicio. Mantener el maintenance lock y detener/esperar a los productores que escriben en MongoDB para obtener un corte lógico coherente; si se pausa un componente, registrar sus réplicas originales. El script no detiene escrituras por sí mismo.

#### Sincronizar los scripts con Hetzner

**[VM-KIND]** Sincronizar primero las tres herramientas versionadas con el directorio operativo de Hetzner. El motor instala archivos regulares mediante un staging remoto, los publica con modo `0750` y compara su SHA-256 con el checkout. Esto reemplaza las copias creadas manualmente y falla si el contenido remoto no coincide:

`HETZNER_HOST`, `HETZNER_USER` y `HETZNER_KEY` deben estar definidos en VM-KIND; `HETZNER_KEY` es la ruta a la clave privada. La confianza SSH guardada en otro equipo no se comparte con esta VM: antes de sincronizar, comprobar que `~/.ssh/known_hosts` de VM-KIND contiene la clave del puerto 2222 previamente verificada. El motor usa `StrictHostKeyChecking=yes` y aborta si no existe o cambia.

```bash
cd /home/adminu/blockchain/tfm
scripts/ci/sync-remote-files.sh \
  --host "$HETZNER_HOST" \
  --user "$HETZNER_USER" \
  --port 2222 \
  --identity "$HETZNER_KEY" \
  --target-dir /home/sysadmin/trust-news/scripts/k8s \
  --mode 0750 \
  -- scripts/k8s/backup-mongodb.sh \
     scripts/k8s/restore-mongodb.sh \
     scripts/k8s/set-blockchain-mode.sh

ssh -i "$HETZNER_KEY" -p 2222 "$HETZNER_USER@$HETZNER_HOST" \
  'test -x /home/sysadmin/trust-news/scripts/k8s/backup-mongodb.sh &&
   test -x /home/sysadmin/trust-news/scripts/k8s/restore-mongodb.sh &&
   test -x /home/sysadmin/trust-news/scripts/k8s/set-blockchain-mode.sh'
```

El job `deploy` repite esta sincronización desde su checkout efímero antes de modificar MongoDB o Kubernetes usando `OPERATIONS_SCRIPTS_DIR=/home/sysadmin/trust-news/scripts/k8s`. La sincronización manual anterior sigue siendo necesaria para disponer de `set-blockchain-mode.sh` en Hetzner antes del pipeline. Instalar `backup-mongodb.sh` en el CX33 no convierte en externa una copia creada allí: el backup de este procedimiento se ejecuta desde VM-KIND y se conserva fuera del servidor.

**[VM-KIND con contexto de producción]** Crear y validar el backup fuera de Hetzner:

```bash
mkdir -p -m 700 "$HOME/mongodb-release-backups"
backup_file="$HOME/mongodb-release-backups/pre-v0.0.13-$(date -u +%Y%m%dT%H%M%SZ).archive.gz"
scripts/k8s/backup-mongodb.sh --namespace infra --output "$backup_file"
scripts/k8s/restore-mongodb.sh --namespace infra --input "$backup_file"
```

El último comando **solo valida** gzip, SHA-256, nombre de base y destino; no cambia datos. Conservar juntos `*.archive.gz`, `*.manifest` y `*.sha256`, registrar ruta, hash, hora UTC, SHA de Git y almacenamiento externo. Comprobar que el backup terminó antes de apagar el servidor. Una prueba de restauración aislada es la verificación más fuerte; el chequeo de integridad no demuestra que toda la aplicación pueda arrancar. Verificar la clase de almacenamiento del PVC MongoDB: los snapshots del servidor no incluyen Cloud Volumes adjuntos.

Para restaurar desde **VM-KIND con contexto de producción**, mantener el lock, detener las escrituras y escoger un MongoDB de destino con la misma `MONGO_APP_DATABASE`. Probar primero en un entorno aislado y revisar el nombre de base/objetivo mostrado por el comando sin `--apply`. La operación real **borra la base de aplicación completa**, restaura las colecciones e índices del archivo y recrea el usuario de aplicación con los Secrets del pod de destino. Pierde todas las escrituras posteriores al backup; no fusiona datos. No ejecutarla sobre una aplicación de versión incompatible ni sin decisión explícita de recuperación:

```bash
scripts/k8s/restore-mongodb.sh --namespace infra --input "$backup_file"
scripts/k8s/restore-mongodb.sh --namespace infra --input "$backup_file" --apply --replace-database
```

No usar `init-mongodb-server.sh` como paso de restore: incluye la realineación de colecciones y podría volver a modificarlas. Si el restore se interrumpe después del borrado, mantener la aplicación bloqueada y repetir con un archivo verificado o recuperar el destino aislado.

#### Apagar, tomar snapshot y arrancar el CX33

Después del backup MongoDB, mantener el lock activo y confirmar que no hay órdenes en curso ni escrituras pendientes. Conservar el acceso a Hetzner Console; el SSH se interrumpirá al apagar. **[VM-KIND]** abrir la conexión y **[HETZNER]** solicitar el apagado limpio:

```bash
ssh -i "$HETZNER_KEY" -p 2222 "$HETZNER_USER@$HETZNER_HOST"
sudo systemctl poweroff
```

Las dos líneas representan pasos consecutivos: la segunda se ejecuta **dentro** de la sesión del CX33. Esperar en Hetzner Console a que el servidor figure como **Off**; no tomar el snapshot mientras se está apagando. En el proyecto correcto, abrir **Snapshots → Take Snapshot**, seleccionar el CX33 y describirlo con fecha UTC, SHA de Git y propósito `pre-v0.0.13`. Esperar a que la creación termine y la imagen esté disponible. Registrar su identificador fuera del repositorio y activar la protección contra borrado si se usa en este proyecto. Solo entonces volver a encender el **mismo servidor** desde Console y esperar a que SSH y K3s estén disponibles. Hetzner [recomienda apagar el servidor para garantizar la consistencia de la imagen](https://docs.hetzner.com/cloud/servers/backups-snapshots/faq/); el snapshot cubre el disco del servidor, **no** los Cloud Volumes adjuntos. El backup lógico de MongoDB sigue siendo necesario para recuperar esa base sin reconstruir el disco completo.

Comprobar la identidad SSH contra la huella previamente confiada; una clave de host inesperada exige investigar antes de continuar. No aceptar automáticamente una huella nueva. Abrir **una nueva sesión SSH con clave** y ejecutar `kubectl get nodes`, `kubectl get pods -A` y `kubectl get pvc -A`; el nodo debe estar `Ready` y los volúmenes y servicios críticos recuperados. Mantener el lock durante la actualización del host.

#### Actualizar paquetes del sistema y comprobar el endurecimiento

**Observación tras el reinicio comunicado por el operador (1 de noviembre de 2026, 15:18 UTC):** el mensaje de bienvenida identifica Ubuntu 24.04.4 LTS, kernel `6.8.0-147-generic`, uso de `/` del 38,6 %, memoria del 83 % y swap del 5 %. Indica **57 actualizaciones disponibles**, una actualización de seguridad adicional asociada a ESM Apps desactivado y ofrece Ubuntu 26.04.1 LTS. El operador comunica que tomó un snapshot; conservar fuera de Git su identificador y comprobar en Hetzner Console que está terminado y disponible, así como si se tomó con el servidor apagado. El login confirma acceso a una sesión, pero no demuestra por sí solo que K3s, los PVC, el acceso SSH por clave y el firewall estén recuperados. Esta observación no acredita que se haya ejecutado `apt-get upgrade`, que se haya resuelto la actualización ESM ni que exista un backup lógico de MongoDB.

**Preflight de paquetes recibido después del reinicio:** `apt-get update` terminó sin errores; la simulación `apt-get -s upgrade` propone exactamente **57 actualizaciones, ninguna instalación o eliminación y ningún paquete retenido**. `/` tiene 44 GiB disponibles de 75 GiB; `free -h` muestra 3,5 GiB de memoria disponible y swap de 8 GiB sin uso. El plan incluye `netplan`, `cloud-init`, `iproute2` y `qemu-guest-agent` (acceso/red), `containerd` y `runc` (contenedores), y `gitlab-runner`/`gitlab-runner-helper-images` de **18.10.1 a 19.5.2** desde el repositorio externo de GitLab (CI). Es una simulación: las líneas `Inst` y `Conf` no demuestran que se hayan instalado. La salida de `pro security-status --esm-apps` enumera nueve paquetes cubiertos, pero no identifica una actualización ESM pendiente; volver a consultarla tras actualizar `ubuntu-pro-client` y refrescar índices. El aviso anterior del MOTD puede estar desactualizado.

**[HETZNER]** En la sesión SSH, confirmar distribución, kernel, espacio y memoria reales antes de actualizar paquetes. Con el 83 % de memoria observado, revisar `free -h` y la capacidad durante la operación. Usar `apt` para Ubuntu 24.04.4; revisar la simulación y los paquetes retenidos antes de aplicarla, y atender los cambios de configuración, especialmente SSH y red. **No ejecutar `do-release-upgrade` a 26.04.1 ni actualizar K3s en esta ventana**: requieren otro plan y validación.

```bash
cat /etc/os-release
uname -r
df -h /
free -h
swapon --show
sudo apt-get update
sudo apt-get -s upgrade
apt list --upgradable
pro security-status --esm-apps
```

El salto mayor de GitLab Runner queda fuera de esta ventana. Retener temporalmente sus dos paquetes y comprobar el resultado antes de actualizar el resto. Mantener abierta la sesión SSH actual y atender cualquier pregunta sobre archivos de configuración de red o SSH; no sustituir automáticamente la configuración local:

```bash
sudo apt-mark hold gitlab-runner gitlab-runner-helper-images
apt-mark showhold
sudo apt-get upgrade

apt list --upgradable
pro security-status --esm-apps

sudo sshd -t
sudo sshd -T | awk '$1=="port" || $1=="pubkeyauthentication" || $1=="passwordauthentication" || $1=="kbdinteractiveauthentication" || $1=="permitrootlogin" {print}'

systemctl is-active k3s gitlab-runner
kubectl get nodes
kubectl get pods -A
kubectl get pvc -A

if test -e /run/reboot-required; then
  cat /run/reboot-required.pkgs
else
  echo "reboot_not_required"
fi
```

Los 57 paquetes están confirmados por la simulación, pero la salida previa no acredita su instalación. Tras el cambio, es normal que `apt list --upgradable` siga mostrando `gitlab-runner` y `gitlab-runner-helper-images`; `apt-mark showhold` debe confirmar que ambos continúan retenidos. Actualizar esos paquetes a 19.5.2 requiere una ventana separada con revisión de compatibilidad, prueba de un job y retirada explícita del hold; no ejecutar `apt-mark unhold` durante este procedimiento. Verificar en GitLab que el runner sigue disponible antes de iniciar el job `build`. Si `/run/reboot-required` existe, seguir el paso de reinicio siguiente y repetir las comprobaciones. `apt-get upgrade` sin ESM Apps no instala un parche exclusivo de ese servicio; la activación de Ubuntu Pro o una alternativa requiere una decisión separada **si la nueva consulta confirma que sigue pendiente**. [Ubuntu explica el aviso de ESM del MOTD](https://documentation.ubuntu.com/pro-client/en/latest/explanations/motd_messages/) y [cómo interpretar `pro security-status`](https://ubuntu.com/pro-client/docs/en/docs/explanations/how_to_interpret_the_security_status_command/).

**Resultado observado el 1 de noviembre de 2026:** se instalaron 55 actualizaciones sin paquetes nuevos ni eliminados; `gitlab-runner` y `gitlab-runner-helper-images` permanecieron retenidos en 18.10.1. `pro security-status --esm-apps` no mostró una actualización ESM pendiente concreta. `sshd -t` terminó correctamente y la configuración efectiva devolvió puerto 2222, autenticación por clave habilitada, contraseña e interacción por teclado deshabilitadas y acceso root deshabilitado. K3s y GitLab Runner estaban `active`, el nodo `Ready`, todos los pods preparados y los nueve PVC `Bound`. Los reinicios visibles de los pods corresponden al arranque del host unos 15 minutos antes de la lectura, no al despliegue de v0.0.13.

La actualización de AppArmor mostró el aviso `/var/lib/dpkg/info/apparmor.postinst: 148: [: Illegal number: yes`, aunque el paquete terminó de configurarse y recargó los perfiles. `/run/reboot-required.pkgs` devolvió `apparmor`, por lo que esta actualización **requiere reiniciar antes del pipeline**. Tras el reinicio, comprobar además `systemctl is-active apparmor` y `sudo aa-status`; no continuar si AppArmor está inactivo, hay perfiles con error o `journalctl -b -p err` muestra un fallo relacionado.

**Resultado observado después del reinicio:** AppArmor, K3s y GitLab Runner están activos; AppArmor carga sus perfiles y mantiene los procesos de los contenedores en modo enforce. El nodo está `Ready`, los nueve PVC siguen `Bound`, los dos paquetes del Runner continúan retenidos y la conexión SSH nueva por clave en el puerto 2222 funciona. Sin embargo, el arranque **no supera la puerta de estabilidad ordinaria**: el kernel registró múltiples OOM de procesos `geth` cercanos a 2 GiB, `news-chain` está en `CrashLoopBackOff` y los tres validadores aparecen `Unknown`. Los StatefulSets de Geth continúan deseando una réplica cada uno. Esta degradación pertenece a la versión anterior; la capacidad de desactivar Blockchain forma parte de la versión candidata y todavía no está instalada.

**[HETZNER]** Recoger el diagnóstico sin reiniciar ni escalar componentes manualmente:

```bash
kubectl describe node trust-news-prod
kubectl top node
kubectl top pods -A --sort-by=memory
kubectl get pods -A -o wide
kubectl get events -A --sort-by='.lastTimestamp'
kubectl describe pod -n apis -l app=news-chain
kubectl logs -n apis deployment/news-chain --previous --tail=200
kubectl describe pod -n apis -l app=validate-worker
kubectl get statefulset -n blockchain
kubectl get pod -n blockchain -o custom-columns='NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,LAST_REASON:.status.containerStatuses[0].lastState.terminated.reason,LAST_EXIT:.status.containerStatuses[0].lastState.terminated.exitCode'
```

Los OOM observados son de cgroup y afectan a Geth; no equivalen por sí solos a un OOM global del nodo. Determinar con `describe`, métricas y eventos qué contenedor alcanzó su límite y por qué los validadores quedaron `Unknown`, y conservar la salida como evidencia previa. Como el destino de esta revisión es LIGHT con Blockchain `OFF`, no ampliar memoria ni ocultar el fallo con reinicios repetidos.

**No ejecutar todavía el modo completo `BLOCKCHAIN_ENABLED=OFF scripts/k8s/set-blockchain-mode.sh`.** Ese modo y el soporte de `blockchain-mode` pertenecen a la versión nueva. Los pods antiguos no interpretan el nuevo ConfigMap y no proporcionan por sí mismos el gate de nuevas órdenes. Durante toda la transición, el maintenance lock de Cloudflare debe permanecer activo y verificado; es el que impide que entren órdenes externas en la versión antigua.

La consulta de pendientes sí es compatible con el `news-handler` anterior y es de solo lectura. El archivo local no puede ejecutarse por su ruta en Hetzner; usar la copia sincronizada en el directorio operativo.

**[HETZNER]** Ejecutar y conservar el número obtenido:

```bash
cd /home/sysadmin/trust-news
scripts/k8s/set-blockchain-mode.sh --check-pending
```

Si devuelve un número mayor que cero o no puede consultarlo, detener la transición y resolver las órdenes pendientes con la versión Blockchain anterior. Si devuelve cero y el diagnóstico confirma que almacenamiento, MongoDB, Kafka, K3s y el runner están disponibles, esta degradación no bloquea el pipeline: el despliegue controlado es el mecanismo que instala la funcionalidad nueva y retira la carga de Geth.

**Decisión observada en esta ventana:** la consulta encontró dos órdenes y el operador autorizó cancelarlas. Se actualizó la copia de `set-blockchain-mode.sh` en Hetzner antes de ejecutar la acción conjunta.

#### Detener el runtime Blockchain saturado

Si Geth continúa saturando CPU o provocando OOM antes del pipeline, se admite una parada anticipada y reversible del runtime. Esta acción funciona contra la versión antigua: vuelve a comprobar las órdenes pendientes y escala únicamente `deployment/news-chain` y los StatefulSets `geth-bootnode`, `geth-miner` y `geth-rpc-endpoint` a cero. Conserva sus PVC, Kafka, MongoDB, Gateway, News Handler y los servicios LIGHT. No escalar `news-handler` a cero porque la CI lo necesita para repetir el gate antes del rollout.

Prerequisito: haber completado la sincronización **VM-KIND → HETZNER** anterior y verificar que el maintenance lock sigue activo. Si el gate devuelve cero, **[HETZNER]**:

```bash
cd /home/sysadmin/trust-news
MAINTENANCE_LOCK_CONFIRMED=true scripts/k8s/set-blockchain-mode.sh --stop-chain-runtime

kubectl get deployment news-chain -n apis
kubectl get statefulset -n blockchain
kubectl get pods -n blockchain
kubectl top node
```

La acción falla sin confirmación explícita del maintenance lock, si no puede consultar MongoDB o si encuentra órdenes Blockchain pendientes. La salida esperada tras completarla es cero réplicas deseadas para `news-chain` y los tres StatefulSets, desaparición de los pods Geth y descenso de CPU/memoria. No borra datos ni PVC. Skaffold y el motor OFF de la versión nueva volverán a declarar el estado durante el pipeline.

Para la decisión actual de cancelar las dos órdenes, **[HETZNER]** ejecutar la acción conjunta después de volver a sincronizar el script:

```bash
cd /home/sysadmin/trust-news
CANCEL_PENDING_CONFIRMED=true \
MAINTENANCE_LOCK_CONFIRMED=true \
scripts/k8s/set-blockchain-mode.sh --cancel-pending-and-stop-chain

scripts/k8s/set-blockchain-mode.sh --check-pending
kubectl get deployment news-chain -n apis
kubectl get statefulset -n blockchain
kubectl get pods -n blockchain
kubectl top node
```

La acción no borra órdenes. Cambia únicamente las órdenes Blockchain en curso a `FAILED`, pone `validators_pending=0` y guarda `cancellation.code=BLOCKCHAIN_DISABLED_BY_OPERATOR`, motivo, estado anterior y fecha UTC. Después vuelve a comprobar el gate, escala el runtime a cero y repite la comprobación. La salida final del gate debe ser cero.

**Resultado observado:** la acción canceló dos órdenes, una desde `VALIDATION_PENDING` y otra desde `BLOCKCHAIN_PENDING`; escaló `deployment/news-chain` y los StatefulSets `geth-bootnode`, `geth-miner` y `geth-rpc-endpoint`; y terminó después de comprobar de nuevo que no había pendientes. La lectura posterior de todos los namespaces ya no mostró pods `news-chain` ni pods en `blockchain`. Todos los pods restantes aparecieron `Running/Ready`, incluidos los tres validadores. No registrar en Git los identificadores de las órdenes.

#### Verificar la parada y preparar el commit

**[HETZNER]** Confirmar el estado deseado y que bajó la presión del nodo:

```bash
cd /home/sysadmin/trust-news
scripts/k8s/set-blockchain-mode.sh --check-pending
kubectl get deployment news-chain -n apis -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas'
kubectl get statefulset -n blockchain -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas'
kubectl get pods -n blockchain
kubectl top node
kubectl get events -A --sort-by='.lastTimestamp' | tail -40
```

En la copia ejecutada durante esta ventana, un gate correcto con cero pendientes no imprime el número y termina sin error después del aviso de selección del contenedor. La versión local queda corregida para mostrar `Pending blockchain orders: 0` en futuras sincronizaciones. `news-chain` y los tres StatefulSets deben mostrar `DESIRED=0`; no debe quedar ningún pod Blockchain; y no deben aparecer nuevos OOM después de la parada.

**Resultado observado:** el gate terminó sin error, `news-chain` y los tres StatefulSets mostraron `DESIRED=0`, y no quedó ningún recurso Pod en el namespace `blockchain`. El nodo bajó a 191 millicores/4 % de CPU y 3624 MiB/46 % de memoria. Los eventos `BackOff` de Geth y `news-chain` son anteriores al escalado; los eventos posteriores registran `ScalingReplicaSet`, `Killing` y `SuccessfulDelete` alrededor de dos minutos antes de la lectura. Los fallos de probes de Loki y Keycloak pertenecen al arranque anterior y ambos pods aparecen actualmente `Running/Ready`.

La única advertencia posterior es `DNSConfigForming` en CoreDNS: el host entregó más nameservers de los admitidos y Kubernetes omitió algunos. No demuestra por sí sola un fallo DNS, pero debe comprobarse antes del pipeline.

#### Validar DNS y ausencia de nuevos OOM

**[HETZNER]** Ejecutar una consulta DNS desde un pod temporal y revisar el kernel desde la parada:

```bash
kubectl delete pod dns-check -n default --ignore-not-found
kubectl run dns-check -n default --image=busybox:1.36 --restart=Never \
  --command -- sh -c 'nslookup kubernetes.default.svc.cluster.local && nslookup kafka.infra.svc.cluster.local && nslookup mongodb.infra.svc.cluster.local'
kubectl wait -n default --for=jsonpath='{.status.phase}'=Succeeded pod/dns-check --timeout=60s
kubectl logs -n default pod/dns-check
kubectl delete pod dns-check -n default
sudo journalctl -k --since '10 minutes ago' --no-pager | grep -Ei 'oom|out of memory|killed process' || echo no_new_kernel_oom
```

Las tres consultas deben devolver direcciones del clúster, el pod debe terminar en `Succeeded` y el journal no debe contener un OOM posterior a la parada. Si falla la resolución, conservar el maintenance lock y revisar `/etc/resolv.conf` y la configuración `resolv-conf` de K3s antes del pipeline. Si pasa, volver a **VM-KIND**, revisar todos los cambios pendientes —incluido el nuevo `scripts/ci/sync-remote-files.sh`—, ejecutar las validaciones locales y crear/publicar el commit candidato. La CI solo puede usar contenido incluido en ese commit.

**Resultado observado:** el pod temporal terminó en `Succeeded` y las consultas a `kubernetes.default.svc.cluster.local`, `kafka.infra.svc.cluster.local` y `mongodb.infra.svc.cluster.local` devolvieron direcciones internas del clúster mediante CoreDNS (`10.43.0.10`). El pod se eliminó al terminar y el journal devolvió `no_new_kernel_oom`. La advertencia anterior `DNSConfigForming` no está impidiendo la resolución dentro del clúster y no se han producido nuevos OOM desde la parada de Geth.

#### Revisar y publicar el commit candidato desde VM-KIND

**[VM-KIND]** Revisar y publicar sin forzar el push:

```bash
cd /home/adminu/blockchain/tfm
bash -n scripts/k8s/set-blockchain-mode.sh scripts/ci/sync-remote-files.sh
git status --short
git diff --check
git diff -- .gitlab-ci.yml docs/deploy/main-posttfm-hetzner-smart-light.md scripts/k8s/set-blockchain-mode.sh scripts/ci/sync-remote-files.sh
git add .gitlab-ci.yml \
  docs/deploy/main-posttfm-hetzner-smart-light.md \
  scripts/k8s/set-blockchain-mode.sh \
  scripts/ci/sync-remote-files.sh
git diff --cached --check
git status --short
git commit -m "Add controlled LIGHT deployment transition"
git push gitlab postTFM
```

**Resultado observado:** el commit candidato se publicó en GitLab y GitHub. El checkout local quedó limpio en la rama `postTFM`, con `HEAD` y `origin/postTFM` en `ad40321369bfd901022df19995369d719c65ba3a` (`ad40321`, `previa a deploy`).

#### Preflight de Secrets en Hetzner

**[HETZNER]** Antes de iniciar el pipeline, comprobar contra K3s que todos los Secrets consumidos por `apis-frontend-prod` existen y que contienen valores no vacíos ni placeholders. El motor siguiente admite varias claves alternativas para un mismo requisito, no imprime sus valores y termina con error si falta algún requisito:

```bash
set +x

secret_value_is_usable() {
  local namespace="$1" secret="$2" key="$3" encoded value compact
  encoded="$(kubectl get secret "$secret" -n "$namespace" -o "jsonpath={.data.${key}}" 2>/dev/null || true)"
  [ -n "$encoded" ] || return 1
  value="$(printf '%s' "$encoded" | base64 --decode 2>/dev/null || true)"
  compact="${value//[$'\t\r\n ']/}"
  value=
  case "${compact,,}" in
    ""|replace-me|replace_me|changeme|change-me|example|example-*|your-*|todo|xxx|xxxxxxxx)
      return 1
      ;;
  esac
}

require_secret_any() {
  local namespace="$1" secret="$2"
  shift 2
  if ! kubectl get secret "$secret" -n "$namespace" >/dev/null 2>&1; then
    echo "ERROR: falta Secret $namespace/$secret" >&2
    return 1
  fi
  local key
  for key in "$@"; do
    if secret_value_is_usable "$namespace" "$secret" "$key"; then
      echo "OK: $namespace/$secret contiene una clave válida para $*"
      return 0
    fi
  done
  echo "ERROR: $namespace/$secret requiere al menos una clave válida entre: $*" >&2
  return 1
}

errors=0
require_secret_any apis source-router-enc OPENROUTER_API_KEY || errors=$((errors + 1))
require_secret_any apis source-router-enc EXA_API_KEY API_KEY_PROVIDER || errors=$((errors + 1))
require_secret_any apis api-keys OPENROUTER_API_KEY || errors=$((errors + 1))
require_secret_any apis search-secret EXA_API_KEY API_KEY_PROVIDER || errors=$((errors + 1))

for key in MONGO_APP_USER MONGO_APP_PWD MONGO_APP_HOST MONGO_APP_PORT MONGO_APP_DATABASE MONGO_APP_AUTHSOURCE; do
  require_secret_any apis mongodb-app-secret "$key" || errors=$((errors + 1))
done

for worker in 1 2 3; do
  for key in PRIVATE_KEY ACCOUNT_ADDRESS API_KEY; do
    require_secret_any apis "validator-secret-$worker" "$key" || errors=$((errors + 1))
  done
done

if [ "$errors" -ne 0 ]; then
  echo "Preflight de Secrets FALLIDO: $errors requisito(s) ausente(s) o no válido(s)." >&2
else
  echo "Preflight de Secrets OK: no se han mostrado valores."
fi
test "$errors" -eq 0
```

Los requisitos cubren el nuevo LLM OpenRouter y la búsqueda Exa del Source Router, el cambio de Generate Assertions a OpenRouter, Evidence Search, MongoDB y los tres validadores incluidos en el perfil. `EXA_API_KEY` y `API_KEY_PROVIDER` son alternativas; tener una no obliga a duplicarla. Si falla el preflight, no lanzar `deploy`: crear o actualizar el Secret mediante el procedimiento privado del paso 2 y repetir el bloque completo. Esta comprobación evita claves ausentes, vacías o de ejemplo; la validez remota, el modelo habilitado, la cuota y el presupuesto se confirman en las cuentas de OpenRouter y Exa sin copiar credenciales al repositorio ni a los logs.

Si se ha aprobado que Source Router comparta las mismas credenciales ya validadas de Generate Assertions y Evidence Search, **[HETZNER]** se puede crear `source-router-enc` copiando los datos codificados entre Secrets, sin decodificarlos, imprimirlos ni guardarlos en disco:

```bash
set +x
copy_status=0
openrouter_b64="$(kubectl get secret api-keys -n apis -o jsonpath='{.data.OPENROUTER_API_KEY}')"
search_key=EXA_API_KEY
search_b64="$(kubectl get secret search-secret -n apis -o jsonpath='{.data.EXA_API_KEY}')"
if [ -z "$search_b64" ]; then
  search_key=API_KEY_PROVIDER
  search_b64="$(kubectl get secret search-secret -n apis -o jsonpath='{.data.API_KEY_PROVIDER}')"
fi

if [ -z "$openrouter_b64" ] || [ -z "$search_b64" ]; then
  echo "ERROR: no se pueden reutilizar las credenciales de origen" >&2
  copy_status=1
else
  cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: source-router-enc
  namespace: apis
type: Opaque
data:
  OPENROUTER_API_KEY: ${openrouter_b64}
  ${search_key}: ${search_b64}
EOF
fi
unset openrouter_b64 search_b64 search_key
test "$copy_status" -eq 0
```

Si Source Router debe tener credenciales, cuota o trazabilidad propias, no reutilizar las anteriores: crear `source-router-enc` desde el fichero privado descrito en el paso 2. En ambos casos, repetir después **todo** el preflight y exigir el único resultado final `Preflight de Secrets OK`. No ejecutar el pipeline con un fallo aunque el shell interactivo haya vuelto al prompt.

**Resultado recibido del operador:** el preflight completo terminó con `Preflight de Secrets OK: no se han mostrado valores.` Pasaron las claves requeridas de `source-router-enc` (OpenRouter y Exa/API_KEY_PROVIDER), `api-keys`, `search-secret`, `mongodb-app-secret` y los tres Secrets de validadores. Esto acredita que los Secrets existen y contienen valores no vacíos ni placeholders según el motor; no prueba que las credenciales sean aceptadas por los proveedores ni que haya cuota disponible. Se cierra el bloqueo anterior por ausencia de `source-router-enc`.

#### Comprobar el SHA y ejecutar el pipeline de GitLab

En GitLab, abrir el pipeline de la rama `postTFM` y comprobar antes de ejecutar `build` o `deploy` que muestra exactamente el commit `ad40321369bfd901022df19995369d719c65ba3a`. Mantener `PROFILE=apis-frontend-prod`, establecer `BLOCKCHAIN_ENABLED=OFF` y conservar activo el maintenance lock durante todo el pipeline. Si el SHA no coincide, no ejecutar los jobs y revisar la rama seleccionada y el origen del pipeline.

La secuencia del job productivo para `BLOCKCHAIN_ENABLED=OFF` debe ser:

1. Con el maintenance lock activo, consultar que no existen órdenes Blockchain pendientes.
2. Ejecutar `set-blockchain-mode.sh --prepare-off`. Esta acción solo crea o actualiza `blockchain-mode=false`; no reinicia los deployments antiguos.
3. Desplegar con Skaffold los nuevos `news-handler`, validadores y `gateway`, que ya consumen `blockchain-mode` y arrancan en modo LIGHT.
4. Ejecutar el motor completo después del despliegue. Este reinicia los consumidores nuevos y escala `news-chain` y los StatefulSets Geth a cero.

La CI contiene esta secuencia y ejecuta el comando siguiente dentro de **GITLAB-RUNNER**, desde el checkout efímero del commit y con su túnel a K3s. No es un comando que el operador deba ejecutar ahora en VM-KIND ni en Hetzner:

```bash
BLOCKCHAIN_ENABLED=OFF scripts/k8s/set-blockchain-mode.sh
```

Este paso solo es válido cuando las imágenes y manifests de la versión candidata ya se han desplegado. Conserva Kafka y los servicios LIGHT, reinicia los consumidores nuevos de `blockchain-mode` y escala `news-chain` y Geth a cero. Después del job, repetir desde HETZNER la comprobación de pods y eventos: los validadores LIGHT deben quedar `Running/Ready`, `news-chain` y los StatefulSets Geth deben tener cero réplicas deseadas, y no deben aparecer nuevos OOM de Geth. Solo entonces retirar el maintenance lock siguiendo las verificaciones posteriores de esta guía.

Comprobar el resultado efectivo esperado: **`port 2222`, `pubkeyauthentication yes`, `passwordauthentication no`, `kbdinteractiveauthentication no` y `permitrootlogin no`**. Si existen reglas `Match` en `sshd_config`, repetir `sshd -T -C` con usuario, host y dirección de origen reales: la salida global puede no representar la política de esa conexión. Conservar la sesión abierta mientras se prueba **otra conexión** con la clave autorizada desde VM-KIND. Probar también sin clave desde otra terminal: debe rechazarse sin ofrecer login por contraseña o teclado interactivo; si aparece un prompt de contraseña, cancelarlo y detener el despliegue. Una sesión existente o `sshd -t` correcto no prueban por sí solos que el acceso nuevo siga funcionando. [Ubuntu documenta el orden efectivo de `sshd_config` y la comprobación previa al reinicio](https://ubuntu.com/server/docs/how-to/security/openssh-server/).

**[VM-KIND]** Ejecutar las pruebas de conexión contra Hetzner:

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -i "$HETZNER_KEY" -p 2222 "$HETZNER_USER@$HETZNER_HOST" 'id -un'
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive -o NumberOfPasswordPrompts=1 -p 2222 "$HETZNER_USER@$HETZNER_HOST" true
```

La segunda prueba debe terminar con autenticación denegada; **no introducir una contraseña** si se solicita. Revisar si `apt list --upgradable` deja paquetes pendientes y resolverlos o documentar la razón antes de continuar. Revisar además en Hetzner Console el firewall del CX33: `2222/tcp` solo desde los orígenes administrativos/runner autorizados, `443/tcp` solo desde rangos Cloudflare verificados y `22/tcp`, `80/tcp`, `6443/tcp` y puertos internos cerrados desde Internet. En el host, revisar `sudo ss -lntp` y las reglas del firewall que realmente use (`ufw`/`nftables`); una lista de sockets no sustituye la prueba desde una red externa. Confirmar que la API K3s solo se alcanza por el túnel SSH del [quick start](../quick_start_hetzner.md#3-acceso-ssh-y-kubernetes) y que Cloudflare conserva lock y mTLS.

Si `/run/reboot-required` existe, ejecutar `sudo systemctl reboot` durante esta ventana y esperar el regreso del CX33. En esta ejecución existe y señala `apparmor`; el reinicio es obligatorio. Después, repetir **todas** las comprobaciones de SSH, firewall, nodo, pods y PVC. **[HETZNER]** Ejecutar:

```bash
systemctl is-active apparmor k3s gitlab-runner
sudo aa-status
sudo journalctl -b -p err --no-pager
apt-mark showhold
apt list --upgradable
```

Registrar versión del sistema, kernel, paquetes actualizados, snapshot y resultados, sin credenciales ni huellas en Git. **No iniciar el pipeline de despliegue** si AppArmor/K3s, MongoDB, Kafka, el runner o los PVC no están disponibles; si se alteró el acceso por clave; si se habilitó login sin clave; si cambió la exposición de puertos; si el snapshot no está disponible; o si existen órdenes Blockchain pendientes. El estado degradado ya identificado de Geth, `news-chain` y los validadores antiguos es la excepción controlada: con pendientes a cero y el maintenance lock activo, el pipeline instala el modo OFF que debe recuperarlo. Resolver cualquier otro problema con el lock activo y el acceso de Console; una reversión completa al snapshot sobrescribe los cambios del disco posteriores a su captura.

### 4. Construir y desplegar desde GitLab

En GitLab, `Build > Pipelines > Run pipeline`, rama `postTFM`, variables explícitas:

```dotenv
PROFILE=apis-frontend-prod
BLOCKCHAIN_ENABLED=OFF
```

Ejecutar/esperar `build` y comprobar que su `build.json` pertenece al SHA elegido; el job `deploy` exige ese archivo aunque `needs: build` sea opcional. Esperar a que pase el preflight TLS. **Antes de lanzar `deploy`, confirmar el punto 3 completo: backup MongoDB, apagado y snapshot disponible, actualización del host y verificaciones de seguridad/K3s**. Al comenzar, el checkout de GITLAB-RUNNER instala y verifica las versiones del SHA de `backup-mongodb.sh`, `restore-mongodb.sh` y `set-blockchain-mode.sh` en `OPERATIONS_SCRIPTS_DIR` de Hetzner. Después realinea MongoDB, comprueba las órdenes pendientes y prepara `blockchain-mode=false` sin reiniciar los pods antiguos. Luego Skaffold aplica las imágenes y el motor ejecuta la desactivación completa con el código nuevo: reinicia sus consumidores y escala Geth/`news-chain` a cero. Finalmente se comprueban rollouts, `/gui` y la reconciliación Keycloak. No sustituir este proceso por parches `kubectl apply` o `helm upgrade` manuales.

Si el salto incluye la migración inicial de Traefik a `/gui` y aún no está aplicada en el destino, seguir la secuencia controlada del runbook con lock habilitado: pipeline separado `PROFILE=traefik-prod`, validación, y **después** el de `apis-frontend-prod`. Si Traefik `/gui` ya existe y no cambió, no redeployar `traefik-prod` innecesariamente. Para una instalación nueva, ejecutar antes los perfiles de infraestructura según el runbook, cada uno en pipeline separado.

**Resultado comunicado por el operador:** despliegue completado correctamente. No se compartieron aquí salidas de jobs ni el SHA del pipeline. Las comprobaciones posteriores de K3s se registran en el paso 5.

### 5. Verificar el estado efectivo, no solo los manifiestos

**Primera comprobación comunicada:** `kubectl get pods --all-namespaces` mostró todos los pods listados en `Running` y Ready. Evidence Search tenía dos pods `1/1`; Source Router, Gateway, News Handler, Generate Assertions, los tres validadores y frontend también aparecían `1/1`, sin reinicios en sus edades actuales. Los pods antiguos de `infra` y `kube-system` mostraban reinicios de hace 26 horas, sin fallos actuales en esa salida. Esa lista no informaba réplicas deseadas ni ConfigMaps; la comprobación posterior que completa el paso está registrada a continuación.

**Resultado comunicado por el operador:** los rollouts de Evidence Search, Source Router, News Handler, Gateway y frontend terminaron correctamente. El ConfigMap informa `SMART` para Evidence Search y `false` para Blockchain; el Deployment de Evidence Search está `2/2`, `news-chain` está `0/0` y los StatefulSets `geth-bootnode`, `geth-miner` y `geth-rpc-endpoint` tienen cero réplicas listas. Ambos pods de Evidence Search informan `SMART` en su entorno. Con estas salidas, el paso 5 queda verificado.

**[HETZNER]** Con el K3s local del host, tras el pipeline:

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

**Estado comunicado por el operador:** el maintenance lock está desactivado durante una ventana de prueba de la GUI. Confirmar en Cloudflare que la regla mTLS general temporal y la administrativa siguen activas; al acabar, devolver el lock al estado operativo acordado y registrar el resultado. Una prueba funcional desde fuera requiere que el lock permita el paso y que el cliente presente un certificado mTLS válido.

#### Comprobación externa de seguridad durante la ventana

El [informe de evaluación externa del 2 de noviembre](pentest-externo-assermetry-2026-11-02.md) amplía las pruebas de rutas, métodos, CORS, TLS y cabeceras, con su alcance y pendientes.

**2026-11-02, 18:49–18:51 UTC.** Desde VM-KIND se enviaron peticiones de solo lectura al dominio público, sin certificado cliente ni JWT y sin seguir redirecciones. Las respuestas HTTPS provinieron de Cloudflare y la verificación del certificado del servidor terminó correctamente. No se enviaron credenciales ni órdenes.

| Comprobación | Resultado observado | Alcance de la conclusión |
| --- | --- | --- |
| `GET /` y `GET /gui` | `302` a `https://assermetry.com/gui/` | Coincide con las Single Redirects documentadas, que pueden ejecutarse antes del WAF. |
| `GET /gui/`, discovery OIDC, `/backend/auth/is-admin` | `403` | Sin certificado cliente no se accede a estas rutas; el código HTTP no identifica por sí solo la regla exacta. |
| `GET /auth/admin/`, `/backend/admin/llm`, `/backend/openapi.json`, `/backend/docs`, `/.git/config` | `403` | No se expusieron en esta prueba sin certificado. Hace falta atribución en Cloudflare Security Events para demostrar cada regla permanente. |
| `GET http://assermetry.com/gui/` | `403` de Cloudflare, sin redirección HTTPS | No sirvió contenido de la aplicación por HTTP en esta ruta; comprobar por separado la política esperada de redirección. |
| TLS 1.0 / 1.1 | Falló la negociación | El borde rechazó estas versiones desde este cliente. |
| TLS 1.2 / 1.3 | Negociación correcta, certificado del servidor válido y respuesta `403` | Se confirmó el transporte TLS; el `403` corresponde a un control HTTP posterior. |

En las respuestas `302` y `403` inspeccionadas no apareció `Strict-Transport-Security`; esto no determina si la cabecera se añade a las respuestas `200` con certificado. El operador debe comprobar en Cloudflare Security Events qué regla produjo los `403`, y probar con certificado cliente válido que la GUI/OIDC funcionan mientras las mismas rutas sin certificado siguen bloqueadas. Con certificado pero sin JWT, comprobar que Gateway rechaza una ruta protegida; comprobar también el acceso administrativo con y sin rol. No se ha comprobado la configuración efectiva del firewall de Hetzner ni el origen directo.

**Prueba funcional comunicada mediante captura de la GUI:** desde `https://assermetry.com/gui/` se visualiza una sesión protegida y una orden en modo LIGHT marcada `Completada`, con 5/5 etapas y 9/9 respuestas de validación. La pantalla muestra resultado `Mixta` y, en el resumen de afirmaciones, una confirmada y dos desmentidas. El contador de respuestas de validadores muestra tres confirmadas, cinco desmentidas y una no concluyente; son agregaciones distintas en la interfaz. La última actualización visible es `02/11/2026, 19:52`. Esta captura acredita que el flujo GUI llegó a un resultado terminal por el dominio público; no permite comprobar por sí sola el certificado mTLS presentado, la atribución de reglas Cloudflare, las fuentes de la pestaña Evidencias, la exactitud factual ni el aislamiento entre usuarios. No se registra el identificador de orden ni el nombre de usuario de la captura en Git.

**Segunda captura, pestaña Evidencias de la misma orden:** las tres decisiones agregadas son `TRUE` para España (>49 millones de habitantes en 2025), `FALSE` para Alemania (inflación anual negativa en 2025) y `FALSE` para Francia (100 % de electricidad renovable en 2025). Los votos visibles son 3 `TRUE`; 2 `FALSE` y 1 `UNKNOWN`; y 3 `FALSE`, respectivamente. El voto `UNKNOWN` de Alemania informa que Evidence Search no entregó contextos citables y que no se llamó al LLM para esa validación. Es una abstención explícita dentro de una orden completada, no un fallo técnico visible de toda la orden; requiere revisar trazas y cobertura documental antes de extrapolar calidad. Como contraste independiente de los hechos, el [INE](https://www.ine.es/dyngs/Prensa/es/CensoVariables2025.html) publicó 49.128.297 habitantes a 1 de enero de 2025; [Destatis](https://www.destatis.de/EN/Press/2026/01/PE26_019_611.html) informó inflación positiva del 2,2 % de media anual y del 1,8 % interanual en diciembre; [RTE](https://analysesetdonnees.rte-france.com/en/annual-review-2025/generation) informó una cuota renovable del 27 % y nuclear del 68,1 % en la generación francesa de 2025. Las tres decisiones de esta muestra concuerdan con esas fuentes oficiales. La captura enseña nombres y extractos, pero no acredita por sí sola URL, fecha, identidad del documento ni correspondencia exacta de cada cita; abrir `Verificación con fuentes` y revisar los enlaces y fragmentos de cada validador antes de dar por cerrada la trazabilidad.

**Confirmación posterior del operador:** la verificación con fuentes de esta orden se ha validado. Se registra como comprobación manual comunicada por el operador, sin copia de los enlaces o fragmentos de la interfaz en este documento. La abstención de un validador por falta de contextos citables sigue siendo un dato de cobertura de esta ejecución; la aceptación del corpus y las pruebas de seguridad restantes se evalúan por separado.

**Conflicto de métodos confirmado en la expresión comunicada por el operador:** la regla de Cloudflare coincide con cualquier `PUT` a `/backend` y sus subrutas, incluidos `/backend/admin/llm/components/{component}` y `/backend/admin/llm/validators/{validator_id}`. Gateway declara esos métodos y la GUI los usa para aplicar cambios de configuración LLM. Si la regla está habilitada con acción `Block`, esas actualizaciones se bloquearán en Cloudflare. Confirmar acción, estado y posibles excepciones en Cloudflare; ajustar la política para permitir solo los `PUT` administrativos necesarios con mTLS, JWT y rol antes de dar la consola LLM por operativa. Las peticiones anteriores sin certificado no verifican el efecto productivo de esta regla.

Con el lock en el estado acordado y un certificado temporal autorizado, comprobar `https://assermetry.com/gui/`, recursos, login/logout, issuer OIDC canónico, Gateway con/sin JWT, ausencia de Swagger/OpenAPI público y aislamiento de rutas administrativas. Ejecutar una orden LIGHT desde la GUI; comprobar que BLOCKCHAIN no se ofrece o se rechaza para nuevas órdenes, y que la respuesta final tiene fuentes/citas trazables. Verificar también desde otra red. El acceso directo por `port-forward` solo ayuda al diagnóstico: no prueba Cloudflare, Traefik ni mTLS.

**[VM-KIND]** Ejecutar una campaña publicada LIGHT sobre el corpus oficial con credenciales de prueba, cuota y ventana autorizadas, siguiendo [evaluation.md](../tests/evaluation.md); `--publish` consume proveedores. El runner documentado no implementa por sí mismo un certificado cliente mTLS, por lo que **no** usar `--no-verify-tls` como atajo de producción ni afirmar que una ejecución por túnel equivale a prueba del borde. Preparar un acceso de prueba que preserve TLS/mTLS o completar esa capacidad del runner antes de acreditar el E2E por el borde. Guardar SHA, imagen, hashes de casos, configuración de validadores, informe y errores sin secretos.

Para afirmar que un modo supera al otro, ejecutar campañas frías y emparejadas en una revisión/configuración comparable, una por modo, y usar `evaluation.pipeline.compare_modes` según [el plan del motor](../architecture/evidence-retrieval-engine-plan.md#2026-10-28--subfase-4a-comparador-de-campañas). Fijar modelo, temperatura, versión de configuración y gold; comparar cobertura de fuentes citables, exactitud, rechazos/abstenciones, `freshness_status`, p50/p95, llamadas y coste. Las campañas locales del 31-10 y 01-11 son evidencia de una regresión observada, no una comparación causal cerrada. Con el ConfigMap actual `provider_extract` seguirá a cero; evaluarlo requiere un cambio versionado separado.

**GO para despliegue controlado:** SHA limpio y artefactos correctos, backup MongoDB externo íntegro, snapshot del CX33 apagado disponible, actualización del host validada, acceso SSH solo por clave, firewall/K3s comprobados, migración aceptada con recuperación, CI autorizada, rollouts verdes, SMART y OFF observados en todos los pods pertinentes, borde y LIGHT funcionales. **NO GO para sacar v0.0.13 de Deploying o publicarla:** P1 sin resolver o sin aplazamiento formal, corpus no homologado, veredictos/fuentes no aceptables o pruebas requeridas en [detalle de v0.0.13](../releases/v0.0.13.md) no acreditadas.

### 7. Fallo y reversión

Si falla antes de `skaffold deploy`, conservar el estado y diagnosticar la realineación/gate; no relanzar a ciegas. Si falla después, identificar qué cambió (MongoDB, imágenes, modo, frontend, ingress, Keycloak) antes de revertir. El job `rollback` no basta para restaurar todo el cambio y debe verificarse su acceso al clúster. Cualquier cambio entre SMART y DIRECT o de imágenes debe hacerse con un commit/configuración versionados y el pipeline protegido, salvo recuperación excepcional autorizada; **no** recuperar colecciones antiguas sobre una aplicación nueva sin comprobar compatibilidad. Mantener el lock si el borde queda inconsistente y registrar el estado final de mTLS/Cloudflare.

Volver al tag/commit anterior y restaurar **solo** MongoDB permite recuperar código, manifiestos y esa base si también existen imágenes reconstruibles, Secrets y configuración compatibles. **No reconstruye por sí solo todo el sistema**: Keycloak usa otra base PostgreSQL con PVC, Kafka/IPFS y otros componentes tienen estado propio; certificados, credenciales, reglas Cloudflare, configuración externa y contenido de otros PVC tampoco están en Git ni en este archivo. Para reconstrucción completa hacen falta inventario y copias de esos estados, versiones de imágenes fijadas y un restore ensayado en un clúster aislado. Para un rollback de esta release, conservar el mismo corte temporal entre código y datos y validar los contratos entre servicios antes de abrir el tráfico.

Solo después de validar Hetzner y cumplir la puerta de salida de Deploying en [detalle de v0.0.13](../releases/v0.0.13.md): actualizar la evidencia de [issues.md](../issues.md), reconciliar `postTFM` con los commits exclusivos de `origin/main`, promover mediante PR/MR a `main` en ambos remotos y crear la etiqueta conforme a [gitlab-github-release-workflow.md](gitlab-github-release-workflow.md#6-release). El alcance documental está cerrado, pero no se etiqueta un commit de trabajo por el mero hecho de terminar el pipeline.
