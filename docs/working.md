Trabaja sobre el repositorio `trust-news`, rama `postTFM`.

Objetivo: implementar la corrección y evolución arquitectónica de `ISSUE-015 - Selection of local evidence sources lacks proven regional relevance`.

La solución NO debe limitarse a añadir más dominios al perfil `LOCAL` actual.

La corrección propuesta consiste en evolucionar el modelo desde:

```text
perfil estático en Mongo
→ scoring local
→ include_domains
→ Evidence Search
```

hacia:

```text
clasificación de la aserción
→ Source Discovery dinámico
→ Source Router
→ cache/memoria de rutas
→ Evidence Retrieval dirigido
→ RAG Validator
```

La finalidad es resolver el problema de ISSUE-015 de forma generalizable: una afirmación sobre una región, país, categoría o autoridad que Assermetry nunca haya visto antes debe poder descubrir dinámicamente las fuentes pertinentes sin depender de que previamente exista una allowlist exhaustiva en MongoDB.

## Contexto del problema

Actualmente `ISSUE-015` evidencia que el modo `LOCAL` puede priorizar fuentes oficiales irrelevantes geográficamente.

Ejemplo de regresión:

```text
Aserción:
"Catalunya supera ocho millones de habitantes."

Clasificación:
SOCIAL
DEMOGRAPHICS
ES-CT
official/statistics
```

La fuente esperable debe ser aproximadamente:

```text
Idescat
> INE
> Eurostat
> organismos estadísticos internacionales
```

pero el sistema puede seleccionar fuentes oficiales extranjeras sin relación con Catalunya debido al scoring del perfil precargado.

El problema no es solamente la ausencia de `idescat.cat`.

El problema arquitectónico es que la selección depende de una lista estática de dominios que intenta anticipar todas las combinaciones posibles de:

```text
categoría
subcategoría
claim type
país
región
entidad
tipo de autoridad
```

Eso no escala globalmente.

La solución de ISSUE-015 debe evolucionar el sistema hacia descubrimiento dinámico de fuentes.

# Arquitectura objetivo

Implementar conceptualmente:

```text
EnrichedAssertion
      ↓
Source Route Signature
      ↓
Route Cache
   ┌───────┴───────┐
   │               │
  HIT             MISS
   │               │
   │        Source Discovery
   │               ↓
   │        Candidate Sources
   │               ↓
   │          Source Router
   │               ↓
   │          Top N sources
   │               ↓
   │         persist route
   └───────────────┬────────────
                   ↓
           Evidence Retrieval
                   ↓
             includeDomains
                   ↓
             Evidence chunks
                   ↓
              RAG validator
```

Distinguir claramente dos fases.

## Fase 1 — Source Discovery

Pregunta:

```text
¿Quién debería saber esto?
```

No busca todavía validar TRUE/FALSE.

Busca fuentes/autoritades potencialmente relevantes según:

```text
category
subcategory
claim_type
location
entity
temporal context
preferred source types
criticality
```

## Fase 2 — Evidence Retrieval

Pregunta:

```text
¿Qué dicen esas fuentes sobre esta aserción concreta?
```

Aquí se reutiliza el mecanismo existente:

```text
include_domains
→ Exa/Tavily
→ resultados
→ chunks/evidence
→ RAG validator
```

La fase actual de evidence retrieval debe reutilizarse tanto como sea posible.

# 1. No usar Mongo como universo cerrado de fuentes

La colección actual `evidence_domain_profiles` NO debe seguir siendo condición necesaria para descubrir fuentes en el nuevo flujo.

Mongo debe evolucionar de:

```text
lista estática de dominios permitidos
```

a:

```text
memoria/cache de rutas de fuentes descubiertas
```

No eliminar necesariamente todavía las colecciones/profile existentes si son necesarias para compatibilidad o tests legacy.

Pero el nuevo flujo dinámico no debe requerir que un dominio estuviera previamente cargado.

# 2. Introducir un Source Router dinámico

Crear un componente claramente separado, preferiblemente dentro de:

```text
api/evidence-search/app/source_router/
```

o estructura equivalente coherente con el proyecto.

Responsabilidades:

```text
- construir route signature
- consultar route cache
- descubrir fuentes cuando no existe cache
- normalizar dominios
- clasificar candidatos
- aplicar eligibility
- rankear
- devolver Top N
- explicar por qué se eligió cada fuente
```

No debe validar la afirmación.

No debe producir TRUE/FALSE/UNKNOWN.

# 3. Source Route Signature

Crear una clave canónica que represente la clase de fuente necesaria.

