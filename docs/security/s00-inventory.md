# S00 — Inventario de entornos y confianza

**Estado:** parcial, iniciado el 04-11-2026. Lectura de repositorio, kind y K3s de preproducción; sin cambios de clúster ni consultas a GitLab o Cloudflare. S00 no queda cerrado con esta fotografía.

## Alcance y procedencia

| Entorno | Función real | Fuente disponible | Estado de comprobación |
| --- | --- | --- | --- |
| VM `kind-trust-news` | Desarrollo y pruebas locales | `kubectl` de solo lectura, `kind get clusters`, checkout | Parcialmente observado el 04-11-2026 |
| Hetzner/K3s | Preproducción | Lecturas `kubectl`, listeners y firewall local, CI, manifiestos y runbooks | Parcialmente observado el 04-11-2026; borde y proveedor pendientes |
| Producción | No existe | Declaración del operador | Sin despliegue ni aceptación productiva |

Los perfiles `traefik-prod`, `infra-prod` y `apis-frontend-prod` y los overlays `prod` son nombres técnicos existentes para Hetzner; no convierten ese entorno en producción. La rama de trabajo es `postTFM` y el SHA del **checkout**, no necesariamente de ningún clúster, es `15fc0d511329c38d7ff8efae09fb0d149d01fa17`. En el árbol de trabajo ya figuraban `version.md` eliminado y `docs/version.md` sin seguimiento antes de esta tarea. El render local está fijado más abajo; queda pendiente vincularlo al SHA e imágenes efectivas de preproducción.

El render local del perfil `apis-frontend-prod` para ese checkout se generó el 04-11-2026 y tiene SHA256 `abb976cfa542edb41de0667ea3e106e129c43361571076c650ef55c195687275` (4.046 líneas). Se conserva temporalmente fuera del repositorio en `/tmp/s00-apis-frontend-preprod-render.yaml`. Es una fotografía reproducible del checkout local; no demuestra que coincida con el render o las imágenes de preproducción ya desplegadas.

## Kind: observación local

Consultas de solo lectura realizadas el 04-11-2026, aproximadamente a las 19:19–19:21 CET. Contexto `kind-trust-news`, API local `127.0.0.1:38521`, clúster `trust-news` con un control plane y dos workers, todos con kubelet v1.29.2. `kind-config.yaml` declara mapeos de puertos 80 y 443 del nodo control plane a la VM; esto no demuestra exposición desde otras redes.

| Componente o control | Estado observado |
| --- | --- |
| Evidence Search | `EVIDENCE_EXTRACTION_MODE=SMART`; Deployment 2/2 |
| Blockchain | `apis/blockchain-mode`: `BLOCKCHAIN_ENABLED=false`; `news-chain` y los tres StatefulSets Geth con 0 réplicas deseadas |
| APIs y frontend principales | Admin, Gateway, Generate Assertions, News Handler, Source Router, tres validadores y frontend con réplicas listas según `kubectl get deployments` |
| Datos y mensajería | MongoDB, PostgreSQL de Keycloak, Kafka e IPFS con 1/1; los Services consultados son `ClusterIP` |
| Entrada | Ingress de Gateway, frontend y Keycloak con host `localhost`; Traefik `LoadBalancer` en 80/443 |
| Segmentación | `kubectl get networkpolicy -A` no devolvió objetos; no demuestra por sí solo el aislamiento real del CNI |

Identificadores de imagen **observados en kind**, útiles para comparar una prueba posterior: Evidence Search `sha256:87616d54482d2e3f644ce3f1bf7efb382a2d1c8191eae2e3d9da1c41ecf5c02c` (ambas réplicas), Gateway `sha256:f388464e1435e7e081d690d411a870cad57d0ed3485127d2e8616faf9b77001f`, News Handler `sha256:127ba2c61bc02b541b9de583a43b125e715eb3b80db04031e82982eecfe4f169`, MongoDB `sha256:4be76f674fc4b27859816811b8baa3c51830eb1dbf4ca81a51e26b79edd662ef` y Kafka `sha256:620734d9fc0bb1f9886932e5baf33806074469f40e3fe246a3fdbb59309535fa`. Los identificadores no prueban qué SHA de Git construyó esas imágenes.

## Preproducción: hechos del checkout y comprobaciones pendientes

| Área | Declarado en el checkout | Falta observar en Hetzner o proveedor |
| --- | --- | --- |
| Pipeline | `.gitlab-ci.yml` usa `HETZNER_IP`, `HETZNER_USER`, `HETZNER_SSH_KEY_B64` y `KUBECONFIG_DATA`; túnel SSH al API K3s | Variables disponibles y protegidas, ámbitos, permisos de runner y credencial K3s, sin publicar valores |
| Confianza de despliegue | La CI obtiene host key con `ssh-keyscan` y usa `--insecure-skip-tls-verify=true`; rollback carga kubeconfig por una ruta separada | Clave del host verificada por canal independiente, CA y nombre TLS de K3s, RBAC efectivo; S01 debe cerrar las rutas |
| Perfil y modo | Valor por defecto `PROFILE=apis-frontend-prod`, `BLOCKCHAIN_ENABLED=OFF`; guías describen SMART | SHA/digests desplegados, render, ConfigMaps, variables de cada pod y réplicas efectivas |
| Borde y puertos | Runbooks describen Cloudflare, mTLS, SSH 2222 y API K3s mediante túnel | Reglas/eventos Cloudflare, firewall Hetzner IPv4/IPv6, listeners reales y prueba de origen directo desde fuera |
| Datos y secretos | Manifiestos declaran MongoDB, Keycloak/PostgreSQL, Kafka e IPFS | Inventario de nombres, propietarios, ubicación y rotación de secretos, sin leer ni registrar sus valores; datos y copias reales |
| Flujos de red | Services y manifiestos muestran componentes, sin `NetworkPolicy` versionadas | Matriz origen→destino/puerto por perfil; egress externo legítimo, DNS, probes, observabilidad y operaciones; enforcement del CNI |

