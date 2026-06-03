# Evidence Search

## Descripción

`api/evidence-search` busca evidencias externas para validar aserciones. Usa perfiles de dominios preferentes guardados en MongoDB, resuelve dominios relevantes para una aserción y consulta Tavily cuando hay API key configurada. Cachea respuestas para reducir coste y latencia.

## Endpoints

- `GET /health`: devuelve estado básico del servicio.
- `POST /search/evidence`: recibe una aserción y una política de búsqueda, resuelve dominios preferentes, genera queries, consulta Tavily o devuelve dominios seleccionados como fallback, normaliza evidencias y cachea la respuesta.

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