NO usar directamente el texto completo de la aserción.

Ejemplo:

```json
{
  "claim_type": "official_statistic",
  "subcategory": "DEMOGRAPHICS",
  "country_code": "ES",
  "region_code": "ES-CT"
}
```

Route key:

```text
official_statistic|DEMOGRAPHICS|ES|ES-CT
```

La categoría puede incluirse cuando sea relevante.

La signature debe ser suficientemente estable para que:

```text
"Población de Catalunya en 2023..."
"Población de Catalunya en 2024..."
"Población de Catalunya en 2025..."
```

puedan compartir ruta.

No incluir por defecto el año exacto en la route signature.

El tiempo debe seguir utilizándose en Evidence Retrieval.

Solo incluir dimensión temporal en la ruta cuando afecte a la autoridad/fuente aplicable.

# 4. Route signatures dependientes del claim type

No usar obligatoriamente una única composición para todos los claims.

Ejemplos orientativos:

```text
official_statistic
→ claim_type + subcategory + jurisdiction

public_health
→ claim_type + topic + jurisdiction

law
→ claim_type + jurisdiction

election_result
→ claim_type + jurisdiction + election_type

company_financial
→ claim_type + entity

scientific_result
→ claim_type + scientific_domain

sports_result
→ claim_type + competition/entity
```

Centralizar estas reglas.

# 5. Source Discovery mediante el proveedor de búsqueda actual

Reutilizar la infraestructura existente de:

```text
Exa
Tavily
SearchProvider
search_with_provider(...)
```

No introducir otro proveedor salvo necesidad justificada.

Source Discovery debe construir consultas orientadas a encontrar autoridades, no respuestas factuales.

Ejemplo:

```text
Input:
official_statistic
DEMOGRAPHICS
ES-CT
Catalunya

Discovery queries aproximadas:

official population statistics Catalunya
Catalunya demographic statistics official institution
ES-CT regional statistical office population
```

Para una aserción económica UE:

```text
central bank interest rate EU official authority
European monetary policy official institution
```

El router puede usar un LLM para generar o mejorar queries, si ya existe infraestructura reutilizable, pero el LLM NO debe inventar directamente dominios aceptados sin evidencia externa.

# 6. Los dominios deben proceder de resultados reales

Pipeline obligatorio:

```text
search provider
→ URLs reales
→ normalize_domain()
→ candidatos
→ classification/ranking
```

NO permitir:

```text
LLM inventa:
example-authority.org
```

y se usa sin que haya aparecido en resultados reales.

Esto evita hallucinated sources.

# 7. Candidate Source Model

Normalizar cada candidato a una estructura similar a:

```json
{
  "domain": "idescat.cat",
  "url": "...",

  "source_type": "official_statistics",

  "authority_level": "regional_primary",

  "jurisdiction": {
    "country_code": "ES",
    "region_code": "ES-CT"
  },

  "categories": ["SOCIAL"],
  "subcategories": ["DEMOGRAPHICS"],

  "claim_types": [
    "official_statistic"
  ],

  "languages": [
    "ca",
    "es",
    "en"
  ],

  "source_discovery_score": 0.0,

  "reason": "...",

  "discovered_from": {
    "provider": "exa",
    "query": "..."
  }
}
```

No es obligatorio persistir todos estos campos inicialmente, pero el modelo interno debe permitir explicar la selección.

# 8. Candidate Classification

El router debe clasificar candidatos por:

```text
source type
authority level
jurisdiction
category/subcategory relevance
claim type relevance
entity relevance
language
```

Puede emplear:

```text
reglas deterministas
+
metadatos del provider
+
clasificación LLM
```

pero el resultado debe quedar explicado.

El LLM actúa como clasificador/ranker de candidatos reales, no como generador de autoridades ficticias.

# 9. Eligibility antes del scoring

Esta es una corrección explícita de ISSUE-015.

No dejar que una fuente totalmente ajena geográficamente gane simplemente porque sea oficial.

Aplicar primero eligibility/gating.

Para una afirmación:

```text
official_statistic
DEMOGRAPHICS
ES-CT
```

una fuente oficial estadística de Nueva Zelanda debe poder ser marcada:

```text
NOT_ELIGIBLE
```

por falta de relación jurisdiccional.

No debe simplemente recibir unos puntos menos.

La elegibilidad debe considerar al menos:

```text
claim type
source type
jurisdiction
category/subcategory
```

# 10. Jerarquía geográfica

Implementar una jerarquía explícita.

Para:

