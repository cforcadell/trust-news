# Auditoría contrastada de seguridad — Codex

Fecha: **3 de noviembre de 2026**. Rama examinada: `postTFM`. Base: `3f1b154187cf9c10d3511227c014f43f2f94d901`, con cambios documentales locales previos. Entorno objetivo: Hetzner/K3s, perfil LIGHT/SMART. **Revisión estática y pruebas locales acotadas; no certificación de producción.**

## Alcance, fuentes y criterio de disputa

Las dos auditorías tienen el mismo valor inicial. Ninguna prevalece por autoría: cada afirmación se acepta, matiza o rechaza según evidencia del checkout y de `docs/`.

- **A — Auditoría aportada:** [copia íntegra del texto recibido](security_review_aportada.md), con referencias `EXT-*`, `INT-*` y `OPS-*`.
- **B — Revisión Copilot:** [security_review_copilot.md](security_review_copilot.md), trasladada desde `SECURITY-REVIEW.md` sin cambiar su contenido.
- **Evidencia complementaria:** [análisis de Hetzner ya existente](analisis-seguridad-hetzner.md), [pruebas externas del 02-11](../deploy/pentest-externo-assermetry-2026-11-02.md), [runbook productivo](../deploy/skaffold-server.md), [despliegue de v0.0.13](../deploy/main-posttfm-hetzner-smart-light.md), [cierre histórico de v0.0.12](../releases/v0.0.12.md), [incidencias](../issues.md) y [roadmap](../next_releases.md).
- **Código revisado:** Gateway y middleware, Admin, News Handler, generación, cliente/modelos de cuotas y descarga de Evidence Search; CI, Skaffold, ingress/Traefik, manifiestos de Kafka/MongoDB/Geth/servicios, Dockerfiles, copias/restauración y tests de seguridad relacionados.

No se ha consultado la configuración activa de Cloudflare, Hetzner, K3s, RBAC, Secrets ni las imágenes de los pods. Tampoco se han ejecutado ataques, migraciones, restauraciones o modificaciones contra producción. Las pruebas del 02-11 son evidencia documental de otra sesión, no pruebas nuevas de esta auditoría. No se ha realizado un escaneo completo de CVE ni una revisión exhaustiva de contratos Solidity, frontend o todos los consumidores Kafka.

**Estados:** confirmado en código/configuración; reproducido localmente con dobles; observado históricamente; pendiente de verificación operativa; condicionado a habilitar una función. Una ausencia en el repositorio no demuestra ausencia en el servidor.

**Gravedad y prioridad son distintas.** Alta describe impacto y condiciones de explotación; P0 bloquea el siguiente despliegue automatizado inseguro o exige contención inmediata si se confirma exposición; P1 bloquea abrir la beta; P2 es endurecimiento posterior o condicionado. No se asigna CVSS sin datos suficientes. Una cadena SSRF → Admin/Kafka puede tener impacto crítico; no se ha demostrado esa cadena desde Internet.

## Resultado de la confrontación

