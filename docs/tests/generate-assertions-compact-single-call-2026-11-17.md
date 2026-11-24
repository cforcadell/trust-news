# Generate Assertions: una llamada con salida compacta

**Fecha:** 17 de noviembre de 2026. **Estado:** 20 solicitudes reales aisladas a OpenRouter; no se modificó código de producto, configuración ni despliegue.

## Diseño de la prueba

Se comparó el `LEGACY` actual con tres variantes de **una sola llamada**. Todas usaron `openai/gpt-5-nano`, el mismo proveedor OpenRouter, `json_schema` estricto y `provider.require_parameters=true`, sin `reasoning=minimal`, temperatura forzada, reintentos ni reparaciones. `MAX_ASSERTIONS=7` se fijó **antes** de importar `AssertionBatch`, de modo que el esquema LEGACY y los tres compactos tenían el mismo límite. El [ejecutor de prueba](../../tests/llm-benchmark/generate_assertions_compact_probe.py) reutiliza el transporte y las métricas del [benchmark aislado existente](../../tests/llm-benchmark/generate_assertions_isolated.py); no invoca el microservicio, Kafka, base de datos, cuotas ni Kubernetes. El coste máximo programado fue USD 0,20; el real fue **USD 0,06895840**.

| Variante | Qué decide el LLM | Qué ensambla el código de prueba |
| --- | --- | --- |
| `LEGACY` | Documento `AssertionBatch` completo, con el prompt y esquema actuales. | Usa los constructores V2 existentes. |
| `C1_semantic` | `text`, categoría, tema, evidencia, contexto completo, confianza y `search_hints`; no genera IDs ni versión. | Asigna ID, índice y versión fija; valida `Assertion`, `EnrichedAssertion` y `AssertionsDocumentV2`. |
| `C2_jurisdiction_key` | Lo mismo que C1, pero expresa jurisdicción mediante una clave de alcance y códigos, más `applicable_country_codes`. | Expande una gramática finita (`GLOBAL`, `UNKNOWN`, `COUNTRY:XX`, `SUPRANATIONAL:CODE`, `REGION:XX:XX-SUBCODE`, `LOCAL:XX:XX-SUBCODE:LOCALCODE`); valida con los modelos actuales. No consulta listas de países o entidades. |
| `C3_wire` | Los mismos campos semánticos en claves cortas, incluidos nombres libres de entidades, lugares, fechas y consultas. | Expande nombres de campos y la clave de jurisdicción; valida los modelos actuales. |

El código **no infiere entidades, países, fechas, temas, categorías, tipos de evidencia ni consultas** a partir de una configuración de nombres. Las únicas tablas son enums y catálogos finitos ya versionados. Los campos libres siguen siendo responsabilidad del LLM. Los esquemas enviados medían 6.574 caracteres en LEGACY, 6.072 en C1, 5.434 en C2 y 4.043 en C3. En el caso de 255 caracteres, los prompts medían respectivamente 8.773, 5.340, 4.751 y 5.120 caracteres. Reducir el tamaño de entrada **no** garantiza menos tokens de razonamiento o salida.

Se usaron tres recursos sintéticos versionados: [E, tres hechos estadísticos y 255 caracteres](../../tests/data/benchmark/resources/cases/historical/pre-gold-v0/eu-official-statistics-2025-v2.json); [N, cuatro hechos de distintos países y 449 caracteres](../../tests/data/benchmark/resources/cases/historical/pre-gold-v0/eu-news-2025-v2.json); y [L, seis hechos distribuidos en 2.321 caracteres](../../tests/data/benchmark/resources/cases/historical/pre-gold-v0/long-europe-2025-synthetic-v1.json), creado para esta prueba. E y N se repitieron dos veces por variante; L, una vez. Se alternó el orden de las variantes. Una llamada HTTP equivale a una prueba; **20 llamadas, 20 respuestas facturables, cero reparaciones**.

## Las 20 respuestas

`Entrada/salida` son tokens informados por OpenRouter; entre paréntesis se muestran tokens de razonamiento incluidos en la salida. `Queries` cuenta aserciones con al menos una `suggested_query` explícita. `Válido` significa que pasó los modelos de dominio y el documento V2, no que la clasificación sea correcta.

