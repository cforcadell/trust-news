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

Una fuente sólo es citable cuando Evidence Search descarga el documento,
extrae su texto y genera contextos con `context_id`, `text_sha256`,
`origin=fetched_document` y `citation_eligible=true`. Si la descarga falla o la
extracción de texto está deshabilitada, se conservan URL, título y snippet para
diagnóstico, pero `contexts` queda vacío y `citation_status=unavailable`. Un
snippet del proveedor no constituye evidencia documental citable.

El validador selecciona únicamente `context_id`; no controla la URL ni el texto
persistidos. Validate Asertions reconstruye `evidence_used` desde el contexto
canónico y rechaza identificadores ausentes o ambiguos.

MongoDB solo guarda `evidence_search_cache_v2` con TTL. La clave incluye la
aserción normalizada, el origen, la estrategia completa, los perfiles enrutados
y la configuración del backend de búsqueda, incluida la versión del contrato de
citas. Cambiar cualquiera de ellos separa la entrada de caché. La nueva versión
no reutiliza respuestas antiguas, por lo que no requiere eliminar la colección.

`DELETE /admin/cache` vacía exclusivamente esa caché. Las colecciones antiguas se
eliminan mediante `scripts/k8s/realign-source-routing-mongodb.sh`.
