# API Gateway

## Descripción

`api/gateway` expone la API pública unificada bajo `root_path=/backend`. Valida tokens JWT de Keycloak y reenvía las peticiones autenticadas a los microservicios internos de órdenes, generación de aserciones, IPFS y blockchain. También calcula el `client_id` efectivo a partir del token y propaga permisos de administración.

## Endpoints

- `GET /auth/is-admin`: devuelve si el usuario autenticado tiene el rol `trust-admin`.
- `POST /assertions/generate`: reenvía el texto a `generate-asertions` (`/extraer`) e inyecta `client_id` para control de cuotas.
- `POST /orders/publishNew`: crea una orden nueva en `news-handler` para generar aserciones y continuar el flujo de validación.
- `POST /orders/publishWithAssertions`: crea una orden en `news-handler` usando aserciones pre-generadas.
- `POST /extract_text_from_url`: reenvía la extracción de texto de URL a `news-handler`.
- `GET /orders/list`: lista órdenes desde `news-handler`; si el usuario es admin y `view_all=true`, permite ver todas.
- `GET /orders/{order_id}`: recupera una orden concreta, propagando `client_id` y flag `admin`.
- `GET /orders/checkOrderConsistency/{order_id}`: reenvía la comprobación de consistencia Order/IPFS/Blockchain.
- `GET /orders/{order_id}/events`: recupera eventos de una orden desde `news-handler`.
- `GET /ipfs/{cid}`: recupera contenido de IPFS mediante el servicio IPFS.
- `GET /blockchain/tx/{hash}`: consulta una transacción en `news-chain`.
- `GET /blockchain/block/{block_id}`: consulta un bloque en `news-chain`.
- `GET /blockchain/post/{post_id}`: consulta un post registrado en el contrato.
- `GET /validators/cache`: lista validadores cacheados desde `news-handler`.
- `GET /validators/cache/{validator_hash}`: recupera detalle de un validador cacheado.
- `GET /validators/cache/{validator_hash}/validations`: recupera validaciones asociadas a un validador, con filtros opcionales por proveedor/modelo.

## Daemons

No arranca consumidores ni productores propios. Su cometido es actuar como proxy HTTP autenticado.

## Inicialización

Al arrancar carga `.env`, configura logging, construye URLs internas de microservicios y URLs de Keycloak. En cada petición protegida descarga el JWKS de Keycloak, valida firma e issuer del JWT, y usa los claims para calcular identidad y rol de administración.

## Variables de entorno

- `LOG_LEVEL`: nivel de logging.
- `NEWS_HANDLER_URL`: URL interna del orquestador de órdenes.
- `NEWS_CHAIN_URL`: URL interna del servicio blockchain.
- `IPFS_API_URL`: URL interna del servicio IPFS.
- `GENERATE_ASSERTIONS_URL`: URL interna del generador de aserciones.
- `KEYCLOAK_ISSUER_URL`: issuer público exacto que debe contener el token.
- `KEYCLOAK_JWKS_URL`: URL interna completa usada para descargar las claves
  públicas de Keycloak. No altera el issuer que se valida.
- `KEYCLOAK_SERVER_INNER_URL`: compatibilidad con configuraciones antiguas; solo
  se utiliza para construir la URL JWKS cuando `KEYCLOAK_JWKS_URL` no está
  definida.
- `KEYCLOAK_REALM`: realm utilizado por el fallback de configuración local.
- `GATEWAY_API_DOCS_ENABLED`: habilita `/docs`, `/redoc` y `/openapi.json`.
  Los overlays productivos lo establecen a `false`.
- `PORT`: puerto de uvicorn si se ejecuta directamente.
