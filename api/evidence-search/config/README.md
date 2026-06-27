# Evidence domain profiles and normalization

`evidence-search` usa MongoDB únicamente cuando `use_preferred_domains=LOCAL`. Los modos `NONE`, `EXT_OFFICIAL_FIRST` y `EXT_ONLY_OFFICIAL` no consultan estas colecciones ni ejecutan scoring local.

## Colecciones

### `evidence_domain_profiles`

Contiene un documento completo por `profile_id`, con índice único sobre `profile_id`. Cada documento incluye `selection_policy`, `scoring_weights` y el array `domains`. No existe compatibilidad con el antiguo modelo `profile_index/profile_subset` ni con documentos por categoría.

El ejemplo versionado es `evidence-domain-profile-default.json`. Las categorías se identifican exclusivamente mediante el `categoryId` registrado en blockchain y reflejado por `common/category_catalog.py`.

El perfil `default` contiene 500 dominios únicos, 50 por categoría. Se genera exclusivamente desde la allowlist curada `official-domain-seed.json`; no consulta Wikidata, Wikipedia, QLever ni otros servicios externos. La política del perfil oficial mantiene `fallback_to_general_search=false`.

### Generador oficial de perfiles

El generador vigente es `scripts/k8s/apis/generate-official-evidence-domain-profile.py`. Su responsabilidad no es descubrir dominios en internet, sino transformar una allowlist curada en un perfil compatible con `evidence-search`.

Entradas por defecto:

- `api/evidence-search/config/official-domain-seed.json`: seed curada de dominios oficiales.
- `api/evidence-search/config/evidence-normalization-configs.json`: taxonomías canónicas de subcategorías, localizaciones y source types.

Salida por defecto:

- `api/evidence-search/config/evidence-domain-profile-official.json`, con `profile_id=official-default`.

Para regenerar el artefacto oficial:

```bash
python scripts/k8s/apis/generate-official-evidence-domain-profile.py
```

Para sustituir el perfil `default` que carga el bootstrap actual:

```bash
python scripts/k8s/apis/generate-official-evidence-domain-profile.py --profile-id default --output api/evidence-search/config/evidence-domain-profile-default.json
```

Opciones CLI:

```text
--seed                         Ruta de la seed curada.
--normalization                Ruta de evidence-normalization-configs.json.
--output                       Ruta del perfil generado.
--domains-per-category         Dominios requeridos por categoría; default 50.
--allow-national-officials     Permite source types nacionales marcados como national/government.
--profile-id                   ID del perfil generado; default official-default.
```

Requisitos de la seed:

- Cada entrada debe tener `official=true`.
- `category_id` debe estar entre 1 y 10.
- `source_types` debe contener IDs existentes en la taxonomía `source_types`.
- `subcategories`, si se informan, deben existir y pertenecer a la categoría indicada.
- Si no se informan subcategorías, el generador asigna subcategorías válidas de esa categoría desde la taxonomía; no inventa IDs.
- `locations` debe usar scopes soportados por la configuración de localizaciones.
- La seed no debe contener dominios duplicados.

Normalización y exclusiones:

- El dominio se extrae desde `domain` o `url`.
- Se pasa a minúsculas, se quita `www.`, se elimina path/query/fragment y se convierte IDNA si aplica.
- Se rechazan redes sociales, blogs y plataformas genéricas: `facebook.com`, `instagram.com`, `linkedin.com`, `tiktok.com`, `twitter.com`, `x.com`, `youtube.com`, `youtu.be`, `blogspot.com`, `wordpress.com`, `medium.com`, `substack.com`, `wikipedia.org` y `wikidata.org`.

Balanceo y scoring:

- El generador selecciona de forma determinista hasta `--domains-per-category` dominios por categoría.
- Si alguna categoría no alcanza el mínimo solicitado, falla explícitamente y no rellena con fuentes no oficiales.
- Score por defecto: `0.96` para fuentes globales, `0.94` para estadísticas oficiales y `0.92` para otras fuentes oficiales aceptadas.
- Cualquier entrada aceptada debe tener score `>=0.85`.
- El perfil generado siempre usa `selection_policy.fallback_to_general_search=false`.

Validación recomendada antes de cargar MongoDB:

```bash
python3 -m py_compile scripts/k8s/apis/generate-official-evidence-domain-profile.py
scripts/k8s/init-mongodb-server.sh --dry-run
```

El antiguo generador basado en Wikidata/QLever queda solo como referencia histórica/deprecada y no debe usarse para regenerar el perfil oficial.

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