| Punto en disputa | Auditoría A | Auditoría B | Resolución independiente |
| --- | --- | --- | --- |
| Identidad del despliegue | OPS-01/02: alta | Hallazgo 1: crítica | Ambas identifican código real. **Alta/P0**, con impacto potencial sobre el clúster; «crítica explotable» no está acreditado. SSH y TLS son dos controles distintos. |
| SSH + API K3s | Propone fijar host y CA/nombre | Misma corrección | Aceptado. Un túnel SSH correctamente autenticado mitiga interceptación exterior del TLS interno, pero hoy el bootstrap de SSH tampoco fija identidad. Cloudflare no protege esta ruta. |
| Admin y red interna | INT-01/02: altas | Alta, exposición potencial | Aceptado como riesgo lateral. Admin es `ClusterIP`; no se ha identificado Ingress público propio. `ClusterIP` no autentica al llamante ni impide acceso entre pods. |
| SSRF | EXT-01: alta potencial | No la desarrolla | A aporta cobertura relevante. Hay validación de IP y redirecciones; falta ligar esa resolución a la conexión. No es «SSRF trivial a IP privada», tampoco está cerrado el rebinding. |
| Cuotas y coste | EXT-03/04: medias | No las desarrolla | **Se elevan a altas/P1** por defectos adicionales de LIGHT reproducidos localmente. Admin sí tiene `$inc`; eso no convierte todas las rutas en atómicas ni reserva presupuesto antes del gasto. |
| Kafka | INT-03: alta; remediación tardía | No lo desarrolla | Confirmado PLAINTEXT sin SASL/ACL en el manifiesto revisado. **Aislamiento y autenticación antes de beta**: diferir íntegramente a producción deja abierta la integridad del flujo LIGHT. |
| MongoDB 4.4 | INT-04: alta | No lo desarrolla | EOL confirmado, sin CVE explotable demostrado. Migración ensayada antes de beta con datos a conservar; nunca sustitución directa de imagen sobre el PVC. |
| Recuperación | OPS-03: media | Hallazgo 3: media | Ambas aciertan sobre cobertura incompleta. Existen checksum, permisos restrictivos y restauración con confirmación explícita; no prueban cifrado externo, consistencia ni recuperación integral. |
| Geth | Baja en LIGHT; alta si ON | Media | **Condicionado, alta al habilitarlo.** YAML declara RPC y News Chain a cero réplicas; comprobar también el resto de Geth y el estado efectivo. Una etiqueta universal «media» pierde este contexto. |
| Borde y mTLS | Arquitectura favorable; validar estado | Base favorable sin cierre operativo | Ambas parcialmente correctas. Hay pruebas históricas y un muestreo externo reciente, no solo planes; los `403` sin certificado no atribuyen regla ni validan JWT/roles o firewall del origen. |
| Métodos `PUT` LLM | Incompatibilidad detectada | No la desarrolla | Conflicto documental confirmado y descrito también en el informe del 02-11. Bloqueo productivo condicionado a acción/estado/excepciones; no demostrado mediante `PUT` autenticado. |
| Cabeceras de navegador | EXT-05 pendiente | No las desarrolla | Nginx no las declara. El 02-11 faltaba HSTS en las respuestas 302/403 muestreadas; sí se observaron framing/referrer en 403. Falta inspeccionar un 200 de GUI; no afirmar ausencia global. |
| Capacidades sin JWT | EXT-06: baja | No lo desarrolla | `/capabilities` devuelve únicamente el flag Blockchain. Se clasifica como información de arranque de bajo impacto, sin secreto demostrado; no obliga por sí sola a añadir autenticación ni bloquea beta. El mTLS de borde puede seguir aplicando. |
| Claves históricas | INT-07, sin acreditar uso productivo | Sin conclusión específica | Dos claves TLS privadas están versionadas; keystore Ethereum cifrado también. Uso activo y alcance desconocidos. No inferir fuga de Origin CA ni imprimir secretos. |
| Estado de v0.0.13 | «Continúa Deploying; sin validación completa» | Rama aún no lista para producción | La guía combina Deploying con despliegue comunicado. Releases/issues actuales indican **desplegada, aceptación pendiente**. No confundir pendiente de aceptación con no desplegada. |
| «0 críticas confirmadas desde Internet» | Conclusión explícita | Crítica en CI | No son medidas comparables: una cuenta explotación exterior demostrada y la otra impacto de configuración. No se certifica «cero vulnerabilidades» ni se acepta una crítica remota sin prueba. |

La discrepancia más importante de planificación: no resulta coherente abrir v0.0.14 dejando identidad de CI, SSRF, confianza administrativa y cuotas para v0.0.16. La nueva **v0.0.13b** adelanta ese cierre; el [plan de ejecución](../version.md) es la referencia de prioridades. Las auditorías originales quedan conservadas como fuentes, no como planes vigentes.

## Registro de hallazgos

### SEC-01 — Confianza de CI en SSH y K3s: alta, P0

**Evidencia:** [CI, líneas 43–53](../../.gitlab-ci.yml), con `ssh-keyscan`, túnel sin `StrictHostKeyChecking=yes` explícito y `kubectl config set-cluster ... --insecure-skip-tls-verify=true`. Corresponde a ISSUE-003/004, OPS-01/02 y B-1.

La adquisición de una clave por la misma red no verifica su identidad. Un adversario con capacidad de suplantar el host o intervenir esa ruta podría aprovechar el bootstrap. Desactivar TLS elimina otra autenticación del destino. No se ha demostrado interceptación ni exfiltración; los permisos reales del kubeconfig no se inspeccionaron.

**Cierre:** motor de acceso de despliegue parametrizado por entorno: host key obtenida por canal independiente, modo estricto y fallo si falta/cambia; CA real y nombre TLS válido para el endpoint del túnel, sin saltos inseguros. Rotación documentada. CA/nombre/host key incorrectos deben detener el pipeline **antes de leer Secrets, aplicar o migrar**. Repetir en todos los jobs que heredan `.kube_access`, incluido rollback; usar credenciales de despliegue con privilegios mínimos.

### SEC-02 — Resolución SSRF separada de conexión: alta, P1

**Evidencia:** [`_validate_import_url` y `fetch_public_url_text`](../../api/news-handler/main.py), líneas 2290–2404; [`_validate_fetch_url`, redirecciones y `_bounded_get`](../../api/evidence-search/app/document_fetcher.py), líneas 308–438. El primero resuelve con `socket.getaddrinfo` y luego `requests` usa el hostname; el segundo valida DNS y después `httpx` abre la URL. No se entrega al transporte el conjunto validado.

