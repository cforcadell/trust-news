# Auditoría de seguridad de Assermetry — rama `postTFM`

3 de noviembre de 2026 · Entorno objetivo: Hetzner / K3s · Auditoría de código, manifiestos y documentación operativa

## 1. Evaluación de seguridad del entorno productivo

La documentación de `docs/deploy/skaffold-server.md`, `docs/quick_start_hetzner.md` y los manifiestos productivos cambia considerablemente la evaluación respecto a analizar únicamente el código.

Assermetry ya dispone de una arquitectura perimetral de seguridad bastante completa, con controles que no serían visibles examinando solo las APIs Python.

He podido documentar estas protecciones:

- Cloudflare: WAF, reglas de bloqueo, protección mTLS, limitación de peticiones y control de rutas.
- Hetzner: firewall previsto para aceptar tráfico HTTPS únicamente desde las redes de Cloudflare.
- Traefik: terminación TLS con certificado Origin CA, validación de cabeceras de proxy y rutas restringidas.
- Keycloak: autenticación OIDC y tokens JWT con validación de firma, emisor, audiencia y cliente.
- Gateway: autorización, separación de clientes, roles administrativos y limitación del tamaño de las peticiones.
- Kubernetes: servicios internos sin Ingress público, acceso operativo mediante SSH y túneles.
- SSH: puerto 2222, autenticación por clave pública y prohibición documentada del acceso root y por contraseña.

Hay una distinción importante: la documentación del 1 de noviembre de 2026 indica que la versión `v0.0.13` de `postTFM` continúa en estado `Deploying` y que todavía no consta su validación completa en Hetzner. Por tanto, diferenciaré entre medidas verificadas en el código, medidas documentadas de la instalación existente y controles cuya aplicación efectiva debe comprobarse en el servidor.

No sería correcto atribuir a producción vulnerabilidades de KIND, ni dar por desplegado todo el contenido de `postTFM`.

## 2. Superficie de ataque exterior: Internet → Cloudflare → Hetzner

Arquitectura documentada

Internet

Usuarios y clientes B2B

Cloudflare

WAF · mTLS · Rate limiting · Reglas de rutas

Firewall Hetzner

HTTPS 443 solo desde redes Cloudflare autorizadas

Traefik + Cloudflare Origin CA

Ingress K3s y enrutamiento de los tres prefijos públicos

/gui/

Frontend

/backend

Gateway JWT

/auth

Keycloak

La regla permanente de mTLS protege `/auth/admin`, `/auth/realms/master` y `/backend/admin/llm/*`. El resto del dominio sigue bajo mTLS temporal hasta la transición prevista para `v0.0.14`.

No hay evidencia de que los otros microservicios tengan Ingress público. Este diseño reduce significativamente el riesgo de ataques directos, aunque no elimina los ataques que utilizan funcionalidades legítimas de la API.

### Hallazgos de seguridad exterior

| ID     | Hallazgo y gravedad                                                                                                                                                                                                                                                             | Dificultad de corrección |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| EXT-01 | ALTA — SSRF y DNS rebinding potencial. Los descargadores comprueban que la URL resuelva a una IP pública, pero la conexión HTTP puede resolver el dominio otra vez. Existe una ventana entre comprobación y uso. Afecta a importación de noticias y recuperación de evidencias. | Media-alta, 8–16 h       |
| EXT-02 | MEDIA — Consulta de JWKS en cada petición autenticada. El Gateway solicita las claves a Keycloak al validar cada JWT. Puede amplificar tráfico y facilitar agotamiento de recursos.                                                                                             | Baja, 3–6 h              |
| EXT-03 | MEDIA — Cuotas no completamente atómicas. Algunas rutas leen un contador y posteriormente escriben su nuevo valor. Las solicitudes concurrentes pueden superar límites o sobrescribir contadores.                                                                               | Media, 8–16 h            |
| EXT-04 | MEDIA — Limitación económica insuficiente por identidad. Cloudflare aplica un límite por IP para operaciones costosas. No equivale a un límite global de gasto por cliente ni impide ataques distribuidos.                                                                      | Media, 6–12 h            |
| EXT-05 | MEDIA, pendiente de verificar — Cabeceras de seguridad del navegador. No encuentro CSP, HSTS ni políticas de framing declaradas en `nginx_k8s.conf`. Podrían configurarse en Cloudflare; no puedo confirmar su ausencia efectiva.                                               | Baja, 2–5 h              |
| EXT-06 | BAJA — Información de diagnóstico accesible. `/capabilities` se expone sin JWT y comunica si Blockchain está habilitado. No revela secretos, pero permite conocer parte del estado operativo.                                                                                   | Baja, menos de 1 h       |

