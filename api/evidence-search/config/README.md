# Evidence domain profiles and normalization

`evidence-search` usa MongoDB únicamente cuando `use_preferred_domains=LOCAL`. Los modos `NONE`, `EXT_OFFICIAL_FIRST` y `EXT_ONLY_OFFICIAL` no consultan estas colecciones ni ejecutan scoring local.

## Colecciones

### `evidence_domain_profiles`

Contiene un documento completo por `profile_id`, con índice único sobre `profile_id`. Cada documento incluye `selection_policy`, `scoring_weights` y el array `domains`. No existe compatibilidad con el antiguo modelo `profile_index/profile_subset` ni con documentos por categoría.

El ejemplo versionado es `evidence-domain-profile-default.json`. Las categorías se identifican exclusivamente mediante el `categoryId` registrado en blockchain y reflejado por `common/category_catalog.py`.

El perfil `default` contiene 1.000 dominios únicos, 100 por categoría. Prioriza ámbitos `global` y `macroregion`; las macroregiones se derivan de ccTLD y los dominios genéricos se consideran globales.

Para regenerarlo desde sitios oficiales catalogados en Wikidata (vía su mirror QLever):

```bash
python scripts/k8s/apis/generate-evidence-domain-profile.py
```

### `evidence_normalization_configs`

Contiene un documento independiente, versionado e indexado por `config_type`, para cada taxonomía off-chain:

- `subcategories`: ID canónico, aliases y `category_ids` compatibles.
- `location_types`: scopes y organizaciones internacionales; países y regiones usan ISO 3166-1/ISO 3166-2.
- `source_types`: IDs canónicos, aliases y confianza por defecto.

El seed es `evidence-normalization-configs.json`. Los perfiles solo pueden referenciar IDs canónicos existentes.

## Carga

Validación sin escribir:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --dry-run
```

Carga o reemplazo atómico por clave, preservando otros perfiles:

```bash
python scripts/k8s/apis/init-evidence-search-domains.py --refresh --confirm
```

Variables relevantes:

```text
MONGO_DBNAME=newsdb
EVIDENCE_DOMAIN_CONFIG_COLLECTION=evidence_domain_profiles
EVIDENCE_NORMALIZATION_CONFIG_COLLECTION=evidence_normalization_configs
EVIDENCE_SEARCH_CACHE_COLLECTION=evidence_search_cache
```

## Flujo LOCAL

Para cada aserción RAG, el servicio normaliza subcategoría, localizaciones y source types; carga el perfil solicitado con fallback a `default`; calcula `final_score`; filtra por `min_score`; limita por `max_domains`; y envía los dominios seleccionados mediante `include_domains`. La política efectiva, sus versiones y el desglose de matching se guardan en `search_policy`.

Si no hay dominios elegibles, solo se hace búsqueda abierta cuando `fallback_to_general_search=true`. `LOCAL` se rechaza para cualquier tipo de validador distinto de `RAG_EVIDENCE_VALIDATION`. El flujo es común a LIGHT y BLOCKCHAIN.