Ambos bloquean destinos privados resueltos inicialmente y revalidan redirecciones. Hay límites de bytes, reintentos y timeouts: no deben darse por ausentes. News Handler permite puertos no estándar; Evidence Search los restringe. News Handler desactiva `trust_env`; el cliente `httpx` mostrado no lo desactiva expresamente, por lo que la política de proxy ambiental también debe inventariarse.

**Escenario:** un dominio controlado cambia de respuesta entre validación y conexión. Una respuesta maliciosa podría alcanzar una red interna si la salida lo permite; no se ha probado rebinding contra Hetzner. La validación posterior de `resp.url` no revierte una petición ya enviada. El WAF entrante no controla ese destino saliente.

**Cierre:** un motor común de descarga con política configurable de destinos/puertos, resolución y conexión ligadas, verificación TLS y Host/SNI conservados, cada salto/reintento sometido a la misma política y presupuesto total. Bloqueo de loopback, link-local, metadatos, redes del clúster y API K8s desde estos descargadores, respetando sus dependencias internas legítimas. Probar IPv4/IPv6, DNS mixto, rebinding y redirecciones mediante infraestructura controlada; no usar servicios internos reales como blanco.

### SEC-03 — Servicios sensibles confían en identidad declarada: alta, P1

**Evidencia:** [Admin](../../api/admin/main.py), rutas de clientes 1280–1365 y PUT LLM 1112–1157, sin autenticación local; `updated_by` procede de `x-assermetry-admin-user`. [News Handler](../../api/news-handler/main.py), `/orders`, `/news`, eventos y consistencia usan `admin=True` por defecto en varias consultas. [Gateway](../../api/gateway/main.py) sí valida rol y deriva identidad/permisos para esas consultas públicas.

Un llamante con acceso interno puede intentar modificar cuotas/configuración, atribuir acciones a otro operador y consultar órdenes con privilegios administrativos. No hay evidencia de acceso directo público a Admin ni de que el cliente externo pueda imponer el `admin` que Gateway construye.

**Cierre:** motor compartido de identidad y autorización por servicio, audiencia, acción y recurso; autenticación verificable del llamante, delegación de usuario/organización protegida y denegación por defecto. La asociación usuario/cliente OIDC → organización debe ser inmutable para el solicitante y resolverse en servidor; la clave de propietario actual basada en `sub` no implementa por sí sola esa asociación. Eliminar elevación implícita, rechazar cabeceras de identidad sin autenticar y separar permisos de worker, Gateway y operador. Un token de servicio válido no debe dar acceso global a todos los tenants. Probar llamadas directas negativas, rol insuficiente, identidad alterada y reintento/replay según el mecanismo elegido.

### SEC-04 — Segmentación no declarada: alta, P1

**Evidencia:** búsqueda de `NetworkPolicy` en `k8s/` sin recursos encontrados; servicios internos como [Admin](../../k8s/apis/admin/service.yaml), MongoDB y Kafka. No se deduce ausencia de políticas instaladas manualmente ni que un ServiceAccount tenga permisos sobre Secrets.

**Cierre:** inventariar los flujos reales de los perfiles y generar políticas desde una matriz declarativa. `default-deny` de ingreso/salida progresivo, DNS y dependencias explícitas; aislar Admin, bases, Kafka, Keycloak/PostgreSQL, IPFS, RPC y paneles. Incluir probes, observabilidad y operación. Los descargadores necesitan Internet público y tráfico interno concreto: bloquear todo RFC1918 indiscriminadamente rompería la aplicación.

El controlador de red debe aplicar las políticas; Kubernetes requiere un plugin compatible. Las NetworkPolicies estándar no constituyen una política de autorización por usuario ni una allowlist de FQDN. La política resultante necesita pruebas positivas y negativas dentro del clúster. [Documentación oficial de NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/).

### SEC-05 — Admisión y contabilidad de cuotas inconsistentes: alta, P1

**Evidencia:** [News Handler](../../api/news-handler/main.py), 1933–2049 y 936–968; [cliente compartido](../../api/common/utils/quotas_client.py), 7–20; [Admin](../../api/admin/main.py), 235–251, 757–821 y 1319–1351; [generación HTTP](../../api/generate-asertions/main.py), 650–692.

