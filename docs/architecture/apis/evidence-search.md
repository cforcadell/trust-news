# Evidence Search

## Descripción

`api/evidence-search` busca evidencias externas para validar aserciones. Usa perfiles de dominios preferentes guardados en MongoDB, resuelve dominios relevantes para una aserción y consulta Tavily cuando hay API key configurada. Cachea respuestas para reducir coste y latencia.

## Endpoints

- `GET /health`: devuelve estado básico del servicio.
- `POST /search/evidence`: recibe una aserción y una política de búsqueda, resuelve dominios preferentes, genera queries, consulta Tavily o devuelve dominios seleccionados como fallback, normaliza evidencias y cachea la respuesta.
- `DELETE /admin/cache`: vacía la colección de cache de búsquedas y devuelve el número de documentos eliminados. No elimina perfiles de dominios ni recrea índices.

## Daemons

No ejecuta consumidores ni productores Kafka. Su cometido es responder bajo demanda a validadores RAG o clientes internos.

## Inicialización

En `startup` conecta a MongoDB, inicializa colecciones de perfiles de dominio y cache, y crea índices únicos para documentos de perfiles/subsets e índices de cache con TTL. En `shutdown` cierra MongoDB.

## Variables de entorno

- `MONGO_URI` o variables `MONGO_APP_*`: conexión MongoDB.
- `MONGO_DBNAME`: base de datos.
- `EVIDENCE_DOMAIN_CONFIG_COLLECTION` o `MONGO_EVIDENCE_DOMAIN_PROFILES_COLLECTION`: colección de perfiles de dominio.
- `EVIDENCE_SEARCH_CACHE_COLLECTION`: colección de cache de búsquedas.
- `EVIDENCE_SEARCH_CACHE_TTL_SECONDS`: duración del cache.
- `TAVILY_API_URL`: endpoint de Tavily.
- `TAVILY_SEARCH_DEPTH`: profundidad de búsqueda.
- `TAVILY_INCLUDE_ANSWER`: incluye respuesta sintética de Tavily.
- `TAVILY_INCLUDE_RAW_CONTENT`: incluye contenido bruto.
- `TAVILY_MAX_RESULTS`: máximo de resultados por llamada Tavily.
- `TAVILY_TIMEOUT`: timeout de Tavily.
- `TAVILY_API_KEY`: API key de Tavily. Si no está configurada, el servicio devuelve evidencias fallback basadas en dominios preferentes.

## Preferred domains y normalización

`LOCAL` es el único modo que lee MongoDB y activa scoring. `evidence_domain_profiles` almacena un documento completo por perfil; `evidence_normalization_configs` almacena documentos independientes para `subcategories`, `location_types` y `source_types`. No se admite el esquema legacy por subsets.

`NONE` mantiene búsqueda abierta. `EXT_OFFICIAL_FIRST` y `EXT_ONLY_OFFICIAL` siguen delegando la política de fuentes al proveedor sin scoring local. `LOCAL` solo es válido para `RAG_EVIDENCE_VALIDATION` y se usa igual en LIGHT y BLOCKCHAIN.

La respuesta incluye `search_policy.selected_domains` con score base, score final y señales coincidentes. Las versiones del perfil y taxonomías forman parte de la clave de caché.
