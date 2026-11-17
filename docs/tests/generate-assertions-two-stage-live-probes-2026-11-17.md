# Pruebas reales encadenadas de Generate Assertions

**Fecha:** 17 de noviembre de 2026. **Repositorio:** `d8b97af281d78b7ea871a98d236cfc1119c4feb1`. **Estado:** experimento aislado; ningún cambio en código, configuración, Kafka, base de datos o despliegue.

## Pregunta y diseño

¿Una primera llamada de selección rápida y una segunda de enriquecimiento del lote completo reducen el tiempo de `LEGACY` sin degradar las aserciones ni el contrato V2? Se ejecutaron **11 pruebas, 20 solicitudes reales a OpenRouter**: dos llamadas LEGACY (una por caso) y nueve cadenas de dos llamadas. No hubo reintentos, reparaciones ni solicitudes extra. Ambas fases usaron `openai/gpt-5-nano`, `json_schema` estricto y `provider.require_parameters=true`, igual que la ruta OpenRouter actual; no se pidió `reasoning=minimal` ni se fijó temperatura porque el cliente actual omite temperatura cuando hay esquema estricto. Las peticiones se hicieron directamente al proveedor con el transporte del [benchmark aislado existente](../../tests/llm-benchmark/generate_assertions_isolated.py); no se invocó el servicio.

Los únicos textos enviados fueron estos recursos **sintéticos versionados**: [estadísticas europeas, 255 caracteres](../../tests/data/benchmark/resources/cases/historical/pre-gold-v0/eu-official-statistics-2025-v2.json) y [cuatro países, 449 caracteres](../../tests/data/benchmark/resources/cases/historical/pre-gold-v0/eu-news-2025-v2.json). Son pruebas de regresión, no noticias verificadas. La combinación `F2+H2` del segundo caso se repitió una vez, según el calendario fijado antes de enviar la primera petición. El tiempo de cada llamada se midió con reloj monotónico; coste y tokens provienen de `usage` de OpenRouter. El coste de la campaña fue **USD 0,04562499**.

**Desviación detectada en la auditoría posterior:** el prompt LEGACY pidió máximo 7 aserciones, igual que `F1/F2`, pero su clase Pydantic había capturado el valor por defecto **`maxItems=20`** al importarse; cambiar `MAX_ASSERTIONS` a 7 después no modificó el esquema ya construido. La extracción en dos fases sí envió `maxItems=7`. Ninguna respuesta superó cuatro aserciones, pero la diferencia de esquema y sus tokens impide considerar la línea base una réplica exacta del ConfigMap de producción. Una siguiente comparación deberá fijar `MAX_ASSERTIONS=7` **antes** de importar el módulo. Las conclusiones de tiempo se limitan a las peticiones efectivamente enviadas.

### Prompts y esquemas comparados

| Variante | Instrucciones enviadas | Salida exigida |
| --- | --- | --- |
| `LEGACY` | `PROMPT` del [ConfigMap actual](../../k8s/apis/generate-asertions/configmap.yaml) más `build_assertions_prompt` de [main.py](../../api/generate-asertions/main.py). | `AssertionBatch` completo: texto, categoría, tema, tipo de evidencia, contexto y búsquedas. |
| `F1_rapido` | “Extrae hasta 7 afirmaciones factuales centrales, independientes y verificables … conserva sujeto, tiempo, lugar, cifras y negaciones … texto autónomo y pasaje literal breve … no clasifiques ni enriquezcas”. | `claims[{text,source_excerpts[]}]`; sin taxonomía. |
| `F2_protegido` | Añade criterio de tesis global, exclusión de opinión y contexto accesorio, cuantificadores como “todos” o “100 %”, atribución y conservación de jurisdicción. | El mismo esquema breve. |
| `H1_compacto` | Lote de candidatos, pasajes literales y noticia una vez; catálogo de categorías, compatibilidad tema/categoría, códigos ISO y reglas breves de contexto. | `enriched[{index,categoryId,topic_code,evidence_kind,context,search_hints,context_confidence}]`. |
| `H2_completo` | El mismo lote más catálogo de temas, compatibilidad exacta, tipos de evidencia y contrato completo de jurisdicción actuales. | El mismo esquema; el servidor experimental une los campos semánticos con el texto original seleccionado. |

