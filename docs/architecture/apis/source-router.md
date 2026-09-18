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

## Clasificación parcial y recuperación

La respuesta del LLM se valida por candidato. Los dominios válidos se conservan
entre intentos; se solicita una corrección solo de los inválidos u omitidos,
con un máximo de dos llamadas. Un error de formato o de proveedor en el segundo
intento tampoco elimina los resultados válidos del primero. No se aceptan dominios
que no aparezcan en el descubrimiento.

El prompt explicita las restricciones de cada jurisdicción. La normalización
solo elimina redundancias inequívocas (por ejemplo, `COUNTRY/ES` con
`jurisdiction_code=ES`). No elimina una región real ni inventa códigos ausentes
o países miembros de una entidad supranacional; esos casos requieren corrección
del clasificador.

Para los dominios descubiertos cuya clasificación falla se pueden reutilizar
perfiles existentes de `domain_profiles_v1`. Deben tener la misma versión del
router, una verificación más reciente que `SOURCE_ROUTE_REFRESH_SECONDS`,
incluir tema y tipo de evidencia, y superar las reglas de autoridad, tipo de
fuente y jurisdicción. Esta recuperación no actualiza la fecha de verificación
del perfil. No incorpora dominios sin clasificar ni cambia LOCAL a búsqueda externa.

Las rutas parciales o recuperadas llevan `degraded=true` y caducan como máximo
en cinco minutos para permitir reconstruirlas. El diagnóstico se conserva en
MongoDB y en respuestas de caché. Una respuesta sin candidatos elegibles no crea
una ruta vacía con caducidad de 30 días; si existe una ruta anterior se reutiliza
como `STALE`.

`diagnostic_code` distingue `CLASSIFICATION_PARTIAL`, `CLASSIFICATION_FAILED`,
`PROFILE_FALLBACK`, `NO_DISCOVERY_CANDIDATES` y `NO_ELIGIBLE_SOURCES`.
`diagnostics` enumera dominios descubiertos, clasificados, rechazados por
elegibilidad, fallidos y recuperados de perfiles. El validador conserva estos
campos en `evidence_search_response.route`, y continúa buscando evidencias cuando
la respuesta degradada contiene fuentes.

Los logs incluyen la clave de ruta, consulta y URLs del descubrimiento, errores
por candidato y el JSON del candidato rechazado (limitado a 4000 caracteres).
No se almacena la respuesta cruda completa del proveedor. Esta traza permite
distinguir ausencia de resultados, errores de esquema y rechazos de elegibilidad.

Variables de persistencia: `SOURCE_ROUTES_COLLECTION=source_routes_v2`,
`SOURCE_DOMAIN_PROFILES_COLLECTION=domain_profiles_v1` y
`SOURCE_ROUTER_VERSION=source-router-v2`.
