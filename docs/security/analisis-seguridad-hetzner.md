# Análisis de seguridad: despliegue LIGHT en Hetzner

Fecha de revisión: 2026-11-02. Revisión de código: `ad40321369bfd901022df19995369d719c65ba3a`, con modificaciones locales previas en [la guía de despliegue](../deploy/main-posttfm-hetzner-smart-light.md). La guía es evidencia de la configuración **prevista**, no de su aplicación en el servidor. No se ha accedido a Hetzner, Cloudflare, GitLab ni al clúster; no se han ejecutado pruebas de penetración, escaneos de dependencias ni restauraciones. El documento no certifica el estado de producción ni la ausencia de otras vulnerabilidades.

## Alcance y método

Se han revisado la guía de despliegue, la configuración de CI, los manifiestos Kubernetes y partes relevantes del Gateway y Evidence Search. El escenario principal es `apis-frontend-prod`, con Blockchain `OFF`, sobre K3s en Hetzner. Blockchain activada, contratos inteligentes y una auditoría exhaustiva del código y de dependencias quedan fuera del alcance. Los manifiestos describen el estado deseado; overlays, recursos preexistentes y configuración externa pueden cambiar el estado efectivo.

Las amenazas se agrupan según STRIDE: **suplantación (S)**, **manipulación (T)**, **repudio (R)**, **divulgación (I)**, **denegación de servicio (D)** y **elevación de privilegios (E)**. Una amenaza puede pertenecer a varias categorías. La prioridad es una valoración cualitativa para el escenario descrito: **alta** si puede comprometer acceso, integridad o recuperación del sistema completo bajo condiciones plausibles; **media** si requiere condiciones adicionales o tiene alcance más limitado. No son probabilidades medidas ni severidades CVSS. Las condiciones de explotación y los controles reales deben verificarse antes de aceptar o descartar cada riesgo.

El flujo previsto es: usuario → Cloudflare → Traefik → frontend, Gateway y Keycloak; Gateway → servicios internos y Keycloak; servicios → MongoDB, Kafka y proveedores externos. La CI construye imágenes y opera K3s a través de SSH. Los límites de confianza principales son Internet/borde, CI/host, clúster/servicios internos y servicios/proveedores externos. La guía contempla lock de mantenimiento, mTLS y firewall, pero aquí no se ha comprobado su estado efectivo.

## Amenazas y hallazgos

### 1. Suplantación del servidor en el despliegue — S, T, I, E; prioridad alta

**Evidencia:** [`.gitlab-ci.yml`](../../.gitlab-ci.yml) obtiene la clave SSH con `ssh-keyscan` en la misma conexión de preparación y configura `--insecure-skip-tls-verify=true` para el API de K3s. Los problemas están recogidos como ISSUE-003 y ISSUE-004 en [issues.md](../issues.md).

**Escenario:** un atacante capaz de intervenir la conexión de la CI, o de controlar el punto de destino, podría hacerse pasar por el host o el API y alterar operaciones o acceder a información a la que la credencial del job tenga acceso. Se desconoce la topología y las protecciones reales de esa ruta; no se ha demostrado una interceptación. El túnel SSH aporta cifrado, pero adquirir la clave de host sin una referencia independiente no acredita su identidad; omitir la verificación TLS elimina otra comprobación de identidad.

**Acción:** fijar y verificar una clave de host obtenida por canal independiente, verificar CA y nombre del API de K3s, y probar que una clave de host, CA o nombre incorrectos rechazan el despliegue. Hasta entonces, documentar responsable, restricciones compensatorias y decisión de riesgo antes de operar.

### 2. Compromiso de la CI o de sus credenciales — S, T, I, E; prioridad alta

**Evidencia:** la [CI](../../.gitlab-ci.yml) recibe una clave SSH y un kubeconfig, construye imágenes y aplica cambios; `deploy` se habilita para pipelines web o manuales. El YAML por sí solo no acredita la protección de ramas, variables, entornos, runner o permisos de GitLab. Se descargan `kubectl` desde `stable.txt` y Skaffold sin comprobación de hash en los fragmentos revisados; Helm sí se verifica con SHA-256.

**Escenario:** quien controle un job con acceso a esas credenciales, el runner o una herramienta descargada podría operar con los permisos efectivos de las credenciales o modificar el software desplegado. El alcance depende de dichos permisos, que no se han inspeccionado.

