# Estudio histórico de prompts de Generate Assertions

**Fecha:** 17 de noviembre de 2026. **Estado:** 15 llamadas reales aisladas a OpenRouter; sin cambios de código, configuración ni despliegue.

## Alcance y método

Se compararon los tags `v0.0.13` hacia atrás. Los prompts versionados se agrupan en cinco variantes: `v0.0.13`, `v0.0.12`, `v0.0.9.1`–`v0.0.11`, `v0.0.8`–`v0.0.9` y `v0.0.2`–`v0.0.7`. `v0.0.1` carece de ConfigMap versionado y no permite reconstruir su prompt efectivo. Dentro de cada grupo, el texto del prompt del ConfigMap es idéntico. Se probó el tag más reciente de cada grupo. Para `v0.0.12` y `v0.0.13` también se ejecutó desde un archivo temporal la función histórica `build_assertions_prompt`, con su catálogo y configuración del tag; los tags anteriores componen `PROMPT + Texto a analizar` directamente.

Las dos entradas son **sintéticas y versionadas**: [caso corto de 78 caracteres](../../tests/data/benchmark/resources/cases/official-gold-v0/01-es-population-final-true-v1.json) y [caso mediano de 449 caracteres con cuatro afirmaciones](../../tests/data/benchmark/resources/cases/v_comptability/eu-news-2025-v1.json). El segundo caso se ejecutó dos veces. No se enviaron noticias de artefactos locales no versionados. La revisión automática rechazó ese primer origen por posible contenido privado; la alternativa versionada permitió completar la prueba sin ese riesgo.

Se usó `openai/gpt-5-nano` en las 15 solicitudes, a través de OpenRouter, para reducir el efecto del cambio de modelo. En `v0.0.7`–`v0.0.12` se envió el prompt histórico como texto y sin esquema impuesto por la API, siguiendo la ruta OpenRouter de esos tags. Se fijó la temperatura en 0,1 para todas esas variantes; algunas versiones antiguas usaban 0,3 en su configuración histórica. En `v0.0.13` se envió su `json_schema` estricto y `provider.require_parameters`, como hace el cliente común. No hubo reintentos ni reparaciones: una petición HTTP por medición. El tiempo es de solicitud a respuesta completa; no incluye Kafka, administración, validación posterior ni interfaz. Las duraciones proceden de reloj monotónico y los tokens y costes de `usage` del proveedor.

## Evolución del trabajo solicitado

| Tags | Prompt base en ConfigMap | Petición real con caso mediano | Salida y taxonomía exigidas | Proveedor/modelo versionados |
| --- | ---: | ---: | --- | --- |
| `v0.0.2`–`v0.0.7` | 577 caracteres | 1.046 caracteres; 256 tokens de entrada | Array JSON de `idAssertion`, `text`, `categoryId`; diez categorías generales. | OpenRouter / `arcee-ai/trinity-large-preview:free` |
| `v0.0.8`–`v0.0.9` | 593 | 1.062; 259 tokens | Igual, con un pequeño ajuste de redacción sobre el contexto mínimo. | Gemini / `gemini-2.5-flash`; el ConfigMap también contiene Qwen para OpenRouter, inactivo. |
| `v0.0.9.1`–`v0.0.11` | 594 | 1.063; 259 tokens | Igual, con otro pequeño ajuste de redacción. | Gemini / `gemini-2.5-flash`; Qwen sigue configurado para OpenRouter, inactivo. |
| `v0.0.12` | 8.694 | 10.425; 2.364 tokens | Objeto JSON enriquecido: categoría canónica 1–10, `subcategory` libre, contexto de lugares, entidades, tiempo y jurisdicción, `search_hints` y confianza. Todavía no exige `topic_code`, `evidence_kind` ni versión de taxonomía. | OpenRouter / `google/gemini-2.5-flash-lite` |
| `v0.0.13` | 3.841 | 8.967 caracteres de prompt más esquema de 6.590 caracteres; 3.724 tokens de entrada | Objeto JSON con categoría canónica, 32 `topic_code`, 14 `evidence_kind`, `taxonomy_version=routing-taxonomy-v2`, compatibilidad tema/categoría, contexto canónico, jurisdicción y `search_hints`. | OpenRouter / `openai/gpt-5-nano` |

La diferencia importante aparece entre `v0.0.11` y `v0.0.12`: se pasa de extraer y clasificar frases a construir el contexto y las consultas de búsqueda por aserción. `v0.0.13` reduce el texto base respecto a `v0.0.12`, pero añade catálogos de enrutamiento y un esquema estricto que eleva la entrada facturada. Los cambios pequeños entre `v0.0.7`, `v0.0.9` y `v0.0.11` no equivalen a ese salto de contrato.