- `publishNew` comprueba y encola sin reserva atómica. El worker generador por Kafka llama al LLM sin una reserva propia por cliente en esa función; el chequeo posterior de News Handler para Blockchain ocurre después de generar y LIGHT retorna antes de ese chequeo.
- `publishWithAssertions` solo compara `blockchain_validation` si el modo es Blockchain. En LIGHT no comprueba ese límite ni `news_generation` antes de publicar las validaciones.
- Ese endpoint toma `cons_news` una vez, escribe `cons_news + 1` y después **`cons_news - 1`**. Desde cero se observan escrituras `1` y `-1`; no restaura el valor inicial. El modelo de cuotas admite enteros negativos.
- Admin usa `$inc` en `record_consumption`, pero no condiciona ese incremento al saldo ni deduplica ahí el evento. Otra ruta aplica `$set` con cifras leídas antes. Operaciones concurrentes y redelivery pueden perder o duplicar cobros. La facturación posterior no impide que el coste ya se haya producido.

**Prueba local:** función real `publish_with_assertions` y funciones de modo extraídas mediante AST, con modelos reales de solicitud/mensaje y constructor documental del repositorio; solo se simularon E/S de DB/Kafka. Cliente `Suspended`, ambos límites y consumos a cero, modo LIGHT y una aserción: retornó `ASSERTIONS_REQUESTED`, envió al productor simulado y solicitó escrituras `1` y `-1`. Esto demuestra decisiones de la función, **no el saldo final con consumidores concurrentes ni una explotación en producción**.

**Cierre:** motor transaccional de admisión/reserva/consumo/liberación por organización y operación, con presupuesto por tokens/coste/concurrencia además de número de órdenes. Clave idempotente común a HTTP, eventos y retries; gasto reservado antes de proveedores y validadores, compensaciones trazables, contadores no negativos. Definir qué consume cada modalidad sin mezclar generación y validación. Probar concurrencia, caída entre fases, redelivery y cuotas agotadas en LIGHT y Blockchain.

### SEC-06 — Estado administrativo del cliente no aplicado al admitir trabajo: alta, P1

**Evidencia:** el [modelo](../../api/common/models/quota_models.py) distingue `Active`, `Deactivated`, `Suspended` y fechas. [`fetch_client_quotas`](../../api/common/utils/quotas_client.py) devuelve el documento sin validar estado; las comprobaciones citadas en SEC-05 solo leen límites/consumos. La prueba aislada aceptó un cliente suspendido.

Desactivar el registro de cuotas no garantiza el cese de trabajo con un JWT todavía válido. No se afirma que desactivar un usuario en Keycloak sea la misma operación ni que todos los tokens emitidos se revoquen inmediatamente.

**Cierre:** incorporar estado/vigencia a la misma política de admisión y a la autorización de recursos que corresponda. Definir si una baja cancela trabajo pendiente o solo nuevas solicitudes; medir la latencia máxima de revocación, cachés y tokens. Ensayar baja/suspensión de organización, usuario y cliente OIDC sin confundir sus ciclos de vida.

### SEC-07 — Kafka sin identidad de productores/consumidores: alta, P1

**Evidencia:** [StatefulSet Kafka](../../k8s/infra/kafka/statefulset.yaml), listeners y mapa `PLAINTEXT`, creación automática de topics, sin configuración SASL/ACL revisada. [News Handler](../../api/news-handler/main.py) y [Admin](../../api/admin/main.py) aceptan eventos tipados: validación Pydantic de forma no equivale a procedencia autenticada.

Ya existe un [helper compartido de configuración Kafka](../../api/common/utils/kafka_contracts.py), `kafka_security_kwargs`, pero si se solicita SASL sin usuario/contraseña retorna `{}` y avisa de fallback a PLAINTEXT. La llamada local con `SASL_SSL` sin credenciales reprodujo ese resultado. Un broker que exige SASL seguirá rechazando al cliente; no se ha demostrado que este fallback permita eludirlo. Sí contradice una política que deba fallar al faltar configuración segura y puede pasar inadvertido mientras siga disponible el listener abierto.

Con conectividad al broker, un pod no autorizado podría intentar leer/publicar eventos que afectan resultados y consumo. Hay validaciones de esquema, orden y correlación; no se afirma que cualquier JSON permita cualquier modificación. Autenticar un servicio tampoco protege frente a ese mismo servicio comprometido: las ACL deben limitar topics/acciones.

**Cierre:** primero segmentación; después transporte autenticado y cifrado, identidades por servicio y ACL mínimas, inventario declarativo de topics, creación administrativa controlada. Extender el helper existente para rechazar credenciales/configuración incompletas en perfiles seguros, sin degradación silenciosa. Motor de aceptación de eventos por procedencia, operación esperada, correlación e idempotencia. Probar productor/consumidor ajeno, credenciales ausentes, topic prohibido, evento duplicado y evento válido de origen indebido. Incluir conectividad de Kafdrop y observabilidad según permisos.