Ambos enriquecedores recibieron la noticia completa **una sola vez por lote** para conservar el contexto global en estas pruebas cortas. Esto aún no ensaya la estrategia de ventanas para noticias largas. El texto de `F1/F2` fue inmutable después de la primera llamada. Se validaron pasajes literales, cardinalidad, orden, los modelos actuales `Assertion`/`EnrichedAssertion` y `AssertionsDocumentV2` en modo LIGHT. Los esquemas de respuesta tenían 528 caracteres para extracción, 6.070 para enriquecimiento y 6.575 para LEGACY, sin contar el resto del cuerpo HTTP. El prompt LEGACY medía 8.773/8.967 caracteres para los dos casos; `F1`, 646/840; `F2`, 895/1.089. Los prompts de enriquecimiento variaron entre 1.830 y 5.017 caracteres, según versión y candidatos.

## Resultados por prueba

`E` = caso estadístico (3 hechos); `N` = noticia de cuatro países (4 hechos). `t1/t2` son segundos de las llamadas; `tok1/tok2` son tokens totales consumidos por llamada; `USD` es coste total. “Válido” significa que la respuesta llegó hasta `AssertionsDocumentV2`, no solo que era JSON válido.

| Nº | Caso | Prompts | t1 / t2 (s) | Total (s) | tok1 / tok2 | USD | Hechos | Contrato final |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | E | LEGACY | 59,846 / — | 59,846 | 10.026 / — | 0,00271505 | 3 | Válido |
| 2 | E | F1 + H1 | 16,903 / 54,640 | 71,543 | 2.567 / 8.905 | 0,00392905 | 3 | Inválido: `jurisdiction_code` en `COUNTRY` |
| 3 | E | F1 + H2 | 18,015 / 54,044 | 72,059 | 2.371 / 10.660 | 0,00422960 | 3 | Válido |
| 4 | E | F2 + H1 | 26,553 / 45,178 | 71,731 | 3.117 / 8.401 | 0,00392925 | 3 | Inválido: `jurisdiction_code` en `COUNTRY` |
| 5 | E | F2 + H2 | 27,900 / 45,194 | 73,094 | 3.888 / 9.194 | 0,00412882 | 3 | Válido |
| 6 | N | LEGACY | 54,409 / — | 54,409 | 11.548 / — | 0,00331580 | 4 | Inválido: `applicable_country_codes` en `COUNTRY` |
| 7 | N | F1 + H1 | 20,461 / 52,435 | 72,896 | 2.228 / 7.755 | 0,00324050 | 4 | Inválido: códigos duplicados en jurisdicción |
| 8 | N | F1 + H2 | 19,825 / 78,173 | 97,998 | 2.106 / 12.614 | 0,00476687 | 4 | Inválido: `COUNTRY` sin `country_code` |
| 9 | N | F2 + H1 | 27,105 / 76,695 | 103,800 | 3.584 / 11.982 | 0,00546005 | 4 | Inválido: códigos duplicados en jurisdicción |
| 10 | N | F2 + H2 | 26,084 / 85,939 | 112,023 | 3.844 / 10.841 | 0,00484325 | 4 | Inválido: `HEALTH_PUBLIC_HEALTH` con categoría 9 |
| 11 | N | F2 + H2, repetición | 18,497 / 76,385 | 94,882 | 2.982 / 12.562 | 0,00506675 | 4 | Válido |

La fase 1 tardó **16,9–27,9 s** (mediana 20,5 s); la fase 2, **45,2–85,9 s** (mediana 54,6 s). El proveedor informó 99.904 tokens de razonamiento entre 111.440 tokens de salida en las 20 llamadas (**89,6 %**). La primera fase fue breve en texto visible, pero consumió 1.536–3.392 tokens de razonamiento por llamada; el ahorro de su respuesta estructurada no compensó la segunda generación. La mediana de las cadenas de E fue 71,895 s (**+20,1 %** frente a la única llamada LEGACY de E); la de N, 97,998 s (**+80,1 %** frente a la única llamada LEGACY de N). Son diferencias descriptivas, no intervalos de confianza; la línea base N además fue inválida.

### Cobertura, taxonomía y contexto

La primera fase encontró 3/3 hechos de E y 4/4 de N en **todas las nueve cadenas**; todas las citas `source_excerpts` eran subcadenas literales. Conservó “inflación negativa”, “inferior al 0 %”, “100 %”, “prohibió por completo” y “eliminó”. Ninguna salida añadió una afirmación ajena al texto. Este resultado mide selección sobre textos muy breves; no demuestra que seleccionará los hechos centrales de noticias extensas.

