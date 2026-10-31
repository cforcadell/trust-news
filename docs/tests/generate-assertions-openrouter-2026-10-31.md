# Benchmark aislado de GenerateAssertions — 2026-10-31

## Alcance y controles

Este benchmark invocó OpenRouter directamente desde el ejecutor de pruebas.
Reutiliza de forma de solo lectura el prompt y el esquema de
`api/generate-asertions/main.py`; no llama a servicios de Assermetry, Kafka,
base de datos ni Kubernetes. No se modificó configuración de producción.

Antes de la ejecución se verificó que `EVIDENCE_EXTRACTION_MODE` estaba en
`DIRECT`. Gemini (B4) se excluyó de esta ejecución.

La campaña principal usó cinco casos *gold*, dos repeticiones y tres
configuraciones: B0, B1 y B2. El plan publicado antes de las llamadas preveía
30 ejecuciones principales, 3 *preflights*, 33 llamadas mínimas y un coste de
USD 0,0191014. Cada intento HTTP, incluido un reintento de transporte o una
reparación de esquema, queda registrado y consume el límite.

## Resultado de la campaña completa

Artefactos: [manifest](../../tests/data/evaluation/artifacts/generate-assertions-openrouter-two-more-b0-b2-20261031/manifest.json), [métricas](../../tests/data/evaluation/artifacts/generate-assertions-openrouter-two-more-b0-b2-20261031/metrics.json) y [detalle tabular](../../tests/data/evaluation/artifacts/generate-assertions-openrouter-two-more-b0-b2-20261031/comparison.csv).

| Configuración | Ejecuciones | Éxito | p50 | p95 | F1 de extracción | Reparaciones | Coste de ejecuciones (USD) | Coste incluido *preflight* (USD) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 · `openai/gpt-5-nano` | 10 | 100% | 12,019 s | 17,565 s | 1,000 | 0% | 0,01131150 | 0,01214800 |
| B1 · `openai/gpt-5-nano` con `reasoning=minimal` | 10 | 90% | 2,181 s | 6,609 s | 0,667 | 20% | 0,00152409 | 0,00186946 |
| B2 · `openai/gpt-4.1-nano` | 10 | 70% | 4,478 s | 5,183 s | 0,286 | 80% | 0,00285152 | 0,00319264 |

La campaña completó las 30 ejecuciones y registró 45 llamadas al proveedor:
30 intentos principales, 10 reparaciones de esquema y 5 *preflights*. El coste
real conocido es USD 0,01721010, un 9,9% por debajo de la estimación previa.
Los costes se calculan desde la bitácora de cada llamada del proveedor, también
cuando una fila de ejecución acaba fallando después de una respuesta facturable.

## Lectura de los resultados

- B0 fue la única configuración con éxito y F1 perfectos en los diez casos.
  Es la opción de referencia de calidad, con mayor latencia y coste.
- B1 reduce mucho la latencia y el coste, pero pierde calidad y presenta un
  fallo. El modo `minimal` no reportó tokens de razonamiento en esta muestra.
- B2 tuvo la mayor tasa de reparación y tres fallos; no es una alternativa
  fiable para este flujo pese a su coste bajo.

El percentil p95 es descriptivo: cada configuración dispone únicamente de diez
ejecuciones, por lo que no debe interpretarse como una estimación robusta de
producción.

## Muestra parcial B3

La sesión inicial sin Gemini dejó una campaña interrumpida antes de completar
la matriz. Sus artefactos permanecen conservados en
[el manifiesto parcial](../../tests/data/evaluation/artifacts/generate-assertions-openrouter-two-more-no-gemini-20261031/manifest.json).

Solo B3 tiene dos ejecuciones principales completas en esa campaña: latencia
media de 265,315 s, F1 0,000 y coste de USD 0,00889644. No se mezcla con la
comparativa de arriba porque no alcanza las dos repeticiones de los cinco
casos. No se enviaron más llamadas B3 para respetar el límite total acordado.

## Límites y contabilidad global

Las dos campañas de esta tanda registraron 65 llamadas y USD 0,03770656. Al
incluir los artefactos persistidos de las tandas previas, el total es de 84
llamadas y USD 0,06124167 conocidos. Ambos valores permanecen por debajo de
los límites autorizados de 100 llamadas y EUR 0,50.

## Reproducibilidad

El ejecutor y sus pruebas están en:

- `tests/llm-benchmark/generate_assertions_isolated.py`
- `tests/llm-benchmark/test_generate_assertions_isolated.py`

La suite unitaria terminó con 12 pruebas correctas. El ejecutor admite un
límite de llamadas, presupuesto explícito, exclusión genérica de
configuraciones, reanudación por segmentos y acumulación correcta de los
costes de llamadas facturables fallidas.