```text
region_code = ES-CT
country_code = ES
```

priorizar:

```text
Tier 1
autoridad regional exacta ES-CT

Tier 2
autoridad nacional ES

Tier 3
organización supranacional aplicable
por ejemplo UE/Eurostat

Tier 4
organización global relevante
```

Una autoridad nacional de otro país no debe competir como equivalente.

La selección geográfica debe ser una regla estructural, no solo un bonus pequeño.

# 11. Ranking posterior a eligibility

Una vez filtrados candidatos elegibles, calcular score aproximadamente según:

```text
authority level
jurisdiction specificity
claim type match
subcategory match
source type match
entity match
language
provider relevance
```

No fijar pesos arbitrarios innecesariamente.

Mantener los pesos configurables y versionables.

Guardar reason/matched fields.

Ejemplo esperado:

```text
1 idescat.cat
  regional_primary
  ES-CT exact
  official_statistic
  DEMOGRAPHICS
  score 0.98

2 ine.es
  national_primary
  ES
  official_statistic
  DEMOGRAPHICS
  score 0.91

3 eurostat.ec.europa.eu
  supranational
  EU
  official_statistic
  DEMOGRAPHICS
  score 0.85
```

# 12. Route Cache

Crear una nueva colección Mongo, por ejemplo:

```text
source_route_cache
```

No reutilizar `evidence_domain_profiles` como cache salvo que exista una razón técnica clara.

Documento orientativo:

```json
{
  "route_key": "official_statistic|DEMOGRAPHICS|ES|ES-CT",

  "route_signature": {
    "claim_type": "official_statistic",
    "subcategory": "DEMOGRAPHICS",
    "country_code": "ES",
    "region_code": "ES-CT"
  },

  "sources": [
    {
      "domain": "idescat.cat",
      "rank": 1,
      "authority_level": "regional_primary",
      "routing_score": 0.98
    },
    {
      "domain": "ine.es",
      "rank": 2,
      "authority_level": "national_primary",
      "routing_score": 0.91
    },
    {
      "domain": "eurostat.ec.europa.eu",
      "rank": 3,
      "authority_level": "supranational",
      "routing_score": 0.85
    }
  ],

  "router_version": "source-router-v1",

  "discovery_provider": "exa",

  "created_at": "...",
  "updated_at": "...",
  "expires_at": "..."
}
```

Añadir TTL configurable.

Ejemplo:

```text
SOURCE_ROUTE_CACHE_TTL_SECONDS
```

Un periodo inicial razonable puede ser varios días.

No mezclar este TTL necesariamente con el cache actual de evidencias.

# 13. Cache HIT

Cuando existe route cache válida:

```text
NO ejecutar Source Discovery
```

Usar directamente los dominios seleccionados para Evidence Retrieval.

Esto evita duplicar costes.

# 14. Cache MISS

Cuando no existe route:

```text
Source Discovery
→ Candidate Classification
→ Eligibility
→ Ranking
→ Top N
→ persist route
→ Evidence Retrieval
```

# 15. Cache no equivale a trust

No guardar ni exponer algo similar a:

```text
truth_probability
source_truth_score
```

La cache describe utilidad de routing.

Puede incluir posteriormente métricas como:

```text
times_selected
searches_with_results
usable_evidence_count
last_success
```

pero deben representar:

```text
routing/retrieval usefulness
```

NO veracidad.

# 16. Evidence Retrieval debe reutilizar el flujo actual

Tras obtener las fuentes:

```text
Top N domains
```

continuar con el mecanismo actual:

```text
includeDomains/include_domains
+
assertion query
+
temporal context
+
entities
+
location
```

No duplicar `evidence-search`.

Reutilizar:

```text
build_search_requests()
search_with_provider()
chunker
chunk_ranker
grounding
```

tanto como sea posible.

# 17. El tiempo debe permanecer principalmente en Evidence Retrieval

No crear perfiles por año.

No crear routes como:

```text
DEMOGRAPHICS|ES-CT|2023
DEMOGRAPHICS|ES-CT|2024
DEMOGRAPHICS|ES-CT|2025
```

salvo necesidad especial.

El código actual ya prioriza temporal context al enriquecer queries.

Mantener ese comportamiento.

Ejemplo:

```text
Source Route:
official_statistic|DEMOGRAPHICS|ES|ES-CT

Evidence Query:
población Catalunya 2025
```

# 18. Source criticality

Preparar el diseño para soportar criticidad del claim:

```text
CRITICAL
HIGH
NORMAL
LOW
```