**Acción:** revisar runners, ramas y entornos protegidos, quién puede lanzar pipelines y acceder a variables, permisos efectivos del kubeconfig, caducidad y rotación. Fijar versiones y verificar integridad de herramientas e imágenes; conservar la relación entre commit, artefactos y despliegue. Aplicar mínimo privilegio y revisar las credenciales tras cualquier sospecha de exposición.

### 3. Confianza excesiva en la red interna y en las claves de firma — S, T, I, E; prioridad alta

**Evidencia:** [Gateway](../../api/gateway/main.py) valida firma RS256, issuer, audiencia y cliente presentador, y exige el rol `trust-admin` para administración LLM. Sin embargo, su [ConfigMap](../../k8s/apis/gateway/configmap.yaml) obtiene JWKS de Keycloak por HTTP interno y usa HTTP para los servicios. El [servicio admin](../../k8s/apis/admin/service.yaml) es `ClusterIP`; Kafka configura listeners `PLAINTEXT` en su [StatefulSet](../../k8s/infra/kafka/statefulset.yaml). No se han localizado manifiestos `NetworkPolicy` en `k8s`; esto no demuestra que no existan políticas o controles externos en el clúster.

**Escenario:** si un atacante obtiene acceso a un pod o puede interferir en el tráfico o DNS interno, el aislamiento efectivo y la autenticación propia de cada servicio determinan si puede alcanzar servicios, leer o alterar mensajes, o sustituir claves JWKS y presentar tokens. `ClusterIP` limita la exposición directa exterior, pero no autentica por sí mismo a los clientes internos. No se ha probado ninguna de esas vías.

**Acción:** inventariar los flujos y permisos efectivos; restringir tráfico entre cargas y salidas mediante políticas compatibles con el CNI, autenticar y cifrar los canales sensibles —en especial la distribución JWKS y Kafka— y comprobar autorización en los servicios internos. Validar que la segmentación no interrumpe flujos legítimos.

### 4. Exposición del origen y de la administración — S, I, E; prioridad alta, pendiente de verificación

**Evidencia:** los [Ingress](../../k8s/ingress/base/kustomization.yaml) publican rutas para GUI, Gateway y Keycloak sobre `websecure`; [Traefik](../../k8s/traefik/values-prod.yaml) restringe qué IP pueden aportar cabeceras reenviadas. La [guía](../deploy/main-posttfm-hetzner-smart-light.md) exige revisar firewall de Hetzner, acceso SSH, lock y mTLS de Cloudflare. La lista de proxies confiables no equivale por sí sola a una regla de firewall ni prueba mTLS.

**Escenario:** si el origen o la administración son accesibles por rutas no previstas, un tercero podría evitar controles del borde o intentar comprometer acceso administrativo. No se han verificado reglas, puertos, identidades de cliente ni acceso externo.

**Acción:** desde redes independientes comprobar IPv4 e IPv6, reglas efectivas de Hetzner y host, cierre de puertos administrativos e internos, restricciones al origen, certificados y mTLS, y comportamiento de Keycloak y Gateway. Verificar claves SSH y desactivación de contraseñas conforme a la guía sin interrumpir el acceso de recuperación.

### 5. Pérdida de datos y recuperación incompleta — T, D; prioridad alta

**Evidencia:** el job de [deploy](../../.gitlab-ci.yml) ejecuta una [realineación de MongoDB](../../scripts/k8s/realign-source-routing-mongodb.sh) que puede eliminar colecciones de rutas, perfiles y caché, y elimina colecciones obsoletas. El job de rollback intenta revertir Deployments del namespace `apis`, no restaura datos ni todos los componentes. La guía identifica otros estados, como PostgreSQL de Keycloak, Kafka, IPFS, PVC y configuración externa, que una copia de MongoDB no cubre. MongoDB y Kafka declaran una réplica en sus manifiestos.

**Escenario:** una migración fallida, un cambio malicioso, corrupción o pérdida del host puede producir indisponibilidad o pérdida de estado. La capacidad real de recuperación y la existencia de copias no se han comprobado. Una réplica adicional en el mismo host tampoco eliminaría el fallo del host.

**Acción:** inventariar datos y dependencias, definir objetivos de recuperación, copias externas protegidas y coherencia entre componentes; ensayar restauraciones aisladas y rollback por versión. Verificar backup antes de la migración y definir explícitamente las colecciones y pérdida de caché aceptables.

### 6. Descarga de contenido externo y SSRF — T, I, D; prioridad media