La documentación histórica llama «producción» a Hetzner. A partir de este inventario se interpreta como preproducción; no se reescriben observaciones históricas como si fueran resultados nuevos.

La consola de GitLab observada el 04-11-2026 confirma que existen las cuatro variables requeridas por la CI: `HETZNER_IP`, `HETZNER_SSH_KEY_B64`, `HETZNER_USER` y `KUBECONFIG_DATA`. Todas están marcadas como **Protected**, **Masked** y **Hidden**. La edición de `HETZNER_IP` confirma tipo Variable, ámbito de entorno `All (default)`, referencia de variables desactivada y protección activada. No se consultó contenido. Esto evita su entrega a ramas o etiquetas no protegidas, pero no las separa por entorno entre pipelines protegidos. Sigue pendiente identificar quién puede ejecutar esos pipelines y revisar el RBAC del kubeconfig sin revelar su material.

Las ramas `main` y `postTFM` están protegidas y, tras el cambio observado el 04-11-2026, ambas permiten push y merge únicamente a Maintainers; force push sigue desactivado. Esto elimina el bloqueo inicial por Developers con capacidad de modificar `postTFM`. Las variables conservan ámbito `All (default)`, por lo que todavía falta asociar las credenciales de preproducción a un entorno protegido y limitar quién puede ejecutar sus jobs.

## Hetzner: observación de preproducción

Consultas de solo lectura realizadas por el operador el 04-11-2026 desde la sesión abierta del host `trust-news-prod`. Contexto K3s `default`. El nodo único de control está `Ready`, ejecuta `v1.34.5+k3s1` sobre Ubuntu 24.04.5 LTS. No se ha inspeccionado kubeconfig ni información que revele credenciales.

| Componente o control | Estado observado |
| --- | --- |
| Perfil funcional | `BLOCKCHAIN_ENABLED=false`; `EVIDENCE_EXTRACTION_MODE=SMART` |
| Cargas | Evidence Search 2/2; APIs, frontend, MongoDB, Keycloak/PostgreSQL, Kafka e IPFS listos; Grafana, Loki, Kafdrop y Mongo Express también están desplegados y listos |
| Blockchain | `news-chain` y los tres StatefulSets de Geth con 0 réplicas deseadas |
| Entrada Kubernetes | Ingress de Gateway, frontend y Keycloak para `assermetry.com`, clase Traefik |
| Servicios | Todos los servicios de aplicación, datos, observabilidad y administración son `ClusterIP`; Traefik es el único `LoadBalancer`, con NodePorts para HTTP/HTTPS |
| Segmentación | No hay recursos `NetworkPolicy` declarados |
| Listeners del host | SSH escucha en 2222 para IPv4/IPv6; K3s escucha en 6443, 10250 y 32694 en interfaces no limitadas a loopback. También existen listeners locales de control y resolución DNS |
| Firewall local | UFW está activo: entrada por defecto denegada y regla explícita que permite 2222/TCP desde cualquier origen IPv4/IPv6. Las cadenas nftables efectivas muestran el mismo modelo y DNAT de 80/443 hacia Traefik |
| Permisos de la sesión examinada | `kubectl auth can-i '*' '*' --all-namespaces` devuelve `yes`; es una credencial administrativa global del host, no la credencial de CI |
| Identidad SSH | Host keys RSA, ECDSA y ED25519 declaradas por `sshd`; huella ED25519 SHA256 `jIPqAJXD3jrK0JYE0UR75ATTMpwLFHve9cQs93UzsYY` observada desde el host y repetida por el operador dentro de una sesión SSH. El operador acepta continuar con la procedencia TOFU; queda como riesgo residual y no como contraste independiente |
| Firewall de proveedor | Firewall Hetzner aplicado a un recurso: TCP/2222 desde cualquier IPv4/IPv6, ICMP desde cualquier IPv4/IPv6 y TCP/443 desde rangos Cloudflare mostrados en la consola; salida sin restricciones declaradas |
| Cloudflare | Consola muestra cinco reglas personalizadas: maintenance lock, mTLS administrativo de Keycloak, mTLS temporal con gate de rutas, bloqueo de recursos no públicos y bloqueo de métodos backend inesperados |
| Política SSH efectiva | Puerto 2222, `PermitRootLogin no`, autenticación por clave pública obligatoria, contraseña y teclado interactivo desactivados |
| Certificado API K3s | Sujeto `kube-apiserver`, válido del 28-03-2026 al 28-03-2027; SAN incluye `localhost`, `trust-news-prod`, `127.0.0.1`, direcciones del host y nombres internos Kubernetes |
| CA API K3s | CA autocertificada `k3s-server-ca@1774687052`, válida del 28-03-2026 al 25-03-2036 |

