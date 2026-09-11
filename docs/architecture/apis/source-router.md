# Source Router

Servicio interno que decide dónde buscar para `RAG_EVIDENCE_VALIDATION + LOCAL`.
Descubre URLs reales mediante `common/search`, clasifica todos los candidatos
en una única llamada a `common/llm`, aplica eligibility geográfica y ranking
deterministas, y recuerda el resultado en Mongo `source_routes`.

```text
RouteSignature → Mongo → FRESH: sources
                      └→ MISSING/STALE: SearchProvider → batch LLM
                                         → eligibility → ranking → Mongo
```

## API

`POST /routes/resolve` acepta `category`, `subcategory`, `claim_type`,
`location`, `entities` y `language`. Devuelve `route_key`, `route_state`,
fuentes y `stale_route_used`. Una ruta FRESH no incurre en llamadas externas.

`GET /routes` admite `route_key`, `claim_type`, `category`, `subcategory`,
`country_code`, `region_code`, `entity` y `limit`. `GET /routes/{route_key}`
recupera una ruta exacta. Ambos GET son Mongo-only y devuelven estado FRESH o
STALE; nunca ejecutan discovery o LLM.

La firma predeterminada es
`claim_type|SUBCATEGORY|COUNTRY_CODE|REGION_CODE`, sin texto ni año. El
classifier no puede añadir dominios y no decide eligibility, selección, rank ni
veracidad. Una jurisdicción nacional ajena se descarta aunque tenga relevancia
semántica máxima.

No hay TTL destructivo. Un refresh fallido reutiliza la ruta STALE existente;
un MISS fallido no fabrica dominios ni usa allowlists.

El pod escucha en 8075 y usa `source-router-config`, `source-router-enc` y
`mongodb-app-secret`. `source-router-enc` contiene las credenciales del LLM y
del proveedor de búsqueda propias de este servicio. No depende de Kafka,
Blockchain ni IPFS.
