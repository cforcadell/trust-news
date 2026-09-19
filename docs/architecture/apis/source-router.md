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

## Flujo de resolución e interconexión

El llamador habitual es `validate-asertions`. Para una aserción en modo LOCAL
construye el payload a partir de `assertion.topic_code`,
`assertion.evidence_kind`, `assertion.context.jurisdiction` y el idioma del
contexto. `source-router` no recibe el texto de la aserción, entidades ni
fechas: esos datos permanecen en `evidence-search` y se usan al construir la
consulta final.

La resolución sigue estas etapas:

1. `signatures.py` construye `RouteSignature` y la `route_key` canónica.
2. Si existe una ruta cuya `refresh_after` aún no ha vencido, se recuperan sus
   perfiles de dominio y se recalcula el ranking sin llamar a buscador ni LLM.
3. Para una ruta `MISSING` o caducada (`STALE`), `query_builder.py` genera la
   consulta de discovery a partir del tipo de evidencia, tema y jurisdicción.
   Los códigos ISO siguen siendo la representación interna y la identidad de la
   ruta, pero se expanden a nombres geográficos completos —incluida la variante
   del idioma solicitado cuando está disponible— antes de llamar a Exa o
   Tavily. `search_with_provider` deduplica los resultados por dominio
   normalizado.
4. `classifier.py` clasifica todos los candidatos en un lote LLM. La salida se
   valida por candidato contra `SourceClassification`; el LLM describe
   propiedades y compatibilidad, pero no decide la selección ni la veracidad.
5. `eligibility.py` aplica reglas deterministas: coincidencia de tema y
   evidencia, tipo de fuente permitido por `EVIDENCE_SOURCE_TYPES`, cobertura
   jurisdiccional y autoridad distinta de `UNKNOWN`/`OTHER`.
6. Las clasificaciones elegibles actualizan `domain_profiles_v1` y se convierten
   en `RouteCandidate`. `ranking.py` las ordena; el límite por defecto es
   `SOURCE_ROUTER_MAX_SOURCES` (8).
7. Se persiste la ruta y se devuelve `ResolveRouteResponse`.

La conexión posterior es unidireccional: `validate-asertions` pasa `sources[]`
como `search_policy.preferred_sources` a `evidence-search`; este último crea
peticiones con `include_domains` y nunca llama de nuevo a Source Router. Si
LOCAL no recibe fuentes elegibles, la búsqueda se omite con
`no_eligible_local_sources`.

## Contratos y metadata

La metadata se separa deliberadamente entre identidad de ruta, perfil estable y
decisión de selección:

- `RouteSignature` contiene `taxonomy_version`, `topic_code`, `evidence_kind`,
  la `jurisdiction` completa y `jurisdiction_key`. La jurisdicción admite
  `GLOBAL`, `SUPRANATIONAL`, `COUNTRY`, `REGION`, `LOCAL` y `UNKNOWN`, con
  códigos validados según el ámbito.
- `DomainProfile` conserva propiedades reutilizables del dominio: `source_type`,
  `authority_level`, jurisdicciones, temas, tipos de evidencia, idiomas,
  `classification_confidence`, `classification_model`, `profile_version` y
  `last_verified_at`. La actualización combina cobertura previa y nueva; un
  fallback no prolonga `last_verified_at`.
- `RouteCandidate` conserva únicamente los campos dependientes de la ruta:
  coincidencias temática y de evidencia, relevancia semántica, score del
  proveedor, justificación y `base_score`.
- `RoutedSource` es la metadata que cruza el límite hacia Evidence Search:
  dominio, tipo, autoridad, jurisdicciones, temas, evidencias compatibles,
  idiomas, `route_score`, `rank`, `reason` y `profile_version`.

El `route_score` combina autoridad (30%), especificidad geográfica (25%),
coincidencia del tipo de evidencia (16%), tema (14%), relevancia semántica (8%),
confianza de clasificación (5%) y score del proveedor (2%). Se añade un bonus
de 0,03 cuando el idioma solicitado figura en el perfil. Los empates se
resuelven por dominio para mantener resultados reproducibles.

Evidence Search vuelve a copiar esta metadata en cada evidencia: `source_type`,
`authority_level`, `route_score`, `why_selected` y `profile_version`. También
calcula `relationship_to_origin` (`ORIGINAL`, `INDEPENDENT` o `UNKNOWN`), de
modo que la evidencia y la decisión de routing permanecen auditables de extremo
a extremo.

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

`SOURCE_ROUTER_DISCOVERY_MAX_RESULTS` controla los candidatos solicitados por
el router (12 por defecto). La capa compartida de búsqueda respeta ese valor;
`SEARCH_PROVIDER_MAX_RESULTS` es únicamente un guardrail técnico común (50 por
defecto), no el límite funcional de Evidence Search.