| Nº | Caso | Variante | Segundos | Entrada / salida (razonamiento) | USD | Hechos | Queries | Contrato |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | E | LEGACY | 40,463 | 3.701 / 5.913 (5.184) | 0,00255025 | 3 | 3/3 | Válido |
| 2 | E | C1 | 56,966 | 2.735 / 8.777 (8.000) | 0,00364755 | 3 | 3/3 | Válido |
| 3 | E | C2 | 58,774 | 2.491 / 8.839 (8.320) | 0,00366015 | 3 | 0/3 | Válido |
| 4 | E | C3 | 44,981 | 2.485 / 7.595 (7.040) | 0,00316225 | 3 | 3/3 | Válido |
| 5 | N | C3 | 69,554 | 2.508 / 10.569 (9.792) | 0,00435300 | 4 | 4/4 | Válido |
| 6 | N | C2 | 51,415 | 2.514 / 8.769 (7.872) | 0,00363330 | 4 | 0/4 | Inválido: `applicable_country_codes` en `COUNTRY` |
| 7 | N | C1 | 68,149 | 2.758 / 10.235 (8.640) | 0,00411670 | 4 | 4/4 | Válido |
| 8 | N | LEGACY | 51,969 | 3.724 / 7.113 (5.888) | 0,00303140 | 4 | 4/4 | Válido |
| 9 | E | C1 | 48,232 | 2.735 / 7.478 (6.656) | 0,00301275 | 3 | 3/3 | Inválido: `applicable_country_codes` en `COUNTRY` |
| 10 | E | C3 | 53,471 | 2.485 / 9.346 (8.832) | 0,00375897 | 3 | 3/3 | Válido, pero clasificación errónea |
| 11 | E | LEGACY | 29,790 | 3.701 / 5.310 (4.480) | 0,00214777 | 3 | 3/3 | Válido |
| 12 | E | C2 | 49,391 | 2.491 / 8.119 (7.296) | 0,00326847 | 3 | 0/3 | Válido |
| 13 | N | C2 | 35,490 | 2.514 / 5.240 (4.736) | 0,00211226 | 4 | 0/4 | Válido, sin hints explícitos |
| 14 | N | LEGACY | 55,691 | 3.724 / 9.999 (8.832) | 0,00402452 | 4 | 4/4 | Válido |
| 15 | N | C3 | 48,270 | 2.508 / 7.029 (6.272) | 0,00283332 | 4 | 4/4 | Válido |
| 16 | N | C1 | 54,023 | 2.758 / 9.177 (8.192) | 0,00369350 | 4 | 4/4 | Válido |
| 17 | L | C3 | 55,196 | 2.904 / 9.432 (8.256) | 0,00381432 | 6 | 6/6 | Inválido: tema y categoría incompatibles |
| 18 | L | LEGACY | 57,942 | 4.120 / 10.636 (9.152) | 0,00446040 | 6 | 6/6 | Válido |
| 19 | L | C1 | 86,071 | 3.154 / 11.416 (10.048) | 0,00460890 | 6 | 6/6 | Válido |
| 20 | L | C2 | 45,262 | 2.910 / 7.567 (6.528) | 0,00306862 | 6 | 0/6 | Válido, sin hints explícitos |

## Calidad y tiempo agregados

Las cuatro variantes seleccionaron los 3, 4 y 6 hechos esperados en cada respuesta, con sus negaciones y cifras principales. Esa cobertura no equivale a calidad de clasificación ni de búsqueda. En la tabla siguiente, las coincidencias con gold son diagnósticas: algunas etiquetas de evidencia del corpus sintético admiten interpretación y no se evaluó recuperación real de fuentes. La jurisdicción se compara por país esperado; `Queries` exige listas no vacías, sin certificar utilidad.

| Variante | Documento V2 válido | Mediana de 5 llamadas | Coste de 5 llamadas | Categoría gold | Tema gold | Evidencia gold | País | Año en `text` | Queries explícitas |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LEGACY | 5/5 | 51,969 s | USD 0,01621434 | 16/20 | 20/20 | 13/20 | 20/20 | 17/20 | 20/20 |
| C1 | 4/5 | 56,966 s | USD 0,01907940 | 17/20 | 19/20 | 13/20 | 19/20 | 17/20 | 20/20 |
| C2 | 4/5 | 49,391 s | USD 0,01574280 | 16/20 | 18/20 | 8/20 | 20/20 | 20/20 | **0/20** |
| C3 | 4/5 | 53,471 s | USD 0,01792186 | **10/20** | 16/20 | 11/20 | 17/20 | 20/20 | 20/20 |

