# Source Router

Servicio interno usado exclusivamente por `RAG_EVIDENCE_VALIDATION + LOCAL`.
Descubre dominios reales, clasifica candidatos con enums cerrados, aplica elegibilidad
geográfica y ranking determinista, y separa dos memorias en MongoDB:

- `domain_profiles_v1`: propiedades estables del dominio (`source_type`,
  `authority_level`, jurisdicciones, temas, tipos de evidencia e idiomas).
- `source_routes_v2`: rutas reutilizables formadas por `topic_code`,
  `evidence_kind` y jurisdicción canónica; solo contienen referencias y puntuaciones
  propias de esa ruta.

```text
RouteSignature -> source_routes_v2 -> FRESH -> unir DomainProfile -> ranking
                                  `-> MISSING/STALE -> SearchProvider -> LLM batch
                                                     -> eligibility -> upsert
```

## API

`POST /routes/resolve` acepta `topic_code`, `evidence_kind`, `jurisdiction` y
`language`. Todos salvo el idioma son vocabularios cerrados de
`routing-taxonomy-v1`. Devuelve `route_key`, `route_state`, `router_version` y
`sources[]` con dominio, tipo, autoridad, jurisdicciones, puntuación y versión
del perfil. Una ruta `FRESH` no realiza llamadas externas.

La clave es:

```text
route-v2|routing-taxonomy-v1|TOPIC_CODE|EVIDENCE_KIND|JURISDICTION_KEY
```

Texto, entidades y fechas no fragmentan esta memoria temática. Esos datos aparecen
después en la consulta concreta de Evidence Search.

`GET /routes` admite filtros `route_key`, `topic_code`, `evidence_kind`,
`jurisdiction_key` y `limit`. `GET /routes/{route_key}` recupera una ruta exacta.
Ambos endpoints son Mongo-only y nunca ejecutan discovery o LLM.

El clasificador no puede añadir dominios ni decidir veracidad. Un candidato con
tema o evidencia `NONE`, autoridad desconocida/no admitida o jurisdicción
incompatible se descarta. Un refresh fallido puede reutilizar una ruta `STALE`;
un `MISSING` fallido no fabrica dominios.

Variables de persistencia: `SOURCE_ROUTES_COLLECTION=source_routes_v2`,
`SOURCE_DOMAIN_PROFILES_COLLECTION=domain_profiles_v1` y
`SOURCE_ROUTER_VERSION=source-router-v2`.
