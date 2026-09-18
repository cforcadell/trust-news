# Evidence Search

`api/evidence-search` recupera documentos concretos para validadores RAG. No
descubre autoridades, no clasifica dominios y no consulta `source-router`.

## Contrato v2

`POST /search/evidence` recibe:

- `assertion`: aserción completa de `assertions-document-v2`.
- `origin_document`: URL/dominio de la noticia, o ambos a `null` si se desconocen.
- `search_policy`: una estrategia RAG, límites y `preferred_sources`.

Solo existen tres estrategias:

| Estrategia | Dominios | Plan |
|---|---|---|
| `LOCAL` | `preferred_sources` obligatorio, producido por Source Router | Búsqueda restringida, sin ampliación general |
| `EXT_OFFICIAL_FIRST` | No acepta `preferred_sources` | Petición oficial preferente y después búsqueda general |
| `EXT_ONLY_OFFICIAL` | No acepta `preferred_sources` | Petición solo oficial y filtro determinista posterior por `source_type` |

`NONE` no existe. La búsqueda web autónoma ya está representada por
`LLM_SEARCH_VALIDATION` y no atraviesa este servicio.

La respuesta contiene el plan ejecutado como objetos estructurados, la resolución
de dominios y evidencias normalizadas. Cada evidencia conserva `source_type`,
`authority_level`, `route_score`, `profile_version` y
`relationship_to_origin`. El documento original puede aparecer como contexto,
pero el grounding no lo admite como evidencia decisiva independiente.

MongoDB solo guarda `evidence_search_cache_v2` con TTL. La clave incluye la
aserción normalizada, el origen, la estrategia completa, los perfiles enrutados
y la configuración del backend de búsqueda. Cambiar cualquiera de ellos separa
la entrada de caché.

`DELETE /admin/cache` vacía exclusivamente esa caché. Las colecciones antiguas se
eliminan mediante `scripts/k8s/realign-source-routing-mongodb.sh`.
