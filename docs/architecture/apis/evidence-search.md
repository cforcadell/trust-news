# Evidence Search

`api/evidence-search` recupera evidencia concreta. No descubre autoridades, no
clasifica fuentes y no consulta `source-router`.

## API

- `GET /health`: liveness.
- `POST /search/evidence`: recibe una assertion y `search_policy`, ejecuta
  Exa/Tavily mediante `common/search`, normaliza resultados, obtiene texto,
  construye chunks/contextos, rankea y cachea.
- `DELETE /admin/cache`: vacía exclusivamente `evidence_search_cache`.

En modo `LOCAL`, `search_policy.include_domains` es obligatorio y ya viene
resuelto por el validator:

```json
{
  "use_preferred_domains": "LOCAL",
  "include_domains": ["idescat.cat", "ine.es"]
}
```

La búsqueda queda restringida a esos dominios y no hace fallback general. En
`NONE`, `EXT_OFFICIAL_FIRST` y `EXT_ONLY_OFFICIAL` se conserva la planificación
anterior; los modos `EXT_*` delegan la preferencia oficial al proveedor.

Mongo solo guarda la caché de evidencia con TTL. No existen perfiles estáticos
ni seeds. La migración operativa ejecutada por
`scripts/k8s/init-mongodb-server.sh` elimina las antiguas colecciones
`evidence_domain_profiles` y `evidence_normalization_configs`.

Variables principales: `MONGO_*`, `EVIDENCE_SEARCH_CACHE_COLLECTION`,
`EVIDENCE_SEARCH_CACHE_TTL_SECONDS`, `SEARCH_PROVIDER`, `SEARCH_API_URL`,
`API_KEY_PROVIDER`, `SEARCH_TIMEOUT`, `SEARCH_MAX_RETRIES` y las opciones
`EVIDENCE_*` de descarga/chunking.