### SEC-08 — MongoDB 4.4 fuera de ciclo de soporte: alta de mantenimiento, P1

**Evidencia:** [StatefulSet](../../k8s/infra/mongodb/statefulset.yaml) declara `mongo:4.4`; el [overlay productivo](../../k8s/infra/mongodb/overlays/prod/kustomization.yaml) incluye esa base sin sustituir imagen. MongoDB sitúa el EOL de 4.4 en **29-02-2024**. Esto acredita obsolescencia, no una CVE concreta explotable ni la imagen efectiva del pod. [Ciclo oficial de MongoDB](https://www.mongodb.com/legal/support-policy/lifecycles).

**Cierre:** destino con soporte vigente y parche fijado, compatibilidad de drivers y herramientas y ruta de migración soportada. Antes, SEC-09: copia protegida y restauración aislada. Ensayar migración, FCV cuando corresponda, índices, consultas, counts y vuelta atrás mediante restauración compatible; no asumir que una versión antigua puede abrir un volumen actualizado. Los scripts usan el cliente `mongo`, que también requiere revisión al cambiar imagen. Registrar duración y espacio necesario antes de la ventana.

### SEC-09 — Recuperación incompleta y no demostrada: alta para datos a conservar, P1

**Evidencia:** [backup](../../scripts/k8s/backup-mongodb.sh) usa `umask 077`, archivo temporal, `gzip -t` y SHA-256; [restore](../../scripts/k8s/restore-mongodb.sh) compara checksum y DB destino y requiere `--apply --replace-database`. [Rollback CI](../../.gitlab-ci.yml), 360–383, intenta `rollout undo` en `apis`; no restaura todas las configuraciones ni estados.

No se ve un flujo completo de cifrado externo y restauración de MongoDB + PostgreSQL/Keycloak + configuración/credenciales y demás estados. Un checksum detecta cambios respecto a su manifiesto, pero no autentica una copia si ambos son alterados. Un dump durante escrituras no demuestra por sí solo consistencia entre colecciones y servicios.

**Cierre:** motor de backup/restauración por inventario, consistencia definida, cifrado y custodia externa de claves, integridad verificable, retención y restauración en destino aislado. Login, counts, índices y coherencia de órdenes/configuración deben verificarse. Medir RPO/RTO; registrar qué cachés/eventos son reconstruibles. Probar rollback de artefactos/configuración/datos compatibles. **Nunca ensayar una restauración destructiva sobre los PVC activos.**

### SEC-10 — JWKS por petición y dependencia sin presupuesto específico: media, P1

**Evidencia:** [Gateway](../../api/gateway/main.py), 124–163, crea sesión y obtiene JWKS antes de decodificar cada token, incluso malformado. No hay caché ni timeout de autenticación explícito en esa función; eso no implica ausencia del timeout por defecto de aiohttp.

**Cierre:** motor de verificación con caché acotada por issuer/`kid`, TTL, refresh único concurrente, rotación y límite de recargas por claves desconocidas; timeout y concurrencia específicos. Firma/issuer/audiencia/presentador siguen siendo obligatorios, y un fallo de descarga nunca autoriza. Probar tokens inválidos masivos y rotación sin convertir un `kid` aleatorio en una nueva descarga por solicitud.

### SEC-11 — Endurecimiento de pods desigual: media, P2

**Evidencia:** [Source Router](../../k8s/apis/source-router/base/deployment.yaml) declara `runAsNonRoot` y `allowPrivilegeEscalation: false`; muchos otros manifiestos revisados no. Los [Dockerfiles de Admin](../../api/admin/Dockerfile) y [Gateway](../../api/gateway/Dockerfile) sí usan `USER appuser`: sería incorrecto afirmar que todos los contenedores son root. No aparecen declaraciones generales de `automountServiceAccountToken: false`, seccomp ni drop de capacidades en el árbol revisado.

**Cierre:** política declarativa por tipo de workload para no-root, capacidades mínimas, no escalada, seccomp, token de ServiceAccount solo cuando se necesita, RBAC mínimo y filesystem de solo lectura donde sea compatible. Validar render y procesos efectivos; no romper almacenamiento, initContainers o tareas operativas. Si la comprobación encuentra privilegios o acceso a Secrets innecesarios en un componente expuesto, elevar ese caso a P1.

### SEC-12 — Cadena de suministro sin fijación y escaneo completos: media, P2

**Evidencia:** [requirements de Gateway](../../api/gateway/requirements.txt) deja `aiohttp`/`python-jose` sin versión; [Admin](../../api/admin/requirements.txt) también varias dependencias. CI descarga `kubectl` desde `stable.txt`, usa `docker:cli` y descarga Skaffold sin checksum; Helm sí tiene SHA-256 verificado. Manifiestos incluyen tags flotantes; imágenes propias se resuelven al construir con Skaffold, por lo que hay que inspeccionar el render/artefactos y no equiparar cada nombre base a una imagen `latest` desplegada.

**Cierre:** motor reproducible de inventario/lock/SBOM y escaneo por artefacto/digest y perfil; verificar binarios descargados y hacer obligatorias las puertas aplicables. Elegir versiones soportadas, sin inventar CVE a partir de antigüedad. Vulnerabilidad crítica/alta aplicable descubierta en el candidato pasa a P0/P1 y bloquea cierre; completar imagen por imagen en la preparación productiva.

### SEC-13 — Material privado versionado y exposición local: media condicionada, P2; P0 si activo expuesto

**Evidencia:** `git grep -l` encuentra claves privadas en `k8s/infra/keycloak/overlays/local/tls.key` y `web_classic/certs/privkey.pem`. `git ls-files` incluye `k8s/blockchain/ethereum-keystores.yaml`, cifrado; su existencia no prueba que pueda descifrarse ni que esté activo. ISSUE-024 documenta una credencial en el lanzador local; no se reproduce aquí su valor.

**Cierre:** inventario de credenciales/certificados por entorno y propietario; comprobar uso y permisos por canal seguro. Revocar/rotar si sigue activo y expuesto, retirar material del flujo de construcción y evitar reintroducción con detección automática. Borrar un archivo no elimina su historial ni invalida una credencial. No reescribir historial como primera medida ni exigir rotación productiva de una clave demostrablemente solo local. Guardar evidencias sin secretos.

### SEC-14 — Borde: conflicto de métodos y estado efectivo pendiente: media funcional + verificación P0/P1

**Evidencia:** [runbook](../deploy/skaffold-server.md), §5.3, permite GET/HEAD/POST/OPTIONS bajo `/backend`; [Gateway](../../api/gateway/main.py), 273–291, declara PUT LLM. El [informe externo del 02-11](../deploy/pentest-externo-assermetry-2026-11-02.md) conserva la expresión comunicada y un borrador acotado. Su acción, habilitación y excepciones no se inspeccionaron aquí.

**Cierre:** motor/matriz de contratos de rutas y métodos que contraste API, frontend y reglas por entorno. Exceptuar únicamente PUT necesario, conservando mTLS administrativo, JWT y rol. Comprobar reglas activas/eventos, IPv4/IPv6, origen directo, 80/6443 y accesos operativos. Verificar respuestas positivas además de negativas. Mantener mTLS general en v0.0.13b; la transición sin ventana al gate de rutas corresponde a v0.0.14 tras superar esta versión. La revocación administrativa prevista en v0.0.14 debe seguir siendo puerta de esa apertura.

Origin CA autentica el servidor ante Cloudflare; no demuestra autenticación del proxy ante el origen. AOP añade certificado cliente; incluso su modalidad global no identifica por sí sola exclusivamente una zona. Evaluar autenticación específica de origen como defensa adicional, sin declarar un bypass confirmado por su ausencia. [Documentación oficial de AOP global](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/set-up/global/).

### SEC-15 — Cabeceras web sin política reproducible: media pendiente, P2

**Evidencia:** [Nginx](../../web_classic/nginx_k8s.conf) no configura CSP/HSTS/framing. El informe externo registró ausencia de HSTS en 302/403, pero framing/referrer en 403 de Cloudflare. Falta respuesta 200 autenticada de GUI y política efectiva del borde.

**Cierre:** política por aplicación/origen, verificar cabeceras finales en éxito/error, CSP compatible con OIDC y recursos de GUI y `frame-ancestors` según necesidad. Introducir CSP en modo informe si precisa ajuste; decidir HSTS/subdominios tras inventario. No activar preload o `includeSubDomains` sin validación. Evaluar el frontend como contenido no confiable de noticias/LLM; esta revisión no demuestra ausencia de XSS.

### SEC-16 — HTTP interno y distribución de confianza: media, P1 en canales de identidad; P2 general

**Evidencia:** [ConfigMap Gateway](../../k8s/apis/gateway/configmap.yaml) usa HTTP para JWKS y servicios internos. mTLS de usuario → Cloudflare no cifra estos saltos. Un pod ordinario no adquiere automáticamente capacidad de interceptar todos los flujos: el riesgo requiere observar o manipular esa red/ruta.

**Cierre:** transportar identidad, claves de verificación y operaciones administrativas por canales autenticados y protegidos, con validación de servidor y rotación. Proteger también Kafka al ejecutar SEC-07. Extender progresivamente a los demás flujos por sensibilidad; elegir TLS directo u otra solución justificada, sin imponer service mesh. NetworkPolicy limita conectividad y no cifra tráfico.

### SEC-17 — Contrato de claims obligatorios incompleto: media condicionada, P1

**Evidencia:** [Gateway](../../api/gateway/main.py), 144–163, fija RS256/issuer/audience y requiere `aud`; no exige expresamente presencia de `exp` ni `sub`. `get_computed_client_id`, 195–203, usa `unknown_sub` si falta `sub`; la ruta de validaciones por propietario sí rechaza `sub` vacío, otras no realizan esa comprobación local.

La prueba de la función de identidad devolvió `user_unknown_sub` para claims sin `sub`. Esto no acredita que Keycloak emita ese token ni que se pueda falsificar una firma. No se verificó dinámicamente el comportamiento de la versión productiva de python-jose ante claims ausentes: el entorno local no tiene esa dependencia.

**Cierre:** contrato único de identidad con claims obligatorios, tipos, vigencia y `sub` no vacío, antes de derivar propietario. Verificar `exp`, `nbf` cuando esté presente y skew acotado; mantener audiencia/presentador y rechazar tokens inválidos de forma uniforme. Pruebas criptográficas reales con claves efímeras y los mismos locks de dependencias del candidato, incluyendo expirado, sin expiración/sujeto, algoritmo incorrecto y cambio de issuer/audience/presentador. No cambiar la clave histórica de propietario sin migración controlada.

### SEC-18 — RPC Geth permisivo: alta condicionada, P2 en LIGHT; bloquea ON

**Evidencia:** [RPC](../../k8s/blockchain/rpc/statefulset.yaml), 77–89, habilita `admin,personal`, desbloqueo inseguro y wildcards; imagen `ethereum/client-go:v1.10.1`. Base RPC y [News Chain](../../k8s/apis/news-chain/deployment.yaml) declaran cero réplicas. El script de modo debe verificar todos los workloads efectivos, no solo dos YAML.

**Cierre:** gate de activación por perfil que impida ON mientras no exista inventario de métodos consumidos, identidad/segmentación, módulos mínimos, firmas/gestión de claves seguras y cliente soportado ensayado. Mantener sin exposición pública y comprobar que LIGHT funciona con Geth apagado. El backlog no se presenta como riesgo remoto activo de LIGHT, pero tampoco se permite encenderlo sin cerrar controles.

### SEC-19 — Evidencia de tests de seguridad insuficiente: media, P1 transversal

**Evidencia:** [tests de Evidence Search](../../tests/api/test_evidence_search_units.py), 207–245: fixture `autouse` sustituye `_validate_fetch_url` por un permiso incondicional; el test que pretende verificar el validador real no lo restaura y falla. Otros tres tests de redirección fallan porque sus dobles `Client.get` no aceptan el argumento `follow_redirects` que usa `_bounded_get`. La selección ejecutada dio **4 fallos y 5 éxitos**. Estos son defectos de las pruebas; no demuestran que producción acepte directamente una IP privada. Además, la colección de tests JWT de esta sesión falla por dependencia `jose` ausente.

**Cierre:** distinguir pruebas de política real, transporte simulado y redirecciones; simular DNS/transporte sin desactivar la función bajo prueba. Entorno reproducible y checks obligatorios por perfil, con pruebas negativas que fallen al retirar el control. Un test que usa un validador falso solo demuestra el flujo ante esa respuesta, no protección SSRF real. No introducir credenciales o dependencia de producción en tests locales.

## Validación realizada y límites de la evidencia

| Comprobación | Resultado de esta sesión | Alcance |
| --- | --- | --- |
| Lectura de código, perfiles y búsqueda declarativa de red/endurecimiento | Hallazgos anteriores referenciados por archivo y función | Checkout local; no estado aplicado |
| `PYTHONPATH=api .venv/bin/python -m pytest -q tests/api/test_gateway_security.py` | **8 passed** | Tamaño de cuerpo, request-id y logging; no valida JWT, red ni borde |
| Mismo comando con `tests/api/test_gateway_jwt_claims.py` añadido | **Error de colección: `ModuleNotFoundError: jose`** | No se alteró el entorno para ocultar el fallo; no hay resultado dinámico de firma/claims |
| `PYTHONPATH=api .venv/bin/python -m pytest -q tests/api/test_evidence_search_units.py -k 'fetch_url_validation or redirect_rejects or redirect_follows or streaming_fetch'` | **4 failed, 5 passed, 74 deselected** | Fixture anula el validador real y tres dobles de redirección no admiten `follow_redirects`; streaming seleccionado pasa. No equivale a explotación SSRF |
| Sonda aislada de `publish_with_assertions` usando su AST, modelos reales y dobles de E/S sin red/DB | Cliente suspendido, cuotas cero, LIGHT: retorno `ASSERTIONS_REQUESTED`, publicación simulada y escrituras `1`, `-1` | Prueba de admisión/contabilidad local; consumidores no ejecutados |
| Sonda de `QuotaDetail(news_generation=-1)` y función de propietario sin `sub` | Modelo acepta `-1`; propietario `user_unknown_sub` | No implica token firmado aceptado en producción |
| Sonda de `kafka_security_kwargs(security_protocol='SASL_SSL')` sin credenciales | Devuelve `{}`, configuración de cliente por defecto | Fallback del helper; no demuestra bypass de un broker que exija autenticación |
| Inspección de material privado versionado | Nombres de dos claves TLS y keystore cifrado; no se imprimieron valores | Uso vigente pendiente |
| Consulta de fuentes oficiales externas | EOL MongoDB, alcance de NetworkPolicy y diferencia AOP/Origin CA contrastados | No sustituyen inspección del despliegue |

Para repetir la sonda de cuotas, extraer `publish_with_assertions`, `normalize_validation_mode` y `require_available_validation_mode` sin decoradores, importar `PublishWithAssertionsRequest`, `AssertionsGeneratedResponse`, `ValidationMode` y `build_assertions_document_v2` reales y sustituir únicamente E/S: cuotas fijas con `status=Suspended`, contadores/límites cero; solicitud LIGHT con una aserción válida y contexto canónico; registrar `update_client_consumed` y `send_and_wait`. Usar `BLOCKCHAIN_ENABLED=False` y lecturas/escrituras de órdenes simuladas. Comparar las escrituras con el valor inicial sin ejecutar consumidores. Las otras sondas llaman directamente al modelo/helper y a la función de propietario extraída. Se ejecutaron desde un archivo temporal fuera del producto. El cierre exige después pruebas integradas con persistencia y mensajería reales.

## Aceptación operativa requerida

| Frontera | Evidencia necesaria antes del cierre correspondiente |
| --- | --- |
| CI → SSH/K3s | Rechazo por host key/CA/nombre incorrectos, antes de cualquier operación privilegiada; ejecución válida de deploy y rollback |
| Internet → Cloudflare → Hetzner | Reglas/eventos y versión exportados sin secretos, origen directo cerrado IPv4/IPv6, 80/6443 internos no públicos; SSH solo según política operativa |
| mTLS → OIDC → rol | Sin certificado administrativo: bloqueo de borde; con certificado sin JWT: rechazo de Gateway; JWT sin rol: 403; autorizado: PUT válido. Mantener semántica 401/403 consistente |
| Usuario/organización → recurso | Dos identidades/organizaciones, acceso cruzado negativo en órdenes, eventos, validaciones, enlaces, búsquedas y exportaciones; documentar privilegio global explícito de `trust-admin` |
| Aplicación → documentos | Política real bloquea destinos prohibidos y rebinding; redirecciones/retries no eluden control; bytes/tiempo/concurrencia acotados |
| Pod → servicios/broker | Pod ajeno rechazado; identidad válida solo para rutas/topics permitidos; regresión positiva completa LIGHT |
| Identidad → coste | Reserva previa, concurrencia/replay idempotentes, límites agotados y clientes suspendidos rechazados, sin cifras negativas ni gasto sin atribución |
| Datos → copia → recuperación | Restauración aislada MongoDB/Keycloak comprobada y cronometrada, claves externas disponibles, consistencia y rollback de migración ensayados |

Cada evidencia debe asociar SHA, digest de imágenes, perfil/render, instante UTC, ejecutor, prueba, esperado/obtenido y ubicación sin secretos. Registrar hallazgos pendientes y responsable; no confundir ejecutar un comando con superar su aceptación.

## Dictamen y relación con v0.0.13b

La revisión identifica debilidades confirmadas y caminos de impacto alto, especialmente CI y la combinación descarga externa/confianza interna/mensajería. El diseño de borde y las pruebas históricas reducen superficie, pero no justifican posponer el cierre de esas rutas hasta v0.0.16. Los problemas de cuotas y baja de clientes añaden una vía de abuso autenticado que ninguna de las dos revisiones había detallado así.

**No hay evidencia suficiente para declarar una vulnerabilidad crítica remota explotada, ni para certificar que no existe.** La recomendación es **NO-GO para abrir la beta mientras falten las puertas P0/P1 de [version.md](../version.md)**. v0.0.13b permanece planificada; esta entrega aporta auditoría y planning, no implementa las remediaciones ni cambia producción. Los P2 quedan con alcance y disparadores explícitos, especialmente Blockchain OFF y rotación urgente si se encuentra una credencial activa expuesta.