#### EXT-01: el riesgo que más me preocuparía desde Internet

Encontré dos implementaciones que verifican URLs antes de descargarlas:

- `api/news-handler/main.py`, líneas 2290–2404.
- `api/evidence-search/app/document_fetcher.py`, líneas 308–385.

Ambas comprueban las IP resueltas y bloquean las privadas. También controlan las redirecciones. Son defensas correctas y bastante mejores que una descarga HTTP sin validación.

El problema es que la IP verificada no queda necesariamente fijada para establecer la conexión.

Un dominio controlado por un atacante podría devolver inicialmente una IP pública y, en una resolución posterior, otra dirección. Esto exige condiciones concretas y no he demostrado explotación contra Hetzner, pero el patrón vulnerable está presente.

Corrección propuesta: resolver y validar todas las direcciones, utilizar para la conexión la IP autorizada conservando Host/SNI y la verificación TLS, aplicar la misma política en cada redirección y bloquear mediante política de salida las redes privadas, loopback, metadatos y API de Kubernetes.

Fuentes: [News Handler](https://github.com/cforcadell/trust-news/blob/postTFM/api/news-handler/main.py?utm_source=chatgpt.com#L2290-L2404) · [Document Fetcher](https://github.com/cforcadell/trust-news/blob/postTFM/api/evidence-search/app/document_fetcher.py?utm_source=chatgpt.com#L308-L385).

#### EXT-02: cachear las claves de Keycloak

En `api/gateway/main.py`, líneas 124–163, `get_current_user()` obtiene las JWKS de Keycloak para cada validación.

No necesitas hacer eso continuamente: puedes mantener una caché de claves públicas por `kid`, con caducidad y actualización controlada ante rotación.

Esto reduce dependencia y latencia, sin desactivar las comprobaciones de firma, emisor, audiencia o cliente.

[Ver implementación](https://github.com/cforcadell/trust-news/blob/postTFM/api/gateway/main.py?utm_source=chatgpt.com#L124-L163).

### Cloudflare: qué considero correctamente protegido

| Control                              | Valoración                                           |
| ------------------------------------ | ---------------------------------------------------- |
| mTLS permanente de administración    | Buena defensa                                        |
| mTLS general temporal                | Buena defensa para la fase actual                    |
| Cloudflare WAF Managed Rules         | Activación documentada                               |
| Regla de métodos HTTP                | Buena restricción, con una incompatibilidad          |
| Límite de cuerpo de 5 MiB            | Implementado en Traefik y Gateway                    |
| Bloqueo de OpenAPI/Swagger           | Documentado en Cloudflare y configuración productiva |
| Bloqueo de rutas desconocidas        | Planificado para v0.0.14                             |
| Bloqueo del acceso directo al origen | Documentado, necesita prueba externa                 |

Hay una incompatibilidad concreta que corregir: `docs/deploy/skaffold-server.md` establece que en `/backend` solo se permiten `GET`, `HEAD`, `POST` y `OPTIONS`, pero la GUI utiliza `PUT` para modificar las configuraciones LLM.

Aunque el administrador presente certificado mTLS válido y JWT autorizado, la regla de métodos puede bloquear esa operación.

No es una vulnerabilidad que abra acceso indebido; es un fallo funcional de la política perimetral. Lo resolvería permitiendo `PUT` exclusivamente en las rutas administrativas LLM, conservando el mTLS y la comprobación de rol. Dificultad baja, unas 1–3 horas con pruebas.

## 3. Seguridad interior: servicios dentro de K3s

Aquí encuentro el mayor margen de mejora.

Tráfico tras superar el Gateway

Gateway — JWT y permisos

News Handler

Admin API

Generate Assertions

Validadores

Evidence Search

Source Router

MongoDB · Kafka · Keycloak · IPFS

El perímetro está protegido, pero la autorización dentro del clúster depende en gran medida de que los servicios que llaman sean legítimos.

### Hallazgos de seguridad interna

| ID     | Hallazgo y gravedad                                                                                                                                                                                                         | Dificultad de corrección                    |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| INT-01 | ALTA — Endpoints internos sin autenticación propia. Admin permite crear clientes, modificar cuotas y configurar modelos sin verificar la identidad del servicio llamante.                                                   | Media-alta, 12–24 h                         |
| INT-02 | ALTA — No hay NetworkPolicies en los manifiestos revisados. No se declara una política de aislamiento de tráfico entre pods y namespaces. Un servicio comprometido podría intentar conectarse a otros componentes internos. | Media, 8–16 h                               |
| INT-03 | ALTA — Kafka utiliza PLAINTEXT y carece de autenticación de productores/consumidores en la configuración examinada. Un pod con acceso de red podría publicar mensajes falsificados o leer comunicaciones.                   | Alta, 16–30 h                               |
| INT-04 | ALTA — MongoDB 4.4 obsoleto. La imagen declarada es `mongo:4.4`, cuyo soporte estándar terminó el 29 de febrero de 2024.                                                                                                    | Alta, 16–32 h, incluida migración           |
| INT-05 | MEDIA — Comunicaciones internas HTTP sin TLS. Gateway, Admin, News Handler y varios servicios intercambian datos mediante HTTP dentro del clúster.                                                                          | Alta, 16–35 h para una solución general     |
| INT-06 | MEDIA — Endurecimiento Kubernetes desigual. Hay contenedores que ejecutan usuarios no privilegiados, pero no todos tienen restricciones explícitas sobre capacidades, escalada de privilegios y token de ServiceAccount.    | Media, 6–12 h                               |
| INT-07 | MEDIA — Credenciales y claves históricas versionadas. Existen archivos de claves privadas TLS y keystores Ethereum cifrados en el repositorio público. No está demostrado que sean credenciales productivas actuales.       | Baja-media, 3–8 h más rotaciones necesarias |

### INT-01: autenticación interna insuficiente

Este es un hallazgo confirmado en el código.

Por ejemplo, `api/admin/main.py` define:

- `POST /clients`
- `PATCH /clients/{client_id}`
- `DELETE /clients/{client_id}`
- `PUT /llm/components/{component}`
- `PUT /llm/validators/{validator_id}`

Estas operaciones no verifican por sí mismas un JWT o una credencial de servicio.

De forma semejante, News Handler acepta parámetros internos `client_id` y `admin`; en varias rutas el parámetro `admin` tiene por defecto el valor `True`.

Esto no implica que un usuario de Internet pueda invocarlas directamente. El Gateway calcula dichos parámetros a partir del JWT y los servicios no tienen Ingress público.

El riesgo aparece si un atacante compromete algún pod, explota una SSRF o consigue acceso de red a los servicios internos.

Un servicio no autorizado podría intentar acceder a datos ajenos o modificar configuración y cuotas.

Recomendación: implantar autenticación servicio-a-servicio para las operaciones sensibles, eliminar valores administrativos por defecto y comprobar siempre la identidad del llamante. El Gateway debe seguir derivando permisos, pero el backend no debería confiar ciegamente en cualquier petición que reciba.

[Admin API](https://github.com/cforcadell/trust-news/blob/postTFM/api/admin/main.py?utm_source=chatgpt.com#L1280-L1365) · [News Handler](https://github.com/cforcadell/trust-news/blob/postTFM/api/news-handler/main.py?utm_source=chatgpt.com#L2051-L2130).

### INT-02: NetworkPolicies

No encontré recursos `NetworkPolicy` en el árbol de `postTFM`.

Esto no demuestra que no se hayan instalado manualmente en Hetzner, pero sí significa que la segmentación de red no está documentada declarativamente en el repositorio.

En tu arquitectura convendría permitir únicamente estas comunicaciones indispensables:

| Servicio        | Destinos necesarios                                                            |
| --------------- | ------------------------------------------------------------------------------ |
| Gateway         | News Handler, Admin, Generate Assertions, IPFS y News Chain cuando esté activo |
| News Handler    | MongoDB, Kafka, Admin y servicios de orquestación                              |
| Validadores     | Kafka, Evidence Search, Source Router, Admin y dependencias explícitas         |
| Evidence Search | MongoDB, proveedores externos de búsqueda y destinos documentales públicos     |
| Source Router   | MongoDB, proveedores LLM y buscadores                                          |
| Admin           | MongoDB, Kafka y componentes que administra                                    |

La política objetivo debería ser `default-deny`, con excepciones explícitas de entrada y salida, DNS y demás dependencias necesarias.

En K3s también hay que confirmar que el controlador de red realmente aplica NetworkPolicies; crear manifiestos que nadie hace cumplir no añade seguridad.

### INT-03: Kafka sin autenticación

En `k8s/infra/kafka/statefulset.yaml` encuentro:

```
KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092
KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka.infra.svc.cluster.local:9092
KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
```

No es un problema de exposición directa a Internet, porque Kafka permanece dentro del clúster.

Pero para Assermetry es especialmente relevante: Kafka distribuye solicitudes de generación, validaciones y respuestas que afectan al resultado de las órdenes.

Si un pod malicioso puede publicar mensajes, la integridad de los resultados podría verse comprometida.

Recomendaría primero aislar Kafka mediante NetworkPolicies y, después, incorporar autenticación SASL y ACL por servicio o una alternativa equivalente. Añadiría además validación de identidad, correlación de orden y procedencia en los mensajes sensibles.

### INT-04: versión de MongoDB

La imagen declarada `mongo:4.4` está fuera de soporte estándar desde febrero de 2024, según el calendario oficial de MongoDB. Las versiones fuera de soporte dejan de recibir las correcciones ordinarias, incluidas las de seguridad.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.mongodb.com\&sz=32)

MongoDB

[image](https://www.google.com/s2/favicons?domain=https://www.mongodb.com\&sz=32)

MongoDB Docs



No lo trataría como una emergencia de exposición pública porque MongoDB no tiene Ingress y exige autenticación. Sin embargo, sí lo resolvería antes de incorporar clientes reales.

La actualización necesita copia de seguridad, comprobaciones de compatibilidad con Motor/PyMongo, ruta de migración de versiones y ensayo de restauración. No sustituiría simplemente `mongo:4.4` por una imagen reciente.

## 4. Seguridad del servidor Hetzner y del despliegue CI/CD

Aquí hay dos vulnerabilidades especialmente claras que ya están reconocidas como `ISSUE-003` y `ISSUE-004`.

| ID     | Hallazgo y gravedad                                                                                                                                                                                         | Dificultad de corrección |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| OPS-01 | ALTA — Verificación TLS de K3s desactivada en CI. Se utiliza `--insecure-skip-tls-verify=true`. Puede permitir suplantación de la API del clúster en determinadas condiciones.                              | Baja-media, 3–6 h        |
| OPS-02 | ALTA — Clave SSH del servidor no fijada. El pipeline utiliza `ssh-keyscan` sin contrastar la huella con una clave verificada previamente.                                                                   | Baja, 2–4 h              |
| OPS-03 | MEDIA — Recuperación productiva incompleta. La documentación reconoce que el rollback no restaura toda la aplicación y sus estados.                                                                         | Alta, 16–30 h            |
| OPS-04 | MEDIA — Dependencias e imágenes desactualizadas o no completamente fijadas. Existen librerías Python con versiones antiguas y otras sin fijación estricta. No he acreditado CVE concretos para todas ellas. | Media, 8–20 h            |
| OPS-05 | BAJA para LIGHT, ALTA si se habilita Blockchain — Configuración Geth permisiva. Se utilizan APIs `admin,personal`, `--allow-insecure-unlock`, CORS y virtual hosts comodín en el RPC.                       | Media, 8–16 h            |

### Dos correcciones rápidas de CI

En `.gitlab-ci.yml` aparecen los dos puntos:

```
ssh-keyscan -p 2222 -H "$HETZNER_IP" >> ~/.ssh/known_hosts
```

y:

```
kubectl config set-cluster default \
  --server=https://127.0.0.1:6443 \
  --insecure-skip-tls-verify=true
```

Para el primero fijaría la clave pública del host verificada por un canal independiente. La CI debe fallar si cambia inesperadamente.

Para el segundo utilizaría la CA correcta de K3s y un certificado cuyo nombre sea compatible con el endpoint del túnel SSH. Hay que validar tanto la cadena como el nombre, sin recurrir a `insecure`.

[Ver ](https://github.com/cforcadell/trust-news/blob/postTFM/.gitlab-ci.yml?utm_source=chatgpt.com#L22-L53)[`.gitlab-ci.yml`](https://github.com/cforcadell/trust-news/blob/postTFM/.gitlab-ci.yml?utm_source=chatgpt.com#L22-L53).

Ambos problemas son importantes porque comprometer la canalización de despliegue puede ser más peligroso que comprometer una petición HTTP normal: el pipeline posee credenciales para modificar recursos productivos.

### Origen de Cloudflare: una aclaración

La protección documentada de Hetzner mediante firewall que limita el puerto 443 a Cloudflare es adecuada.

Pero un certificado Cloudflare Origin CA no es lo mismo que exigir que Cloudflare presente un certificado cliente al origen. Origin CA protege la conexión TLS; Authenticated Origin Pulls incorpora autenticación adicional del proxy Cloudflare ante el servidor.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developers.cloudflare.com\&sz=32)

Cloudflare SSL/TLS docs

[image](https://www.google.com/s2/favicons?domain=https://developers.cloudflare.com\&sz=32)

Cloudflare SSL/TLS docs



No he encontrado evidencia de Authenticated Origin Pulls en los manifiestos, por lo que no daría ese control por activado.

No lo clasificaría como vulnerabilidad alta mientras el firewall realmente solo permita los rangos de Cloudflare. Sí lo consideraría una mejora de defensa en profundidad.

## 5. Hallazgos que NO considero vulnerabilidades críticas actuales

Conviene separar lo realmente peligroso de lo que ya está mitigado o pertenece a otros entornos.

| Situación                                                | Evaluación                                                                                                       |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Mongo Express, Grafana y Kafdrop accesibles por túnel    | Correcto si los túneles permanecen en loopback y no existen otros accesos públicos                               |
| API administrativa como ClusterIP                        | Correcto perimetralmente, aunque requiere mejorar autenticación interna                                          |
| Keycloak con HTTP dentro de K3s                          | Riesgo interno, no exposición HTTP directa de Internet                                                           |
| Claves TLS locales incluidas en Git                      | Mala práctica; no hay evidencia de que sean las claves Origin CA activas                                         |
| Credencial OIDC local de `ISSUE-024`                     | Riesgo local documentado; no debe confundirse con una fuga confirmada de Hetzner                                 |
| Blockchain con configuración Geth permisiva              | No es riesgo activo de LIGHT si los StatefulSets y News Chain están realmente a cero réplicas                    |
| Ausencia actual de la regla `default deny` de Cloudflare | No equivale a exposición automática: Traefik restringe los Ingress. Debe implantarse al retirar el mTLS temporal |

Esto último es importante: cuando llegue `v0.0.14`, retirar el mTLS temporal sin activar simultáneamente el bloqueo de rutas desconocidas y probar el firewall sería un retroceso innecesario de seguridad.

## 6. Priorización de remediación

Mi propuesta es separar las correcciones urgentes de las mejoras de defensa en profundidad.

Plan recomendado para preparar Hetzner

1. P0 — Antes de desplegar la nueva revisión

   Corregir OPS-01 y OPS-02, comprobar firewall desde una red externa, validar el estado de Cloudflare y resolver el conflicto de métodos `PUT`.

   Esfuerzo estimado: 6–12 h de cambios y pruebas, aparte de la ventana operativa
2. P1 — Antes de abrir la beta a terceros

   Corregir SSRF, cachear JWKS, implantar límites económicos efectivos, añadir NetworkPolicies y endurecer las operaciones administrativas internas.

   Esfuerzo estimado: 35–65 h
3. P2 — Antes de producción comercial

   Autenticar Kafka, migrar MongoDB, revisar dependencias, completar los controles de pods y ensayar recuperación integral.

   Esfuerzo estimado: 50–100 h, dependiendo de migraciones y pruebas

Estos tiempos son estimaciones de ingeniería, no compromisos: incluyen pruebas básicas, pero no contemplan incidencias imprevistas de migración o indisponibilidad.

## 7. Qué validaría realmente en Hetzner

Antes de declarar resueltos los problemas de exposición externa, exigiría estas pruebas con la versión exacta desplegada:

| Prueba                                                          | Resultado requerido                         |
| --------------------------------------------------------------- | ------------------------------------------- |
| Acceso directo a IP de Hetzner por 443 desde una red externa    | Rechazado por el firewall                   |
| Acceso a puertos 80, 6443 y puertos internos                    | No accesibles desde Internet                |
| `/backend/admin/llm/*` sin certificado                          | Rechazado por Cloudflare                    |
| Ruta administrativa con certificado, pero sin JWT válido        | 401                                         |
| Ruta administrativa con certificado y JWT sin rol `trust-admin` | 403                                         |
| Ruta administrativa con certificado, JWT y rol válidos          | Acceso permitido; `PUT` funcional           |
| Acceso a una orden de otro cliente                              | 403 o 404, sin fuga de información          |
| URL de importación que apunta a redes internas o cambia de IP   | Bloqueada, incluidos redireccionamientos    |
| Un pod sin permiso intentando alcanzar Admin o MongoDB          | Conexión rechazada por política de red      |
| Producción LIGHT                                                | Geth y News Chain a cero réplicas efectivas |

Estas pruebas se deben ejecutar contra el borde real y dentro del clúster según corresponda. Un `port-forward` no sirve para demostrar que Cloudflare esté bloqueando una petición.

## 8. Veredicto final

Vulnerabilidades críticas confirmadas desde Internet

## 0

Esto no equivale a certificar ausencia de vulnerabilidades críticas: es una auditoría estática y documental, sin pentest ni acceso a la configuración efectiva del servidor.

La arquitectura perimetral de Assermetry es razonablemente sólida sobre el papel y tiene varias decisiones acertadas: mTLS selectivo, origen restringido, autenticación centralizada, separación de servicios y controles de despliegue.

Lo que no consideraría todavía suficientemente endurecido para un producto B2B expuesto es la seguridad de las comunicaciones y autorizaciones internas, especialmente si un componente llega a comprometerse.

Mis tres preocupaciones principales, por orden práctico, son:

1. Que una funcionalidad legítima de descarga de contenido permita SSRF hacia servicios internos.
2. Que un pod comprometido pueda modificar datos administrativos o falsificar mensajes de Kafka.
3. Que la CI despliegue código sin validar correctamente la identidad del servidor SSH y la API K3s.

No reconstruiría la arquitectura ni añadiría un service mesh ahora. Corregiría los dos problemas del pipeline, cerraría la SSRF, implantaría NetworkPolicies y protegería las operaciones administrativas internas. Esas cuatro líneas de trabajo aportan una mejora de seguridad considerable sin convertir Assermetry en otro gran proyecto de infraestructura.

Dejaría como segunda fase la autenticación avanzada entre microservicios, la migración de MongoDB y el resto del hardening. Y mantendría el mTLS general hasta que las pruebas de aceptación exterior estén superadas.

En conclusión: el diseño de acceso desde Internet es bueno, pero el aislamiento y la confianza entre componentes internos son el principal punto que reforzaría antes de abrir Hetzner a clientes reales.