**Evidencia:** [document_fetcher.py](../../api/evidence-search/app/document_fetcher.py) valida esquema, puerto, resolución a direcciones globales y cada redirección; limita redirecciones y tamaño, y rechaza degradación HTTPS a HTTP en redirecciones. La validación DNS ocurre antes de la conexión HTTP, que puede realizar otra resolución; no se ha acreditado que la dirección validada quede vinculada a la conexión. El motor también procesa HTML y PDF externos.

**Escenario:** si una URL controlable por un atacante alcanza esta ruta y la resolución cambia entre validación y conexión, podría intentar acceder a destinos internos; documentos maliciosos o costosos también podrían afectar al proceso. Son hipótesis dependientes del camino de entrada, DNS, proxy y red; no se ha demostrado explotación.

**Acción:** probar el flujo completo con redirecciones y cambios DNS en un entorno aislado; vincular la conexión a direcciones verificadas conservando validación TLS y controlar la salida de red. Mantener límites de tamaño, tiempo y recursos y actualizar los procesadores de documentos.

### 7. Contenido externo y proveedores de IA — T, I, D; prioridad media

**Evidencia:** la [guía](../deploy/main-posttfm-hetzner-smart-light.md) describe búsquedas y uso de proveedores externos de LLM, y el procesamiento de documentos recuperados. En SMART puede usarse texto devuelto por el proveedor de búsqueda.

**Escenario:** contenido o resultados manipulados podrían influir en la clasificación, evidencia o respuesta del modelo; los datos enviados a terceros quedan sujetos a sus configuraciones y políticas. Cuotas agotadas, latencia o fallos del proveedor pueden afectar disponibilidad y coste. No se ha demostrado una inyección de instrucciones ni una filtración.

**Acción:** tratar documentos como datos no confiables, evaluar ataques de prompt injection y citas falsas, limitar datos enviados y permisos de claves, fijar presupuestos y monitorizar uso, errores y calidad. Revisar contratos y retención reales de los proveedores.

### 8. Agotamiento de recursos y puntos únicos de fallo — D; prioridad media

**Evidencia:** el [middleware de Gateway](../../api/gateway/security.py) y [Traefik](../../k8s/ingress/base/gateway-middleware.yaml) limitan el cuerpo a 5 MiB; Gateway registra eventos y consulta JWKS al autenticar solicitudes. Gateway, MongoDB y Kafka declaran una réplica; Evidence Search declara dos. No se ha encontrado limitación de tasa en Gateway ni en los manifiestos de ingress y Traefik revisados. El runbook documenta una regla de Cloudflare por IP para operaciones costosas; no cubre login, refresh ni polling y su estado actual no se ha comprobado.

**Escenario:** tráfico concurrente, llamadas costosas o fallo de Keycloak, proveedores o host pueden degradar el servicio y generar gasto. Los límites de tamaño no limitan por sí solos el número de solicitudes. No se ha medido capacidad ni probado resistencia.

**Acción:** verificar límites de tasa y concurrencia en el borde y por identidad, cuotas de proveedor, alertas, tiempos de espera y capacidad bajo carga; valorar caché segura y rotación de JWKS, así como recuperación del host y dependencias críticas.

### 9. Secretos, registros y trazabilidad — I, R, E; prioridad media

**Evidencia:** los manifiestos consumen Kubernetes Secrets y la guía pide ficheros privados y verificación sin imprimir valores. [Gateway](../../api/gateway/security.py) registra método, ruta, estado e identificador de petición; el identificador puede ser suministrado por el cliente. [issues.md](../issues.md) recoge una credencial local en un helper; no se ha establecido que sea productiva. No se han comprobado cifrado de Secrets en reposo, RBAC efectivo, retención, protección o centralización de auditoría.

**Escenario:** acceso indebido a runner, backups, registros o clúster puede revelar secretos o datos; registros incompletos o modificables pueden dificultar atribución e investigación. Un identificador aportado por el cliente sirve para correlación, no acredita identidad.

**Acción:** inventariar y rotar credenciales según exposición y permisos, revisar RBAC y protección de Secrets y copias, evitar secretos en logs y artefactos, y definir auditoría protegida de acciones administrativas, despliegues y cambios de configuración. Verificar los controles efectivos y su retención.

## Análisis del borde exterior según la documentación