No es obligatorio introducir una taxonomía completa en esta iteración si no existe todavía.

Pero el router debe permitir políticas futuras como:

```text
CRITICAL
→ official/primary required
→ no general fallback

HIGH
→ primary preferred

NORMAL
→ authoritative secondary accepted
```

No usar criticidad como probabilidad de verdad.

# 19. Evolución de los modos actuales

Actualmente existen:

```text
NONE
LOCAL
EXT_OFFICIAL_FIRST
EXT_ONLY_OFFICIAL
```

No romperlos inmediatamente si existen consumidores/tests.

Pero introducir el nuevo comportamiento de forma compatible.

Posibles opciones aceptables:

A)

```text
añadir:
DYNAMIC
DYNAMIC_OFFICIAL_FIRST
DYNAMIC_OFFICIAL_ONLY
```

o B)

evolucionar `LOCAL` internamente hacia cache + discovery dinámico manteniendo el valor externo por compatibilidad.

Antes de elegir, analizar uso actual en:

```text
frontend
validator configs
API
tests
Mongo
bootstrap
```

Preferir compatibilidad.

Documentar la decisión.

# 20. EXT_OFFICIAL_FIRST como base de Source Discovery

El flujo actual `EXT_OFFICIAL_FIRST` ya realiza búsqueda abierta y añade instrucciones de:

```text
official source
government agency
regulator
organismo público
```

y Exa puede usar una categoría de official source.

Reutilizar esta infraestructura.

Pero separar:

```text
Source Discovery
```

de:

```text
Evidence Retrieval
```

Actualmente EXT puede consumir directamente los resultados como evidencia.

La evolución propuesta debe poder hacer:

```text
external search
→ descubrir candidatos
→ seleccionar autoridades
→ segunda búsqueda dirigida
```

# 21. Bootstrap/denylist

No depender de una allowlist global precargada.

Puede mantenerse una pequeña configuración de:

```text
denylist
social networks
content farms
generic platforms
known low-quality domains
```

y opcionalmente unas pocas autoridades globales como bootstrap.

Pero el criterio de aceptación es:

```text
una región desconocida previamente debe poder descubrir fuentes válidas.
```

# 22. Observabilidad

Registrar de forma estructurada:

```text
route_key
cache_hit/cache_miss
source_discovery_queries
candidate_domains
rejected_candidates
rejection_reason
selected_domains
routing_scores
router_version
provider
elapsed time
```

Evitar loggear secretos.

La respuesta de Evidence Search debe conservar información suficiente en:

```text
search_policy
domain_resolution
```

o estructura nueva equivalente para explicar cómo se eligieron fuentes.

# 23. Ejemplos de comportamiento esperado

## Caso 1

```text
Assertion:
"En 2025 Catalunya supera los ocho millones de habitantes."

classification:
SOCIAL
DEMOGRAPHICS
official_statistic
ES-CT
```

Esperado aproximadamente:

```text
Idescat
> INE
> Eurostat
> global statistics
```

No aceptar como Top source una autoridad estadística nacional sin relación con España/Catalunya.

## Caso 2

```text
Assertion:
"El BCE bajó los tipos de interés..."

classification:
ECONOMY
MONETARY_POLICY
central_bank_decision
EU
```

Esperado:

```text
ECB
> relevant EU institutional sources
> authoritative secondary sources
```

## Caso 3

```text
Assertion:
"La OMS declaró una emergencia sanitaria..."

classification:
HEALTH
public_health
GLOBAL
```

Esperado:

```text
WHO
> UN/related international authorities
> authoritative secondary sources
```

## Caso 4

Introducir un país/región no presente en ninguna allowlist del repositorio.

El Source Router debe:

```text
discover
classify
rank
return sources
```

sin requerir modificación previa de Mongo o JSON.

Este test es especialmente importante para demostrar la evolución real de ISSUE-015.

# 24. Tests unitarios

Crear tests separados para:

```text
route signature
cache hit
cache miss
candidate normalization
eligibility
geographic hierarchy
ranking
provider failures
empty discovery
duplicate domains
denylist
```

Casos mínimos:

```text
ES-CT:
regional exact > ES national > EU > global
```

```text
unrelated national authority
→ rejected
```

```text
same route, different assertion year
→ same route key
```

```text
cache hit
→ no Source Discovery provider call
```

```text
cache miss
→ discovery provider called
→ route persisted
```

```text
same candidates in different order
→ same ranking
```

# 25. Tests E2E específicos de ISSUE-015

Añadir pruebas que demuestren que la corrección/evolución de ISSUE-015 funciona end-to-end.

