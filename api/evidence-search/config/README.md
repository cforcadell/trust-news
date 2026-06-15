# Evidence Domain Profiles Loader

Esta carpeta contiene la configuracion de perfiles de dominios preferentes para
`evidence-search` y el cargador que los publica en MongoDB.

## Archivos

- `evidence-domain-profiles.yaml`: seed versionado de perfiles.
- `load-evidence-domain-profiles.py`: cargador hacia MongoDB.

## Que hace el cargador

El cargador reemplaza solo los documentos del `profile_id` indicado dentro de
la coleccion `evidence_domain_profiles`.

No borra toda la coleccion de perfiles. Esto permite tener varios perfiles en
MongoDB, por ejemplo `default`, `custom`, `validator-a`, etc.

Por defecto si borra la coleccion `evidence_search_cache`, porque una recarga
de perfiles puede invalidar resultados cacheados. Usa `--keep-cache` para
conservarla.

## Dry-run

Valida el YAML y muestra el resumen sin escribir en MongoDB:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --dry-run
```

Dry-run para otro perfil:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --dry-run --profile-id custom
```

## Carga real

Cargar o reemplazar el perfil `default`:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --confirm
```

Cargar o reemplazar otro `profile_id`:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --profile-id custom --confirm
```

Conservar la cache:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --confirm --keep-cache
```

Usar otro fichero fuente:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py \
  --source /path/to/profiles.yaml \
  --profile-id custom \
  --confirm
```

## Backends

Por defecto `--backend auto` intenta usar `pymongo` y, si no esta disponible o
falla, cae a `kubectl`.

Forzar `pymongo`:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --backend pymongo --confirm
```

Forzar `kubectl`:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py --backend kubectl --confirm
```

El backend `kubectl` usa por defecto:

```text
pod: mongodb-0
namespace: infra
```

Se puede ajustar con:

```bash
api/evidence-search/config/load-evidence-domain-profiles.py \
  --backend kubectl \
  --mongo-pod mongodb-0 \
  --mongo-namespace infra \
  --confirm
```

## Variables relevantes

El cargador reutiliza la configuracion del script base:

```text
MONGO_DBNAME
EVIDENCE_DOMAIN_CONFIG_COLLECTION
MONGO_URI
MONGO_APP_USERNAME
MONGO_APP_PASSWORD
MONGO_APP_HOST
MONGO_APP_PORT
MONGO_APP_DATABASE
```

Valores por defecto:

```text
database: newsdb
profiles collection: evidence_domain_profiles
cache collection: evidence_search_cache
profile_id: default
```

## Documentos creados

Para cada `profile_id`, el cargador crea un indice y un documento por subset:

```text
profile_index/<profile_id>
profile_subset/<profile_id>/source_types
profile_subset/<profile_id>/categories
profile_subset/<profile_id>/subcategories
profile_subset/<profile_id>/countries
profile_subset/<profile_id>/regions
profile_subset/<profile_id>/cities
profile_subset/<profile_id>/entities
```

## Uso desde validadores

Los validadores que activan dominios preferentes deben enviar a
`evidence-search`:

```json
{
  "search_policy": {
    "use_preferred_domains": true,
    "preferred_profile_id": "default"
  }
}
```

En Kubernetes, el validador lo controla con:

```text
EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=true
EVIDENCE_SEARCH_PREFERRED_PROFILE_ID=default
```

Si `EVIDENCE_SEARCH_PREFERRED_PROFILE_ID` no existe o esta vacio, el validador
usa `default`.

## Despues de cargar

Si `evidence-search` mantiene estado en memoria o quieres asegurar que lee la
configuracion actualizada:

```bash
kubectl rollout restart deployment/evidence-search -n apis
kubectl logs deployment/evidence-search -n apis
```

## Mantenimiento de categorias

`categoryId` es la identidad unica de categoria en blockchain, mensajes,
documentos y perfiles. Los literales son solo etiquetas de presentacion.

Para incorporar una categoria nueva:

1. Registrarla con `TrustNews.addCategory(id, label)` en la red objetivo.
2. Anadir el mismo ID y su etiqueta en `api/common/category_catalog.py`.
3. Anadir las traducciones de presentacion en `web_classic/app/js/i18n.js`.
4. Anadir perfiles `categories.<id>` y `subcategories.<id>.<subcategory>` si corresponden.
5. Registrar o actualizar validadores que soporten el nuevo ID.

No se deben introducir aliases, conversiones desde literales ni rangos fijos
de IDs. El cargador rechaza perfiles que no pertenezcan al catalogo backend.