La configuración local del firewall es evidencia de filtrado previsto para 6443/10250/32694, pero no acredita el firewall de Hetzner Cloud ni la conectividad efectiva desde Internet. SSH continúa expuesto a cualquier origen permitido por el proveedor; limitar sus orígenes se tratará como decisión de endurecimiento de S01/S04 tras confirmar el acceso operativo requerido. La ausencia de `NetworkPolicy` es una entrada para S04, no una demostración de comunicación permitida o denegada entre pods.

La captura de Hetzner aporta que 2222 está permitido por el firewall del proveedor desde cualquier dirección y que 443 se limita a los rangos Cloudflare visibles. No se observa una regla para 80, 6443, 10250 o 32694. Esta interfaz no sustituye una prueba desde Internet ni garantiza que la lista de rangos Cloudflare esté actualizada. Las capturas de Cloudflare muestran nombres y resúmenes de reglas, con partes de las expresiones truncadas: hay que revisar sus expresiones completas, acción, orden y eventos antes de acreditar el borde. La credencial administrativa de la sesión no puede utilizarse como prueba de mínimo privilegio de la CI; S01 deberá crear o verificar un principal separado y limitado.

Las expresiones completas aportadas para las reglas 2–5 muestran: mTLS de administración Keycloak para `/auth/admin` y el realm `master`; mTLS temporal y una allowlist de rutas `/gui/`, `/backend` y `/auth`; bloqueo de documentación, OpenAPI y rutas `.git`; y denegación de métodos backend fuera de `GET`, `HEAD`, `POST`, `OPTIONS` y `PUT`. La regla de maintenance lock coincide con todo el host `assermetry.com`. Falta registrar para cada regla la acción, estado, fase y eventos: el contenido de la expresión no acredita que el motor la esté aplicando.

La política SSH efectiva se consultó para la conexión actual de `sysadmin` mediante `sshd -T -C`: `permitrootlogin no`, `pubkeyauthentication yes`, `passwordauthentication no`, `kbdinteractiveauthentication no` y `authenticationmethods publickey`; `authorizedkeysfile` usa `.ssh/authorized_keys` y `.ssh/authorized_keys2`. El operador también confirmó desde su sesión SSH que `sshd -T` declara claves RSA, ECDSA y ED25519 y obtuvo la clave pública ED25519; su huella es `SHA256:jIPqAJXD3jrK0JYE0UR75ATTMpwLFHve9cQs93UzsYY`, igual a la previamente registrada. Esta coincidencia no es contraste independiente. El 07-11-2026 el operador decide aceptar ese riesgo TOFU para continuar; por tanto, la huella se fijará explícitamente en CI, pero su procedencia no se eleva a verificada fuera de banda.

El operador informa que generó una clave SSH separada para GitLab CI y alterna su presencia en `~/.ssh/authorized_keys` con `toggle_deploy_key.sh` antes y después del despliegue. El script compartido identifica la entrada por el comentario `cforc@Home`, añade la clave pública al archivo o elimina las líneas con ese comentario y cambia de modo según la encuentre. Es evidencia descriptiva aportada por el operador, no verificación del estado actual del archivo ni de las variables de GitLab. La lógica es una alternancia manual basada en comentario: una ejecución repetida invierte el estado, puede afectar líneas con el mismo comentario y no garantiza retirada si la ruta de despliegue falla antes del segundo paso. El script tampoco aparece integrado en el `.gitlab-ci.yml` del checkout revisado; hay que verificar qué clave contiene la variable CI sin revelar su valor y cómo se orquesta la habilitación/retirada. No se registraron claves públicas completas ni privadas.

En una comprobación posterior, el operador ejecutó el chequeo de solo lectura por comentario y obtuvo `CI_KEY_ABSENT` para `~/.ssh/authorized_keys`. Esto indica que no hay línea con el comentario `cforc@Home` en ese archivo en el momento de la consulta; no verifica la presencia/ausencia de la misma clave con otro comentario, `authorized_keys2` ni el valor de GitLab CI.

El operador comparó la huella de la clave pública embebida en `toggle_deploy_key.sh` con `id_rsa_hetzner_deploy.pub` en Windows; ambas dieron `SHA256:RchgGDL94h8uWJuWwQTPdZrh8hwVwusU+NQ2YH9pdnY` (RSA 4096). Esto confirma que esas dos copias públicas coinciden. En esa comprobación aún faltaba derivar la clave pública desde el archivo privado correspondiente; la verificación posterior se registra a continuación. Sigue sin verificarse qué valor privado está almacenado en GitLab CI.

Después, el operador derivó la clave pública desde `id_rsa_hetzner_deploy` con `ssh-keygen -y` y obtuvo la misma huella `SHA256:RchgGDL94h8uWJuWwQTPdZrh8hwVwusU+NQ2YH9pdnY`; eliminó el archivo público temporal. Queda confirmado localmente el par privado/público y su correspondencia con la clave pública del script. Sigue sin verificarse que la variable oculta de GitLab contenga ese privado.

El operador confirma que la variable `HETZNER_SSH_KEY_B64` en GitLab está marcada **Protected**, **Masked** y **Hidden**, con ámbito `All (default)`. Esto concuerda con la observación del 04-11-2026: el secreto queda disponible en todos los entornos que satisfagan la condición Protected, no aislado a preproducción. Sigue sin verificarse que contenga el privado del par cuya pública tiene huella `SHA256:RchgGDL94h8uWJuWwQTPdZrh8hwVwusU+NQ2YH9pdnY`, sin revelar su valor.