Al menos:

```text
Catalunya demographics
España inflation/statistics
EU monetary policy
global public health
unknown geographic region
```

Los tests no deben depender necesariamente del orden exacto de Internet en tests deterministas.

Separar:

### Deterministic tests

Mock/frozen provider responses.

Verificar:

```text
router ranking
eligibility
cache
include_domains
```

### Live smoke test

Opcional pero recomendable:

usar proveedor real y comprobar que devuelve al menos una autoridad coherente.

No hacer que el suite normal dependa de Internet.

# 26. Compatibilidad con ISSUE-013

ISSUE-013 ya está corregida.

No modificar su semántica.

El Source Router decide:

```text
dónde buscar
```

ISSUE-013/grounding garantiza:

```text
que la evidencia utilizada pertenece realmente a lo recuperado
```

Mantener esa separación.

La arquitectura final debe ser:

```text
Assertion extraction
→ Source Routing
→ Evidence Retrieval
→ Grounding
→ Validation
→ Consensus
```

# 27. Compatibilidad LIGHT/BLOCKCHAIN

El Source Router pertenece a Evidence Search/RAG.

Debe comportarse igual en:

```text
LIGHT
BLOCKCHAIN
```

No introducir lógica distinta según modo de persistencia on-chain.

# 28. Documentación

Actualizar:

```text
docs/issues.md
docs/testing-v0.0.13.md
docs/version.md
```

si corresponde.

En `ISSUE-015` explicar explícitamente que la solución ha evolucionado desde:

```text
corregir ranking de profile LOCAL
```

a:

```text
Source Router dinámico con descubrimiento web y cache de rutas
```

Motivo:

```text
una allowlist estática no escala a cobertura geográfica/temática global.
```

Documentar:

```text
Source Discovery
Source Router
Route Signature
Route Cache
Evidence Retrieval
```

y su separación de responsabilidades.

# 29. Criterios de aceptación de ISSUE-015 evolucionado

ISSUE-015 puede considerarse corregido/evolucionado cuando:

* el sistema no depende de que una fuente relevante esté precargada en Mongo;
* puede descubrir fuentes para una jurisdicción previamente desconocida;
* una fuente nacional de un país no relacionado no puede ganar solo por ser oficial;
* existe jerarquía región > país > supranacional > global;
* Source Discovery y Evidence Retrieval son fases separadas;
* las fuentes candidatas proceden de resultados reales del provider;
* el LLM no puede introducir dominios inexistentes como autoridades sin respaldo del discovery;
* existe route cache;
* un cache HIT evita repetir Source Discovery;
* el tiempo de la aserción continúa enriqueciendo Evidence Retrieval sin crear profiles por año;
* la selección de fuentes queda explicada mediante reason/matched/routing metadata;
* LIGHT y BLOCKCHAIN se comportan igual;
* tests deterministas de Catalunya y otras jurisdicciones pasan;
* existe al menos un test de región/país no presente previamente en la allowlist;
* no se rompe ISSUE-013 ni el grounding existente.

# 30. Alcance: qué NO hacer todavía

No intentar:

```text
crear un crawler mundial
mantener miles de fuentes manualmente
crear profiles por país/región/año
crear un algoritmo de reputación factual de fuentes
entrenar ML específico
```

No convertir ISSUE-015 en un proyecto de crawling.

El objetivo es crear una arquitectura generalizable usando el proveedor de búsqueda existente.

# Forma de trabajo

1. Analiza primero el flujo actual de Evidence Search y los modos `LOCAL`, `EXT_OFFICIAL_FIRST`, `EXT_ONLY_OFFICIAL`.
2. Identifica los puntos mínimos de integración.
3. Propón una estructura de archivos antes de modificar código.
4. Implementa Source Router y Route Cache.
5. Reutiliza SearchProvider actual para Source Discovery.
6. Reutiliza Evidence Retrieval actual para la segunda fase.
7. Añade tests deterministas.
8. Ejecuta regresión completa relevante.
9. Actualiza documentación.
10. Al terminar, entrega un informe con:

```text
- arquitectura anterior
- arquitectura nueva
- archivos modificados
- modelo de route signature
- modelo de cache
- reglas de eligibility
- reglas geográficas
- tests añadidos
- resultados de tests
- compatibilidad mantenida
- limitaciones pendientes
- qué partes del antiguo LOCAL quedan deprecadas
```

No hagas cambios ajenos a ISSUE-015 salvo los estrictamente necesarios para implementar esta evolución de forma coherente.
