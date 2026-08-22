# Versiones publicadas

Este documento conserva el resultado funcional de las versiones anteriores a la
versión en curso. La planificación activa está en [`version.md`](version.md) y
las versiones futuras en [`next_releases.md`](next_releases.md).

## v0.0.12 - Cierre del perímetro y acceso administrativo

- `assermetry.com` quedó publicado mediante Cloudflare con TLS estricto y el
  origen de Hetzner limitado a sus redes verificadas.
- Se conservaron el mTLS general temporal hasta `v0.0.14` y la protección mTLS
  administrativa permanente de Keycloak.
- OIDC quedó alineado con el issuer canónico y se comprobaron login, sesión,
  renovación del token y logout.
- Gateway rechazó las peticiones sin JWT y aceptó un JWT válido con el rol
  administrativo esperado.
- Los recorridos Light y Blockchain se completaron bajo el acceso protegido.
- El lock de mantenimiento bloqueó sesiones válidas de usuario y administrador
  y permitió recuperar ambos accesos al deshabilitarlo.
- La línea base de cierre registró el nodo y los 29 pods preparados sin
  reinicios, nueve PVC `Bound` y observabilidad disponible.
- `ISSUE-001` permanece mitigada y su resolución se traslada a `v0.0.13`.
- La revocación controlada de un certificado administrativo desechable se
  realizará en `v0.0.14`.

[Detalle completo del cierre de v0.0.12](releases/v0.0.12.md).

## v0.0.11 - Validadores con evidencia y renovación del frontend

- Se añadieron endpoints de recomendación de modelos económicos mediante un
  router de API.
- Se renovaron el tema de login de Keycloak, el estilo del frontend y la
  presentación de los resultados de validación.
- Se incorporó soporte en español e inglés.
- Se añadió monitorización de MongoDB y Kafka mediante Kafdrop.
- Se separaron los usuarios administradores y normales y se adoptó un usuario
  de aplicación para las APIs.
- Se centralizaron los modelos Pydantic y las funciones comunes.
- Los validadores quedaron clasificados como:
  `LLM_MEMORY_VALIDATION`, `LLM_SEARCH_VALIDATION`,
  `RAG_EVIDENCE_VALIDATION`, `DETERMINISTIC_VALIDATION` y `HUMAN`.
- Se creó el servicio `evidence-search`, con proveedor de búsqueda abstraído,
  soporte de Exa, perfiles de dominios preferidos, caché y descarga de contenido
  en chunks para los validadores RAG.
- Se configuró un validador RAG con dominios preferidos y dos validadores RAG
  adicionales, con modelos distintos, sin esa restricción.
- Los validadores con búsqueda online admiten los modos `LOCAL`, `NONE`,
  `EXT_OFFICIAL_FIRST` y `EXT_ONLY_OFFICIAL`.
- El generador de aserciones limita cada aserción a un solo hecho y usa las
  categorías estándar a lo largo de toda la cadena.
- Traefik pasó a ser el Ingress común de los entornos local y productivo.

La fuente histórica dejó sin confirmación la prueba de que el modo Light no
envía validaciones cuando los validadores no superan el health check.

## v0.0.10 - Configuración de validadores y protocolo de aserciones v2

- La configuración de cada validador se almacena en IPFS y su hash queda
  registrado en blockchain durante el alta, la actualización y la baja.
- El contrato emite `new_validator_config` y permite recuperar validadores con
  sus hashes de configuración.
- `validate-assertions` sincroniza la configuración registrada al arrancar,
  al cambiar la configuración administrativa y al dar de baja un validador.
- `news-chain` expone los validadores, escucha los cambios on-chain, recupera
  la configuración de IPFS y publica los eventos correspondientes en Kafka.
- `news-handler` mantiene una caché de validadores, la actualiza mediante
  eventos y guarda la configuración aplicable junto con cada validación.
- Se añadieron consultas por hash, proveedor y modelo, con recuperación
  opcional de validaciones y enlaces a sus órdenes.
- Gateway protege y enruta los nuevos endpoints con el mismo modelo de seguridad
  que el resto de la API.
- El frontend permite listar validadores, consultar su configuración y navegar
  desde sus validaciones hasta las órdenes relacionadas.
- Los modelos Pydantic compartidos se trasladaron al módulo común.
- Se introdujo el protocolo de aserciones v2 para generación, validación, modo
  Light y blockchain, con payloads enriquecidos, contexto de búsqueda,
  selección de dominios, caché y respuestas RAG.
- Los servicios de aserciones, validación, cadena y búsqueda de evidencias
  adoptaron la nueva forma del payload y persisten los metadatos de evidencia.

La configuración versionada de un validador contiene nombre, tipo, proveedor,
modelo, fechas de alta y actualización, fecha de baja y estado.

## v0.0.9.1 - Consumo efectivo de cuotas

- Las cuotas se descuentan al consumir el servicio.
- `news-handler` procesa los eventos recibidos y genera las aserciones
  correspondientes.

## v0.0.9 - Rate limit y administración de usuarios

- Se incorporó control de claves y rate limiting.
- Los usuarios disponen de límites de consumo para generación de aserciones y
  validaciones.
- Se añadió un módulo administrativo para gestionar nuevos usuarios.
- Se actualizaron las pruebas Python.
- Gateway deriva y aplica automáticamente el `client_id` en los endpoints de
  órdenes.
- El frontend restringe la visibilidad de las órdenes al cliente efectivo.

## v0.0.8 - Gateway, Keycloak y preparación productiva

- Se optimizaron y endurecieron los Dockerfile.
- Se integró Keycloak.
- Se incorporó un Gateway único, con APIs públicas e integración con Keycloak.
- Nginx dirige las llamadas exclusivamente a través del Gateway.
- Kafka funciona en modo KRaft, sin ZooKeeper.
- Se añadieron validación estricta del issuer, hostname y HTTPS.
- La configuración volátil se trasladó a variables de entorno y se añadieron
  ficheros `.env` de ejemplo sin secretos.
- Las pruebas automáticas validan las llamadas de creación y consulta de
  órdenes obteniendo previamente un token OAuth.
- Se prepararon los perfiles y la configuración de despliegue productivo.