La captura de la tabla confirma que hay cuatro **Project variables**: `HETZNER_IP`, `HETZNER_SSH_KEY_B64`, `HETZNER_USER` y `KUBECONFIG_DATA`. Todas muestran **Protected**, **Masked**, **Hidden** y `All (default)`. Se confirma así que son variables de proyecto y pueden usar ámbito de entorno en el plan Free; el ámbito global sigue exponiendo cada variable a todos los jobs elegibles de ramas protegidas.

Para preparar ese control, `.gitlab-ci.yml` recibió una configuración parametrizada `DEPLOY_ENVIRONMENT` (valor por defecto `prod`) en `check_phase6_origin_tls`, `deploy`, `bootstrap_mongodb` y `rollback`, los jobs que usan credenciales para SSH/Kubernetes. Es un cambio local sin validar contra el linter de GitLab ni activar CI. Tras revisar el pipeline, los cuatro secretos de proyecto podrán acotarse a ese ámbito; no cambiar el ámbito mientras la configuración no esté incorporada y validada.

La modificación se registró en el commit local `49c270b` de `postTFM`, con solo `.gitlab-ci.yml`; el árbol conserva cambios previos ajenos a este commit. No se publicó: el push dispararía `check_phase6_origin_tls`, que en la versión remota aún obtiene confianza SSH mediante `ssh-keyscan`, omite validación TLS y lee la clave privada del Secret TLS de origen. Integrar y revisar primero S01 para evitar esa ejecución insegura.

La captura aportada de Settings > CI/CD muestra General pipelines, Auto DevOps, Runners, Artifacts, Variables, Pipeline trigger tokens, Deploy freezes, Job token permissions y Secure files; no muestra una sección Protected environments. Esto deja la ubicación/función sin confirmar, no demuestra que no existan entornos protegidos. Se continúa la inspección en Deploy > Environments.

La captura posterior del menú Deploy muestra Releases, Feature flags, Package registry, Container registry, Model registry y Pages, sin opción Environments. La navegación sigue inconclusa y no acredita ausencia de entornos; se inspeccionará el menú Operate.

La captura de Operate > Environments confirma un entorno activo llamado `prod`, con un despliegue marcado Success/Latest Deployed. En el proceso actual, `prod` es la etiqueta histórica que el operador usa para el despliegue Hetzner de preproducción; se tratarán `prod` y `preprod` como alias de nombre para ese mismo entorno, sin inferir que exista producción separada. La pantalla no muestra si el entorno está protegido ni quién puede desplegar; esos permisos siguen pendientes.