Esta sección amplía la revisión anterior: la documentación **sí registra pruebas históricas del perímetro**, no solo una intención. La [evidencia de cierre de v0.0.12](../releases/v0.0.12.md#phase-7---closure-of-the-perimeter-and-administrative-access) sitúa una línea base en el 21-08-2026, asociada al commit `8bdaa6f`. El [runbook de Hetzner](../deploy/skaffold-server.md#1-current-photo) describe una fotografía operativa y la [guía de v0.0.13](../deploy/main-posttfm-hetzner-smart-light.md) recoge observaciones posteriores. Ninguna prueba histórica acredita que las mismas reglas sigan activas hoy ni valida por sí sola la revisión v0.0.13, que permanece en Deploying. No se ha consultado el estado en vivo.

| Límite de confianza | Evidencia documental | Amenaza y valoración |
| --- | --- | --- |
| Usuario → Cloudflare | La release registra HTTPS obligatorio, TLS mínimo 1.2, modo Full (strict), mTLS general temporal, mTLS administrativo, WAF y límites. Documenta pruebas con y sin certificado y acceso OIDC. El runbook declara cinco reglas ordenadas. | **S, I, E:** certificados robados, reglas mal ordenadas o una ruta no protegida permitirían alcanzar controles posteriores. Existen defensas históricamente probadas; configuración vigente, rutas y revocación siguen por verificar. La retirada del mTLS general pertenece a v0.0.14, no al estado aceptado de v0.0.13. |
| Cloudflare → origen Hetzner | La release declara certificado Origin CA validado para el dominio y firewall que admitía 443 solo desde redes Cloudflare; registra bloqueo del acceso directo a 443, 80 y 6443. El runbook exige revisar rangos y reglas. | **S, T, I, E:** si el origen acepta tráfico fuera del camino previsto, podrían eludirse los controles de Cloudflare. El filtrado por redes compartidas limita el origen de red, pero no demuestra por sí solo una autenticación exclusiva de la zona; no hay evidencia revisada de autenticación mutua Cloudflare → origen. Confirmar reglas IPv4/IPv6, acceso directo y controles adicionales sin dar por probado un bypass. |
| Origen → Traefik → aplicación | El runbook documenta rutas `/gui`, `/backend`, `/auth`, TLS de origen, cabeceras de Cloudflare confiables, bloqueo de recursos no públicos y de métodos, límite de 5 MiB y logs sin cabeceras ni query. Los manifiestos declaran `strictPrefixMatching`. | **S, T, I:** reglas de rutas, métodos o cabeceras divergentes pueden abrir una vía o romper una función. Los Ingress y `ClusterIP` documentados reducen superficie externa, pero hay que verificar el estado desplegado y pruebas negativas con variaciones de ruta. |
| Operador / CI → SSH → K3s | La guía registra el 01-11-2026 configuración efectiva SSH por clave en 2222, contraseñas, teclado interactivo y root deshabilitados, y una conexión nueva por clave tras reinicio. El acceso previsto a K3s usa túnel SSH y el runbook exige 6443 cerrado externamente. | **S, T, I, E:** estas evidencias favorecen el acceso administrativo, pero no acreditan el firewall actual ni todas las condiciones `Match`. La CI presenta dos debilidades confirmadas en código: confianza SSH obtenida con `ssh-keyscan` y verificación TLS de K3s omitida. La prueba de rechazo sin clave queda pendiente en la guía. |
| Plataforma → proveedores y documentos | La guía describe proveedores externos de búsqueda y LLM y obtención de documentos. Es una frontera saliente además del acceso público entrante. | **I, T, D:** datos enviados a terceros, contenido no confiable, dependencia de cuota o proveedor. Deben verificarse los datos efectivamente enviados, controles de salida y pruebas indicadas en las amenazas 6 y 7. |

### Controles concretos y límites

- **mTLS y lock:** v0.0.12 documenta rechazo sin certificado y aceptación con certificado válido, además de pruebas del lock y atribución de reglas. La revocación de un certificado administrativo desechable está prevista para v0.0.14. Un certificado válido supera el control mTLS, pero no sustituye JWT ni autorización. El runbook advierte que, si se crean las redirecciones Single Redirect, `/` y `/gui` pueden responder `302` antes del WAF incluso con lock: no afirmar que todo el hostname devuelve `403` sin comprobar si están activas.
- **WAF y tasa:** el runbook declara Free Managed Ruleset y una regla de 5 peticiones por 10 segundos y mitigación de 10 segundos para operaciones costosas por IP. Excluye login, refresh y polling: no se debe extrapolar la cobertura al resto de rutas ni inferir ausencia de cualquier otra protección. La release registra pruebas y correlación de rechazos; falta comprobar configuración, alcance y eficacia actuales.
- **Administración:** el runbook exige mTLS permanente también para `/backend/admin/llm` y sus subrutas. Las pruebas históricas citadas acreditan específicamente la administración de Keycloak, no necesariamente todas las rutas LLM nuevas. Además, el runbook dice que la regla de métodos de `/backend` solo permite GET, HEAD, POST y OPTIONS, mientras que [Gateway](../../api/gateway/main.py) declara `PUT` para actualizar componentes y validadores LLM. Hay una posible incompatibilidad funcional: comprobar expresión y excepciones reales y probar `PUT` autorizado por el borde; no se ha comprobado que la regla desplegada lo bloquee.
- **Plan futuro:** [next_releases.md](../next_releases.md#step-1-remove-temporary-mtls-and-keep-the-route-gate) describe conservar una puerta de rutas al retirar el mTLS general; [el runbook](../deploy/skaffold-server.md#54-redirects-and-public-border-after-withdrawal-of-the-general-mtls) describe añadir un `default deny`. Las formulaciones no demuestran por sí solas la expresión actualmente desplegada ni que el cambio futuro se haya aplicado. Antes de la transición reconciliar ambos procedimientos y validar la expresión efectiva sin abrir una ventana desprotegida.
- **Trazabilidad temporal:** el registro de cierre de v0.0.12 indica lock desactivado al terminar aquella prueba; la guía de v0.0.13 exige activarlo durante operaciones. Ambos datos se refieren a momentos o estados operativos distintos, no permiten determinar el estado actual.

### Juicio del perímetro documentado

La documentación aporta una línea base con varias capas y pruebas históricas, más sólida que una configuración meramente propuesta. La confianza sobre el **estado actual** sigue siendo baja sin comprobación directa; los riesgos confirmados de identidad en la CI persisten aunque el borde web funcione correctamente. La prioridad inmediata es verificar reglas y accesos efectivos, renovar pruebas negativas y corregir SSH/K3s de la CI. Antes de retirar el mTLS general deben probarse también rutas, métodos, revocación, límites y rollback bajo la configuración exacta de esa ventana.

## Controles observados y límites

- Gateway verifica firma, issuer, audiencia y cliente de JWT, y las rutas administrativas LLM requieren `trust-admin`; debe comprobarse el aislamiento de órdenes y administración por el borde real con identidades distintas. El overlay productivo desactiva la documentación interactiva de Gateway. Fuentes: [código](../../api/gateway/main.py), [overlay](../../k8s/apis/gateway/overlays/prod/kustomization.yaml).
- El servicio Source Router declara `runAsNonRoot` y deshabilita escalada de privilegios; esta observación no se extiende automáticamente a las demás cargas. Fuente: [Deployment](../../k8s/apis/source-router/base/deployment.yaml).
- Evidence Search incorpora validaciones y límites en la descarga; no prueban por sí solos protección completa frente a cambios DNS, documentos hostiles o consumo de recursos. Fuente: [document_fetcher.py](../../api/evidence-search/app/document_fetcher.py).
- La guía prevé verificación del borde, mantenimiento y backups, pero su ejecución y resultado siguen sin acreditarse en esta revisión. La guía indica que el despliegue y aceptación de esta revisión en Hetzner están pendientes.

## Verificaciones prioritarias antes de aceptar el riesgo

1. Corregir la autenticación de SSH y del API K3s de la CI y verificar los rechazos ante identidades incorrectas; revisar privilegios y protección de runner, ramas y secretos.
2. Comprobar desde fuera y en Hetzner firewall, exposición de K3s y SSH, Cloudflare, mTLS y acceso al origen. Registrar resultados sin incluir secretos.
3. Inventariar políticas de red, RBAC, identidad de servicios y cifrado interno; verificar especialmente acceso a Kafka, servicios administrativos y JWKS.
4. Verificar y ensayar recuperación de MongoDB y demás estados, incluyendo el efecto de la migración y la compatibilidad con la versión de aplicación.
5. Probar aislamiento de usuarios y roles, descarga frente a SSRF y límites de consumo; revisar dependencias e imágenes con herramientas y resultados asociados al SHA e imágenes realmente desplegados.

Registrar para cada comprobación fecha, entorno, alcance, resultado, responsable y evidencia protegida. Las pruebas locales o la mera presencia de manifiestos no sustituyen la verificación de la configuración efectiva en Hetzner.