En el caso E, LEGACY y las dos cadenas válidas coincidieron con las tres etiquetas gold de categoría, tema y evidencia, y con el país de cada aserción. Las búsquedas sugeridas no estaban vacías. En N, la cadena válida Nº 11 acertó **3/4 categorías gold**, **4/4 temas**, **1/4 tipos de evidencia** y **4/4 países**. La categoría de educación fue 3, permitida por la taxonomía, pero distinta de la gold 10; los tipos de evidencia para Alemania, Italia y España tampoco coincidieron con gold. Son coincidencias de etiqueta diagnósticas, no una medida de verdad factual: el conjunto N es sintético y su evidencia esperada no se comprobó con buscador real.

Hay una pérdida de autonomía en el texto: en las cuatro afirmaciones de N, tanto LEGACY como todas las primeras fases incluyeron **2025 solo en la primera**. La salida válida Nº 11 tampoco recuperó el año en `context.temporal_context` de las otras tres; las marcó `unknown` y varias consultas omitieron la fecha. Un `search_hints` no vacío no demuestra utilidad para Evidence Search. Los modelos V2 aceptan esta salida, pero no cumple el objetivo de conservar todo el tiempo relevante. En E, las tres salidas finales válidas conservaron 2025 en los tres textos.

Los errores dominantes fueron semánticos, aunque OpenRouter devolvió JSON conforme al esquema sintáctico. `H1` obtuvo **0/4 documentos válidos**; en E puso a la vez `country_code` y `jurisdiction_code`, y en N añadió además `applicable_country_codes`. `H2` obtuvo **3/5**: una respuesta N dejó `country_code` nulo y otra asignó una pareja tema/categoría prohibida; su repetición sí pasó. LEGACY obtuvo **1/2**: N falló por `applicable_country_codes`. Los errores explican por qué el esquema estricto del proveedor no sustituye los validadores de dominio del repositorio. No se hicieron reparaciones; producción puede hacerlas y aumentar tiempo y coste.

## Lectura frente a la estrategia de dos fases

El [estudio histórico](generate-assertions-prompt-history-2026-11-17.md) había localizado el salto de complejidad en contexto, taxonomía y búsquedas. Este experimento lo concreta: quitar esos campos de la **primera** llamada acelera la selección, pero moverlos a una **segunda llamada secuencial** no acelera el resultado final en estos dos casos. La fase de enriquecimiento generó el mayor tiempo y el mayor coste. La estrategia de [dos fases](generate-assertions-two-stage-strategy-2026-11-17.md) conserva el contrato externo y sigue siendo una arquitectura posible, pero **estas pruebas no justifican activarla ni afirmar que mejora latencia**.

Antes de implementarla, la siguiente comparación útil requiere noticias sintéticas largas con hechos decisivos distribuidos a lo largo del texto y una línea base emparejada, repetida y válida. Hay que exigir: cobertura de hechos centrales, citas literales, año/jurisdicción autónomos en cada `text`, compatibilidad tema/categoría, salida `AssertionsDocumentV2`, búsquedas útiles en Evidence Search, tiempo total incluyendo reparaciones y coste por orden. Ensayar `H2` con una entrada por ventanas y contexto global explícito, y un esquema semántico más compacto, es una hipótesis de mejora; debe medirse con el mismo modelo y sin relajar los modelos/ICs. Un paso adicional de comprobación local solo puede rellenar campos deterministas (índices y versión), no inventar año, jurisdicción, tema ni evidencia. Mientras no se supere esa comparación, la propiedad propuesta debe seguir con `LEGACY` como valor inicial.

**Límites:** dos noticias de 255/449 caracteres, una línea base por caso, una sola repetición, mismo proveedor/modelo y sin red del servicio, Kafka, cuota, búsqueda real ni despliegue. El desajuste `maxItems` de LEGACY también limita la equivalencia. Los tiempos absolutos incluyen variabilidad del proveedor; no permiten inferir p95 ni una mejora para noticias largas. La trazabilidad local detallada (prompts, respuestas y `usage`) queda en `/tmp/generate-assertions-two-stage-20261117/`, fuera del repositorio y sin credencial en los resultados.