El formulario Edit environment de `prod` muestra nombre no editable, descripción y URL externa vacías, y selector GitLab agent; no contiene controles de protección. Settings > CI/CD tampoco mostró sección Protected environments. El operador confirma que el plan del proyecto es **Free**. Según la [documentación de GitLab](https://docs.gitlab.com/ci/environments/protected_environments/), los entornos protegidos requieren Premium o Ultimate y se gestionan desde Settings > CI/CD. Por tanto, esta función no está disponible en el plan actual. No se guardaron cambios en el entorno.

Desde Windows, el operador intentó una conexión nueva a `135.181.80.57:2222` con `PubkeyAuthentication=no` y `PreferredAuthentications=publickey`; el servidor respondió `Permission denied (publickey)`. Esto confirma el rechazo de ese intento sin autenticación por clave y concuerda con la política efectiva de `sshd`; no valida por sí solo la identidad del host ni prueba otras rutas de autenticación.

En Windows, `ssh-keygen -F "[135.181.80.57]:2222" -f "%USERPROFILE%\.ssh\known_hosts"` encontró entradas ED25519 (línea 8), RSA (línea 9) y ECDSA (línea 10). El operador indicó que verificó la conexión aceptando la clave que SSH mostró al conectar. Por tanto, la entrada procede de confianza TOFU y no de una comparación por canal independiente; la coincidencia actual de huella no cierra el control de identidad. No se alteró `known_hosts`.

El certificado de serving del API K3s tiene huella SHA256 `0F:B3:2A:FF:C5:02:E4:35:51:AE:16:BE:E6:CC:76:2D:35:33:87:0F:03:43:41:0E:BE:66:B0:88:08:B9:81:3F`. La CA tiene huella SHA256 `FC:5F:8B:66:9F:79:E7:55:5B:6F:C8:77:EB:D7:BE:7D:4C:0C:2F:8E:83:6F:00:05:36:D5:C7:E5:73:27:E7:79`. El SAN contiene `127.0.0.1`, por lo que el endpoint del túnel `https://127.0.0.1:6443` puede preservar validación de nombre si el kubeconfig usa la CA real. Falta contrastar ambas huellas por un canal independiente y comprobar el kubeconfig de CI sin revelar su contenido.

El 07-11-2026 el operador volvió a calcular desde su sesión SSH la huella de `/var/lib/rancher/k3s/server/tls/server-ca.crt`; OpenSSL devolvió `FC:5F:8B:66:9F:79:E7:55:5B:6F:C8:77:EB:D7:BE:7D:4C:0C:2F:8E:83:6F:00:05:36:D5:C7:E5:73:27:E7:79`, sujeto `CN = k3s-server-ca@1774687052`. Coincide con la observación previa. Esta repetición confirma consistencia del archivo visto por SSH, pero no es un canal independiente; su confianza se apoya en verificar independientemente la identidad SSH del servidor.

El operador aportó el valor Base64 de la entrada ED25519 de `known_hosts` para `[135.181.80.57]:2222`. Al decodificarlo y calcular su huella con `ssh-keygen`, resultó `SHA256:jIPqAJXD3jrK0JYE0UR75ATTMpwLFHve9cQs93UzsYY`, coincidente con la clave TOFU previamente aceptada. Esto valida formato, host/puerto y huella del material aportado; no verifica la procedencia de forma independiente ni confirma que se haya guardado en GitLab. El valor no se replica en esta documentación.

La verificación local de cadena `openssl verify -CAfile server-ca.crt serving-kube-apiserver.crt` terminó en `OK`. Esto demuestra que esos dos archivos presentes en el host son coherentes entre sí; no equivale a una comprobación desde una segunda fuente ni prueba una conexión TLS a través del túnel. El operador acepta seguir con esta procedencia como riesgo residual.

Pruebas de conectividad desde la red real de la VM de desarrollo el 04-11-2026: TCP/2222 respondió; TCP/443, TCP/6443, TCP/10250 y TCP/32694 quedaron cerrados o filtrados. Esto concuerda con el firewall local y de proveedor observados, y acredita una comprobación puntual desde ese origen, no una garantía universal. Una solicitud HTTPS `HEAD` sin certificado cliente a `https://assermetry.com/gui/` recibió `HTTP/2 403` con `server: cloudflare`. La respuesta acredita que el dominio pasa por Cloudflare y que el acceso sin certificado se bloquea; no atribuye el bloqueo a una regla concreta ni prueba GUI/OIDC con mTLS válido.

Los siguientes digests de aplicación se observaron en pods de preproducción el 04-11-2026: Admin `65554b59de6b`, Evidence Search `58c9f3b37b44` (dos réplicas), Gateway `bd25ff6e8c98`, Generate Assertions `7ffd6a4368d3`, IPFS API `07d3cb226a29`, News Handler `03629156e269`, Source Router `7a8791b275d2`, Validate Assertions `2de774f52480` (tres réplicas), frontend `10befa16e5b0` y Keycloak `f6c829b0d7dc`. Son identificadores de imagen de ejecución, no una prueba del SHA fuente que los construyó. MongoDB ejecuta el digest `4be76f674fc4`, Kafka `620734d9fc0b`, Traefik `21a3d8369637`, y los componentes de observabilidad también están fijados por digest en el informe de terminal aportado por el operador.

El inventario de Secrets de preproducción se consultó por nombre, tipo y fecha de creación, sin leer valores ni claves internas. Se observan referencias de aplicación en `apis` (API, Gateway, MongoDB, News Handler, búsqueda, Source Router y validadores), datos e identidad en `infra` (Keycloak, PostgreSQL, MongoDB y Mongo Express), credenciales de pull de GitLab por namespace, TLS de frontend/Keycloak/origen y material Ethereum/K3s. Las referencias de aplicación consultadas se recrearon el 02-11-2026; TLS, pull secrets, keystores y releases Helm tienen antigüedades distintas. Esta evidencia no permite inferir si cada secreto sigue vigente, quién es responsable, dónde se conserva la copia externa o cuándo se rotó por última vez.

## Contrato de salida de S00 para S01

S01 recibe configuración validada por entorno mediante [`prepare-kube-access.sh`](../../scripts/ci/prepare-kube-access.sh): destino SSH, puerto y usuario; host key fijada para el host/puerto; identidad SSH de CI; CA y nombre TLS esperado de K3s; endpoint del túnel; kubeconfig con privilegios revisados. Falla si falta cualquiera de esos contratos, si la host key no corresponde a host/puerto, si la CA no es un certificado o si el kubeconfig conserva la omisión TLS. La procedencia actual de host key y CA es la sesión SSH aceptada por el operador bajo TOFU; la fijación evita cambios silenciosos, pero no elimina el riesgo de origen aceptado. La misma interfaz debe servir a preflight, deploy, bootstrap, rollback y sincronización remota. Ningún valor secreto se versiona ni se imprime en evidencia.

La integración parametrizada sí está conectada localmente a `.gitlab-ci.yml`, aunque todavía no validada ni publicada. Falta ampliar las variables comunes a `prod/*`, preparar `KUBECONFIG_DATA` separado por perfil con RBAC revisado y validar el pipeline. La rama protegida limita push/merge a Maintainers. Según la [documentación de variables CI/CD](https://docs.gitlab.com/ci/variables/), las variables de proyecto admiten ámbito de entorno en Free, mientras que la limitación equivalente para variables de grupo requiere Premium/Ultimate. No acepta `ssh-keyscan` ni `insecure-skip-tls-verify` como alternativa.

**Estado para reanudar:** el inventario de kind y preproducción, firewall, borde, certificados, digests, referencias de Secrets y variables CI está documentado. La restricción de `postTFM` a Maintainers está aplicada. El proyecto usa GitLab Free; Protected Environments no está disponible. La clave CI local está separada de la interactiva; el par público/privado local coincide, pero el valor GitLab no se ha validado criptográficamente. El motor S01 y la asociación de entorno por perfil están integrados localmente, pendientes de revisión y validación; los jobs aún requieren la nueva configuración de variables y kubeconfigs.

**Siguiente paso al reanudar:** resolver el diseño RBAC por perfil antes de crear credenciales. No usar `ssh-keyscan`, `insecure-skip-tls-verify` ni el kubeconfig administrativo del host como alternativa.

**Pendiente para cerrar S00:** vincular SHA/render a las imágenes efectivas de preproducción, confirmar los permisos de la credencial K3s de CI, completar la matriz de flujos y asignar responsable operativo. También faltan acción/estado/eventos de Cloudflare y evidencia de acceso con mTLS válido. Si aparece un secreto activo expuesto o una ruta de administración directa, aplicar contención P0 y registrar el resultado antes de seguir.

## Recogida repetible de metadatos Kubernetes

[`collect_k8s_inventory.py`](../../scripts/security/collect_k8s_inventory.py) es un motor de solo lectura parametrizado por contexto y etiqueta de entorno. Selecciona únicamente nombres, estado, imágenes e identificadores, tipos de Service, hosts de Ingress y nombres/tipos de NetworkPolicy. No consulta Secrets, valores de ConfigMaps, variables de entorno, logs ni manifiestos completos. Su salida JSON incluye hora UTC y `complete`; si alguna consulta falla, deja `complete=false` y termina con código 3. No determina por sí solo SHA de despliegue, reglas de Cloudflare, firewall, RBAC de CI ni exposición externa.

Prueba local del 04-11-2026: `--context kind-trust-news --environment local-kind` terminó con `complete=true`, 3 nodos, 20 Deployments, 7 StatefulSets, 3 DaemonSets, 34 pods, 27 Services, 3 Ingresses y 0 NetworkPolicies. La salida temporal se guardó en `/tmp/s00-kind-inventory.json`; no se incorporó al repositorio. Un contexto inexistente devolvió `complete=false` y código 3.

### 1. Obtener la clave pública por un canal independiente

Entrar en la **consola del servidor dentro de Hetzner Console**, no mediante la conexión SSH que se está preparando. Identificar las claves de host que usa `sshd` y mostrar la pública y su huella; nunca copiar la clave privada:

```bash
sudo sshd -T | awk '$1 == "hostkey" { print $2 }'
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

Si `sshd` no usa esa ruta o no existe, tomar la ruta pública correspondiente a una `hostkey` activa. Conservar la línea completa que empieza por `ssh-ed25519` (o el algoritmo activo) y la huella SHA256 para compararla en la VM. La huella sola no basta para construir `known_hosts`.

### 2. Preparar la VM

Desde la raíz del checkout, definir **localmente**, sin pegar sus valores en Git ni en el chat, `HETZNER_HOST`, `HETZNER_USER` y `HETZNER_KEY` como en [quick start](../quick_start_hetzner.md#3-acceso-ssh-y-kubernetes). Comprobar que la clave privada ya existe; si `test` falla, detenerse. Crear un fichero nuevo de confianza para esta operación y pegar la línea pública obtenida de la consola cuando `read` la solicite:

```bash
test -r "$HETZNER_KEY" && echo 'Clave privada accesible'
install -d -m 700 "$HOME/.ssh"
export VERIFIED_KNOWN_HOSTS="$(mktemp "$HOME/.ssh/s00-known-hosts.XXXXXX")"
read -r -p 'Clave pública de host de Hetzner: ' HOST_PUBLIC_KEY
printf '[%s]:2222 %s\n' "$HETZNER_HOST" "$HOST_PUBLIC_KEY" > "$VERIFIED_KNOWN_HOSTS"
chmod 600 "$VERIFIED_KNOWN_HOSTS"
ssh-keygen -lf "$VERIFIED_KNOWN_HOSTS" -E sha256
```

Comparar la huella impresa en la VM con la de Hetzner Console. Deben coincidir exactamente. La entrada usa el host o IP exacto de `HETZNER_HOST` y el puerto SSH 2222; si se cambia cualquiera, hay que preparar una entrada correspondiente. No usar `ssh-keyscan` como fuente de confianza.

### 3. Verificar la conexión y el contexto K3s

```bash
ssh -T -o BatchMode=yes -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes -o UpdateHostKeys=no \
  -o UserKnownHostsFile="$VERIFIED_KNOWN_HOSTS" \
  -i "$HETZNER_KEY" -p 2222 "$HETZNER_USER@$HETZNER_HOST" \
  'command -v python3 && command -v kubectl && kubectl config current-context'
```

Esta lectura debe mostrar las rutas de Python y `kubectl` y el contexto K3s del host. Si SSH informa clave ausente/cambiada o el contexto no corresponde a Hetzner, detenerse. Esta comprobación SSH no sustituye la futura validación de CA/nombre TLS de S01.

### 4. Extraer y revisar el informe

El script viaja por `stdin`; no se instala en Hetzner ni usa el contexto kind de la VM. El contexto se toma del `kubectl` del host remoto. Guardar la salida en `/tmp`, fuera del repositorio:

```bash
umask 077
ssh -T -o BatchMode=yes -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes -o UpdateHostKeys=no \
  -o UserKnownHostsFile="$VERIFIED_KNOWN_HOSTS" \
  -i "$HETZNER_KEY" -p 2222 "$HETZNER_USER@$HETZNER_HOST" \
  'ctx=$(kubectl config current-context) && python3 - --context "$ctx" --environment hetzner-preprod' \
  < scripts/security/collect_k8s_inventory.py \
  > /tmp/s00-hetzner-inventory.json
python3 -m json.tool /tmp/s00-hetzner-inventory.json >/dev/null
python3 - <<'PY'
import json
with open('/tmp/s00-hetzner-inventory.json') as source:
    report = json.load(source)
print('context:', report['context'])
print('complete:', report['complete'])
print('counts:', {kind: len(items) for kind, items in report['resources'].items()})
print('errors:', report['errors'])
PY
```

`complete=true` y `errors=[]` indican que todas las lecturas solicitadas terminaron; no acreditan por sí solos la seguridad de preproducción. El JSON contiene metadatos de infraestructura, aunque no Secrets: compartirlo solo por el canal de trabajo autorizado y no subirlo a Git. Si falla algún paso, comunicar el mensaje de error **sin** pegar claves privadas, kubeconfig ni variables secretas. Esta recogida no modifica el clúster.

## Reanudación S01 — estado local al 07-11-2026

El motor parametrizado `scripts/ci/prepare-kube-access.sh` está conectado localmente al bloque común `.kube_access`, usado por `check_phase6_origin_tls`, `deploy` y `bootstrap_mongodb`; `rollback` también referencia ese bloque. La conexión crea los archivos de acceso en un directorio privado de trabajo, fija la identidad SSH mediante `known_hosts`, establece el túnel de Kubernetes y configura CA/nombre TLS; se retiraron del pipeline `ssh-keyscan` y `--insecure-skip-tls-verify=true`. `sync-remote-files.sh` ahora exige `known_hosts` y restringe SSH/SCP a autenticación por clave con comprobación estricta. El preflight dejó de leer el Secret `trustnews-origin-tls` y su `tls.key` en el runner; conserva la comprobación de referencia del TLSStore. La verificación de pareja certificado/clave ya no la hace CI y queda como control operativo pendiente.

El cambio de entorno GitLab `prod` quedó en el commit local `49c270b`; la integración S01 posterior permanece sin commit. Ambos son cambios locales, no publicados, y no se ha ejecutado pipeline. El alias `prod` corresponde al único Hetzner de preproducción; no hay producción separada.

### Contrato pendiente de variables del motor

Los siguientes valores deben estar disponibles en cada job que use `.kube_access`. Las variables comunes y la única variable `KUBECONFIG_DATA` compartida deben ser variables **de proyecto**, protegidas y con ámbito `prod/*`. Los secretos deben permanecer Masked/Hidden cuando GitLab acepte el formato. No introducir valores particulares del servidor en el motor.

| Variable GitLab | Tipo | Uso |
| --- | --- | --- |
| `HETZNER_IP` | Existente; protegida | Host SSH (mapeada a `DEPLOY_ACCESS_SSH_HOST`); ámbito objetivo `prod/*` |
| `HETZNER_USER` | Existente; protegida | Usuario SSH; ámbito objetivo `prod/*` |
| `HETZNER_SSH_KEY_B64` | Existente; secreto | Clave privada SSH codificada en Base64; ámbito objetivo `prod/*` |
| `HETZNER_SSH_KNOWN_HOSTS_B64` | Nueva; confianza | `known_hosts` fijado; existente con ámbito `prod`, Protected y Visible. Ampliar a `prod/*`. Huella coincide con TOFU aceptado, no verificada independientemente |
| `DEPLOY_ACCESS_SSH_PORT` | Nueva; configuración | `2222`; existente con ámbito `prod`, Protected y Visible. Ampliar a `prod/*` |
| `KUBECONFIG_DATA` | Existente; secreto; **cluster-admin aceptado para CI** | El operador decide conservar la credencial actual. Cree que la generó desde el mismo servidor, pero no recuerda el usuario/origen exacto. El kubeconfig de `sysadmin@trust-news-prod` respondió `yes` a `kubectl auth can-i '*' '*' --all-namespaces`; no se puede comparar el valor Hidden de GitLab. El operador acepta que los jobs que la reciban tendrán esos privilegios globales |
| `K3S_CA_B64` | Nueva; confianza | CA K3s; existente con ámbito `prod`, Protected y Visible. Ampliar a `prod/*`; procedencia SSH/TOFU aceptada como riesgo residual |
| `DEPLOY_ACCESS_KUBE_CONTEXT` | Nueva; configuración | `default`; existente con ámbito `prod`, Protected y Visible. Ampliar a `prod/*` |
| `DEPLOY_ACCESS_KUBE_CLUSTER` | Nueva; configuración | `default`; existente con ámbito `prod`, Protected y Visible. Ampliar a `prod/*` |
| `DEPLOY_ACCESS_KUBE_TLS_SERVER_NAME` | Nueva; configuración | `127.0.0.1`; existente con ámbito `prod`, Protected y Visible. Ampliar a `prod/*` |

El código no fija el puerto, contexto, nombre de clúster ni nombre TLS: se suministran en tiempo de ejecución. El operador confirma que creó las seis variables nuevas del motor como variables de proyecto con ámbito `prod`, Protected y Visible; deben ampliarse a `prod/*` para coincidir con los nombres `prod/<perfil>`. El operador decide conservar el `KUBECONFIG_DATA` actual como credencial única para todos los perfiles y acepta para CI los permisos globales asociados al kubeconfig administrativo de `sysadmin`; no se puede comparar el valor Hidden byte a byte. El entorno GitLab se forma localmente como `prod/$PROFILE`.

La captura de Settings > CI/CD del 07-11-2026 confirma 10 variables de proyecto con Environment scope `prod/*` y Protected. `HETZNER_IP`, `HETZNER_SSH_KEY_B64`, `HETZNER_USER` y `KUBECONFIG_DATA` también aparecen Masked y Hidden. Los valores no son visibles. El scope coincide con los entornos dinámicos previstos `prod/<perfil>`.

La inspección del checkout muestra que `apis-frontend-prod` administra recursos namespaced de `apis`, `frontend` e `infra`; `blockchain-prod` recursos namespaced de `blockchain`; `infra-prod` además aplica ClusterRole/ClusterRoleBinding para Fluent Bit; y `traefik-prod` instala por Helm en `kube-system`, con recursos que pueden incluir permisos y objetos cluster-scoped. Aislar variables por perfil reduce exposición entre jobs, pero no convierte un permiso amplio en RBAC mínimo. Antes de crear kubeconfigs, hay que separar la instalación/configuración cluster-scoped de las actualizaciones namespaced rutinarias (o aceptar y aislar una credencial elevada solo para ese job), y enumerar los verbos, recursos, namespaces y nombres a partir del render exacto. No conceder a un principal de CI permiso general para crear/editar Roles, ClusterRoles o sus bindings.

### Puerta antes de publicar o ejecutar

1. Registrar como riesgo aceptado que la host key y la CA se obtuvieron por SSH con procedencia TOFU, sin atribuirles verificación independiente.
2. El operador acepta conservar la credencial administrativa actual en `KUBECONFIG_DATA`; registrar que los jobs de despliegue tendrán permisos cluster-admin. No ampliar esta variable a jobs de build/test.
3. **Verificado por captura:** las 10 variables muestran `prod/*` y Protected; las cuatro credenciales secretas también Masked/Hidden. No se observan valores y no queda scope global en la tabla.
4. Conservar Protected y Masked/Hidden donde aplique. Revisar que los jobs usan `environment.name: prod/$PROFILE` y que únicamente los perfiles solicitados estén disponibles.
5. Revisar el diff completo antes de publicar. No lanzar preflight, deploy, bootstrap ni rollback hasta resolver RBAC y scopes; no ejecutar ni crear credenciales administrativas como atajo.

La revisión estática local del 07-11-2026 confirma que `PROFILE` ofrece solo los cuatro perfiles solicitados; los jobs de acceso usan `environment.name: "$DEPLOY_ENVIRONMENT/$PROFILE"` con prefijo `prod`, coherente con las variables `prod/*`; el motor valida entradas, host key fijada, CA y endpoint TLS; `sync-remote-files.sh` requiere SSH estricto. La última validación reportada en Pipeline Editor sobre `postTFM` muestra “Pipeline syntax is correct”; la simulación push no crea pipeline porque `workflow` acepta solo `CI_PIPELINE_SOURCE=web`. Esto no valida el origen `web`. El operador canceló el pipeline anterior `#3024194149` sin jobs iniciados. `build` y `deploy` están configurados manuales; `deploy` requiere el artefacto de `build`. El operador confirma MongoDB existente y realineado; el job postdeploy se cambió localmente a verificación no mutante (rollout y `realign --check`), retirando la inicialización y el `--apply`. No se ha ejecutado pipeline. El preflight sigue automático para API/infra y la verificación MongoDB se ejecuta después de `deploy` en infra. El preflight ya no lee ni valida el certificado/clave TLS del Secret `trustnews-origin-tls`; esa comprobación es un control operativo pendiente. Antes de publicar, revisar el diff completo de YAML y scripts.

### Diseño por perfiles solicitado el 07-11-2026

El operador necesita los perfiles `apis-frontend-prod`, `infra-prod`, `traefik-prod` y `blockchain-prod`, y decide usar la credencial administrativa Kubernetes actual para todos; acepta el privilegio cluster-admin en CI y será el único que lance despliegues. Los cuatro jobs privilegiados asignan localmente `environment.name: prod/$PROFILE`; la lista UI de `PROFILE` queda limitada a esos cuatro nombres. Plan de variables: host/SSH/known_hosts/CA/parámetros comunes y única `KUBECONFIG_DATA` con scope `prod/*`; las 10 variables relevantes deben quedar con ese scope y Protected, manteniendo Masked/Hidden en secretos.

Una credencial compartida debe cubrir la unión de las operaciones de los cuatro perfiles; que el operador sea el único en lanzar jobs limita quién inicia despliegues, pero no los permisos del token ni el impacto de un pipeline alterado. Además del apply de manifiestos namespaced, el perfil API/frontend ejecuta scripts que hacen `pods/exec` en `infra` (inicialización y cambios de índices de MongoDB) y `apis` (lectura/escritura de órdenes y escalado/reinicio de deployments y StatefulSets), y modifica un ConfigMap de modo blockchain. `infra-prod` incluye ClusterRole/ClusterRoleBinding de Fluent Bit; Traefik usa Helm en `kube-system` con recursos potencialmente cluster-scoped. Por tanto, la autorización no equivale a solo actualizar Deployments. Próximo paso: completar la matriz de verbos/recursos a partir de manifiestos y comandos, identificar qué permisos cluster-scoped se pueden preaprovisionar fuera del pipeline y luego definir la identidad común. No se ha cambiado GitLab ni el clúster.