En total, el proveedor informó 150.016 tokens de razonamiento entre 168.559 tokens de salida (**89,0 %**). C1/C2/C3 redujeron los tokens de entrada agregados frente a LEGACY, pero C1 y C3 **aumentaron** los tokens de salida. La mediana mezclada de cinco casos por variante no es un p50 de producción; L tiene una sola ejecución y no hay p95 fiable.

**Fallos que impiden adoptar una compacta:**

- C1 redujo entrada, pero fue más lenta y costosa en conjunto; su segunda E falló por lista de países incompatible con `COUNTRY`. En L fue 86,1 s frente a 57,9 s de LEGACY.
- C2 fue rápida en L (45,3 s), pero devolvió **cero `search_keywords` y cero `suggested_queries` en sus 20 aserciones**. En L también usó `evidence_kind=GENERAL` para las seis, incluidas cifras y decisiones normativas. El modelo V2 permite listas vacías y `GENERAL`; Evidence Search tiene una consulta de respaldo basada en texto/contexto, pero no se midió que recupere igual de bien. La velocidad coincide con trabajo semántico omitido, por lo que **no es una mejora de calidad equivalente**. Una N falló además por `applicable_country_codes` en `COUNTRY`.
- C3 mantuvo queries explícitas, pero en la segunda E asignó `DEMOGRAPHY` y categoría 10 a los tres hechos, aunque dos trataban inflación y energía; Pydantic lo aceptó. En L asignó categoría 1 a **los seis hechos**, provocando incompatibilidades de taxonomía. La compresión de nombres de campos no garantizó clasificación estable.
- LEGACY pasó el contrato en las cinco llamadas, aunque también omitió `2025` en tres textos de la segunda N. La mejora de autonomía temporal de C2/C3 es real en estos ejemplos, pero no compensa sus fallos de evidencia, consultas o categoría.

## Enriquecimiento por código: límite universal

**Seguro para evaluar o reutilizar:** asignar ID, índice y `taxonomy_version` mediante el constructor existente; expandir una representación finita de jurisdicción **solo** cuando el LLM haya decidido explícitamente alcance y códigos, seguida de `JurisdictionContext`; validar compatibilidad con `TOPIC_CATEGORY_IDS`. De ese catálogo finito, siete temas tienen una sola categoría permitida y podrían recibirla por una regla general; los demás necesitan decisión semántica. Esta posible simplificación no se probó aquí. También existe una consulta de respaldo en [Evidence Search](../../api/evidence-search/main.py) formada a partir de `text` y contexto; usarla como sustituto de hints del generador requiere comparar recuperación real y evitar duplicar el motor de consultas.

**Debe seguir siendo semántico:** nombres de entidades y lugares, referencia temporal inferida, ámbito territorial no explícito, afirmación factual, categoría cuando hay varias válidas, `evidence_kind`, consultas útiles y grados de confianza. Ninguno puede resolverse con una lista cerrada de entidades. El código puede verificar forma, procedencia y compatibilidad, pero no convertir un dato ambiguo en certeza.

## Decisión

**No adoptar C1, C2 ni C3.** La estrategia de una sola llamada compacta sigue siendo una hipótesis, pero esta formulación no alcanzó calidad y velocidad a la vez. Una siguiente variante tendría que exigir hints no vacíos, conservar la clasificación de evidencia y pasar evaluación semántica, no solo Pydantic. Debe medirse con más noticias largas, repeticiones alternadas y búsqueda posterior. Hasta entonces, `LEGACY` permanece como ruta inicial y se conservan los modelos e ICs actuales.

Los resultados detallados, prompts, respuestas y `usage` están en `/tmp/generate-assertions-compact-20261117/`, fuera del repositorio y sin credenciales. El [caso L sintético](../../tests/data/benchmark/resources/cases/historical/pre-gold-v0/long-europe-2025-synthetic-v1.json) y el ejecutor de pruebas quedan versionables; no se hizo commit ni push.