## Tiempos de cada respuesta

Cada celda incluye segundos, tokens de salida totales (incluido razonamiento) y número de aserciones. `C` es el caso corto; `M1` y `M2` son repeticiones del caso mediano.

| Prompt | C | M1 | M2 | Mediana M1/M2 | Coste de las tres llamadas |
| --- | ---: | ---: | ---: | ---: | ---: |
| `v0.0.7` | 13,393 s · 785 tok · 1 | 27,924 s · 3.300 tok · 4 | 29,955 s · 3.721 tok · 4 | 28,940 s | USD 0,00315805 |
| `v0.0.9` | 7,821 s · 641 tok · 1 | 14,725 s · 1.748 tok · 1 | 25,384 s · 2.778 tok · 4 | 20,055 s | USD 0,00210290 |
| `v0.0.11` | 11,453 s · 963 tok · 1 | 26,588 s · 2.841 tok · 4 | 20,361 s · 1.884 tok · 4 | 23,475 s | USD 0,00231130 |
| `v0.0.12` | 22,012 s · 2.325 tok · 1 | 51,625 s · 7.258 tok · 4 | 38,762 s · 5.495 tok · 4 | 45,194 s | USD 0,00618145 |
| `v0.0.13` | 28,189 s · 4.148 tok · 1 | 37,267 s · 5.512 tok · 4 | 51,108 s · 8.168 tok · 4 | 44,188 s | USD 0,00736449 |

**Total:** 15 llamadas completadas, 15 respuestas JSON parseables, ninguna llamada de reparación; coste reportado por el proveedor: **USD 0,02111819**. Las seis respuestas enriquecidas de `v0.0.12` y `v0.0.13` pasan sus modelos Pydantic históricos. La mediana de solo dos respuestas medianas es descriptiva; no se calcula p95 ni se presenta como estimación de producción.

En el caso mediano, los tokens de razonamiento fueron 4.224–5.952 en `v0.0.12` y 4.352–7.040 en `v0.0.13`, una parte mayoritaria de la salida facturada. Esto acompaña el aumento de tiempo y coste, aunque no permite separar cuánto proviene del texto del prompt, del esquema, del número de campos o del comportamiento interno del modelo.

## Campos y taxonomía observados

- `v0.0.7`, `v0.0.9` y `v0.0.11` devolvieron solo `idAssertion`, `text` y `categoryId`: ningún `topic_code`, `evidence_kind`, contexto o búsqueda. La primera repetición mediana de `v0.0.9` devolvió una sola aserción de cuatro esperadas; por tanto, una respuesta rápida también puede omitir hechos.
- `v0.0.12` devolvió contexto, `search_hints`, `context_confidence` y `subcategory`, sin taxonomía de enrutamiento. En las dos repeticiones medianas produjo cuatro aserciones.
- `v0.0.13` devolvió cuatro aserciones medianas con categorías `[5, 9, 8, 3]` y temas `[HEALTH_PUBLIC_HEALTH, ENVIRONMENT, CULTURE, EDUCATION]`, compatibles con su catálogo. `evidence_kind` cambió entre las dos repeticiones, aunque los temas y categorías coincidieron. Su respuesta corta usó `categoryId=10`, `topic_code=DEMOGRAPHY` y `evidence_kind=STATISTICAL_DATA`.

## Interpretación y siguiente medición

La muestra respalda que **el salto de extracción simple a salida enriquecida coincide con más entrada, más salida y mayor latencia** bajo un modelo fijo. Sitúa el cambio principal en `v0.0.12`; `v0.0.13` añade taxonomía y formato estricto, con un coste mayor, pero no una mediana mediana superior a `v0.0.12` en estas dos repeticiones. No demuestra que el prompt por sí solo cause las latencias actuales: entre tags también cambió el proveedor/modelo histórico y aquí el formato de salida cambia con el contrato. Tampoco se ha medido una noticia larga ni una orden real que tarde 90 s.

Para atribuir el problema de artículos largos, la siguiente prueba debería usar un artículo **explícitamente autorizado para su envío al proveedor** o un caso sintético largo versionado, con igual modelo, formatos de salida controlados y trazas de cada intento, reparación y validación. Este estudio no justifica por sí solo activar una arquitectura en dos fases; primero habría que comparar el tiempo y la calidad del resultado completo.
