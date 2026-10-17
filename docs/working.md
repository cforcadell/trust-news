# Plan de pruebas factual — Official Gold v0

**Plan operativo — 15 de octubre de 2026.** Este documento sustituye el plan anterior de `working.md`. Su objetivo inmediato no es certificar comercialmente la precisión de Assermetry, sino obtener una primera señal factual pequeña, equilibrada, reproducible y trazable para localizar fallos de extracción, routing, recuperación, validación y consenso.

La guía contractual del runner continúa en [evaluation.md](tests/evaluation.md). Los resultados de cada ejecución son artefactos fechados; no deben editarse ni sobrescribirse.

## 1. Decisión y alcance

No se construirá todavía un generador de datasets ni se intentarán producir 60–500 afirmaciones. Primero se ejecutará un lote manual de doce afirmaciones reales y revisables:

- 6 `TRUE` y 6 `FALSE`.
- 6 fuentes institucionales primarias.
- Una noticia atómica por afirmación.
- Una pareja verdadera/falsa por fuente.
- Una contradicción directa para cada `FALSE`.
- Sin `UNKNOWN` en la métrica factual principal.

Los `UNKNOWN` se tratarán posteriormente en un lote separado de abstención. En un ensayo `FULL`, no encontrar evidencia no demuestra que la afirmación sea incognoscible: puede ser un fallo de Router o Evidence Search. Por ello no se mezclarán inicialmente con la precisión factual.

### Recursos activos

```text
tests/data/benchmark/resources/
├── cases/
│   ├── official-gold-v0/                # 12 casos activos
│   └── historical/pre-gold-v0/          # 6 recursos anteriores, solo regresión
└── provenance/
    └── official-gold-v0.json            # expediente de fuentes y revisión
```

`official-gold-v0` permanece marcado como `status:candidate` hasta completar una revisión humana independiente. Ser estructuralmente válido o haber sido revisado por una IA no equivale a estar homologado.

## 2. Matriz de Official Gold v0

| Pareja | TRUE | FALSE | Dominio gold | Evidencia |
| --- | --- | --- | --- | --- |
| Población de España, 1/1/2025 | Cifra definitiva: 49.128.297 | Cifra definitiva: 49.077.984 | `ine.es` | Estadística oficial definitiva |
| Generación eléctrica española, 2024 | Renovables: 56,8 % | Renovables: 100 % | `ree.es` | Cierre anual del sistema eléctrico |
| Consumo renovable de la UE, 2023 | Cuota: 24,5 % | Cuota: 34,5 % | `ec.europa.eu` | Eurostat, `nrg_ind_ren` |
| Objetivo renovable de la UE, 2030 | Obligación mínima: 42,5 % | Obligación: 45 % | `eur-lex.europa.eu` | Directiva (UE) 2023/2413 |
| Aplicación del RGPD | 25/5/2018 | 25/5/2020 | `commission.europa.eu` / `eur-lex.europa.eu` | Resumen legal oficial |
| Parlamento Europeo 2024–2029 | 720 miembros | 705 miembros | `europarl.europa.eu` | Página institucional |

La primera pareja distingue expresamente estimación y dato definitivo. Los 49.077.984 habitantes procedían de una estimación provisional; el Censo Anual publicó después 49.128.297 como cifra definitiva. La pareja sobre renovables distingue también obligación jurídica del 42,5 % y aspiración de llegar al 45 %.

## 3. Reglas de interpretación

Las campañas responden preguntas diferentes y sus puntuaciones no se deben fusionar:

| Modo | Router | Recuperación | Validador | Pregunta |
| --- | --- | --- | --- | --- |
| `gold-evidence` | Omitido | Evidencia congelada | Directo | ¿Interpreta el modelo la evidencia correcta? |
| `gold-domains` | Dominio inyectado | Real | Directo | ¿Recupera evidencia útil partiendo de una fuente correcta? |
| `full` directo | Real | Real | Directo | ¿Dónde falla el pipeline técnico con una configuración conocida? |
| `full --publish` | Despliegue real | Despliegue real | Validadores desplegados y consenso | ¿Qué hace el producto completo, incluida extracción? |

Un `GROUNDING_PASS` solo acredita que la cita existe y es elegible. No demuestra por sí solo que implique semánticamente el veredicto. Del mismo modo, encontrar `ine.es` no basta si el fragmento recuperado pertenece a otra fecha o a una versión provisional incompatible.

## 4. Convenciones de ejecución

Todos los comandos parten de la raíz del repositorio:

```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=tests:api
export GOLD_V0=tests/data/benchmark/resources/cases/official-gold-v0
```

Los nombres `REEMPLAZAR_MODELO_A/B` son marcadores obligatorios. No se deben guardar tokens, contraseñas ni secretos de Keycloak en este documento o en scripts versionados. Cada `--output` debe apuntar a un directorio inexistente.

## 5. Fase 0 — Homologación humana de fuentes

### Objetivo

Comprobar antes de medir Assermetry que cada etiqueta es más fiable que el sistema evaluado. Una persona distinta de quien redactó el caso verificará autoridad, URL, fechas, estado provisional/definitivo, fragmento, implicación del veredicto y alineación entre `news` y la afirmación gold.

### Comandos

Listar casos y expediente:

```bash
find "$GOLD_V0" -maxdepth 1 -type f -name '*.json' -print | sort
sed -n '1,260p' tests/data/benchmark/resources/provenance/official-gold-v0.json
```

Calcular huellas:

```bash
find "$GOLD_V0" -maxdepth 1 -type f -name '*.json' -print0 \
  | sort -z \
  | xargs -0 sha256sum
sha256sum tests/data/benchmark/resources/provenance/official-gold-v0.json
```

Comprobar que las URLs responden; esto no sustituye la revisión semántica:

```bash
curl -L --fail --silent --show-error --output /dev/null --write-out '%{http_code} %{url_effective}\n' \
  'https://www.ine.es/dyngs/Prensa/es/CensoVariables2025.html'
curl -L --fail --silent --show-error --output /dev/null --write-out '%{http_code} %{url_effective}\n' \
  'https://www.ree.es/es/sala-de-prensa/actualidad/nota-de-prensa/2025/03/la-produccion-renovable-crece-en-Espana-un-10-3-por-ciento-2024-alcanza-mayores-registros'
curl -L --fail --silent --show-error --output /dev/null --write-out '%{http_code} %{url_effective}\n' \
  'https://ec.europa.eu/eurostat/en/web/products-eurostat-news/w/ddn-20241219-3'
curl -L --fail --silent --show-error --output /dev/null --write-out '%{http_code} %{url_effective}\n' \
  'https://eur-lex.europa.eu/legal-content/ES/ALL/?uri=CELEX:32023L2413'
curl -L --fail --silent --show-error --output /dev/null --write-out '%{http_code} %{url_effective}\n' \
  'https://commission.europa.eu/law/law-topic/data-protection/legal-framework-eu-data-protection_en'
curl -L --fail --silent --show-error --output /dev/null --write-out '%{http_code} %{url_effective}\n' \
  'https://www.europarl.europa.eu/about-parliament/en/organisation-and-rules/organisation/members'
```

### Puerta de salida

- Las doce implicaciones están identificadas por revisor.
- Las seis entradas del manifiesto pasan de `CANDIDATE` a `APPROVED`.
- Se registra la huella del documento o de una copia privada fechada cuando la fuente sea mutable.
- Una fuente dudosa bloquea su pareja; no se corrige el gold mirando la respuesta de Assermetry.

## 6. Fase 1 — Validación estructural y balance

### Objetivo

Comprobar el contrato v2 sin llamar a servicios ni proveedores.

### Comandos

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline --dataset "$GOLD_V0" --validate-only
```

Comprobar identificadores, balance y anotaciones imprescindibles:

```bash
python3 - <<'PY'
import collections
import json
from pathlib import Path

root = Path("tests/data/benchmark/resources/cases/official-gold-v0")
rows = []
for path in sorted(root.glob("*.json")):
    case = json.loads(path.read_text(encoding="utf-8"))
    assert len(case["assertions"]) == 1, path
    assertion = case["assertions"][0]
    assert assertion["source_excerpt"] in case["news"], path
    assert assertion.get("acceptable_domains"), path
    assert assertion.get("reference_sources"), path
    assert "reference_evidence" in assertion, path
    rows.append((case["id"], assertion["id"], assertion["expected_verdict"]))
assert len(rows) == 12, len(rows)
assert len({case_id for case_id, _, _ in rows}) == 12
assert len({assertion_id for _, assertion_id, _ in rows}) == 12
assert collections.Counter(v for _, _, v in rows) == {"TRUE": 6, "FALSE": 6}
print("OK", collections.Counter(v for _, _, v in rows))
PY
```

### Puerta de salida

El runner informa `datasets=12 assertions=12` y el script informa `TRUE: 6, FALSE: 6`.

## 7. Fase 2 — GOLD_EVIDENCE: decisión del validador

### Objetivo

Comparar modelos con la misma evidencia, sin ruido de Router ni Evidence Search. Esta es la primera campaña con proveedores porque ofrece el diagnóstico más limpio.

### Comando

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.llm_benchmark \
  --dataset "$GOLD_V0" \
  --mode gold-evidence \
  --model openrouter:REEMPLAZAR_MODELO_A \
  --model openrouter:REEMPLAZAR_MODELO_B \
  --temperature 0 \
  --cache FROZEN \
  --repetitions 3 \
  --output "tests/data/evaluation/artifacts/gold-v0-evidence-$(date -u +%Y%m%dT%H%M%SZ)"
```

### Puerta de salida

Registrar accuracy, distribución de veredictos, resultados `TRUE`/`FALSE` separados, respuestas inválidas, errores, citas, grounding y variabilidad. El runner actual no calcula macro-F1; no se presentará esa métrica salvo que se añada un cálculo determinista y probado. Un error con evidencia gold suficiente es candidato a `LLM_WRONG_VERDICT`; no se atribuye al Router.

## 8. Fase 3 — GOLD_DOMAINS: recuperación controlada

### Objetivo

Comprobar Evidence Search partiendo del dominio primario anotado.

### WARM

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --dataset "$GOLD_V0" \
  --mode gold-domains \
  --model openrouter:REEMPLAZAR_MODELO_A \
  --temperature 0 --cache WARM --repetitions 3 \
  --output "tests/data/evaluation/artifacts/gold-v0-domains-warm-$(date -u +%Y%m%dT%H%M%SZ)"
```

### COLD

`EVALUATION_ALLOW_COLD=true` debe estar configurado tanto en Source Router como en Evidence Search; definirlo solo en la shell del runner no modifica los servicios.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --dataset "$GOLD_V0" \
  --mode gold-domains \
  --model openrouter:REEMPLAZAR_MODELO_A \
  --temperature 0 --cache COLD --repetitions 1 \
  --output "tests/data/evaluation/artifacts/gold-v0-domains-cold-$(date -u +%Y%m%dT%H%M%SZ)"
```

### Puerta de salida

Por afirmación quedan registrados URLs, descargas, contextos citables, dominio de referencia y cobertura del hecho. La ausencia de un fragmento útil se clasifica como recuperación aunque el dominio sea correcto.

## 9. Fase 4 — FULL directo y contrafactuales

### Objetivo

Ejecutar Router, Evidence Search y un modelo conocido, añadiendo automáticamente `gold-domains` y `gold-evidence` para localizar la etapa responsable.

### Comando

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --dataset "$GOLD_V0" \
  --mode full \
  --model openrouter:REEMPLAZAR_MODELO_A \
  --temperature 0 --cache WARM --counterfactuals --repetitions 3 \
  --router-url http://localhost:8075 \
  --evidence-search-url http://localhost:8074 \
  --output "tests/data/evaluation/artifacts/gold-v0-full-direct-$(date -u +%Y%m%dT%H%M%SZ)"
```

### Lectura causal

- `FULL` falla y `GOLD_DOMAINS` pasa: candidato a error del Router.
- `FULL` y `GOLD_DOMAINS` fallan, pero `GOLD_EVIDENCE` pasa: candidato a recuperación.
- `GOLD_EVIDENCE` falla con evidencia suficiente: candidato a validador.
- Validadores correctos y consenso incorrecto: candidato a `CONSENSUS_ERROR`.
- Sin hashes o anotación: `NOT_EVALUATED`, no una inferencia optimista.

### Puerta de salida

Cada fallo tiene una etapa candidata respaldada por contrafactuales de la misma afirmación, configuración, plantilla y repetición, o queda como `UNDETERMINED`.

## 10. Fase 5 — FULL publicado: producto completo y extracción

### Objetivo

Publicar las doce noticias por el flujo LIGHT real. Es la fase que incluye Generate Assertions y el consenso/reputación del despliegue.

### Preparación segura

Proporcionar credenciales solo en el entorno:

```bash
export ASSERMETRY_API_URL=https://localhost:7443/backend
export ASSERMETRY_ACCESS_TOKEN='REEMPLAZAR_SIN_GUARDAR_EN_GIT'
```

Alternativamente, configurar `ASSERMETRY_USERNAME`/`ASSERMETRY_PASSWORD` o `ASSERMETRY_KEYCLOAK_CLIENT_ID`/`ASSERMETRY_KEYCLOAK_CLIENT_SECRET` fuera del repositorio.

### Comando

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --dataset "$GOLD_V0" \
  --mode full --publish \
  --base-url "$ASSERMETRY_API_URL" \
  --no-verify-tls \
  --result-timeout 600 --repetitions 3 \
  --output "tests/data/evaluation/artifacts/gold-v0-published-$(date -u +%Y%m%dT%H%M%SZ)"
```

Con certificado válido se sustituirá `--no-verify-tls` por `--verify-tls`.

### Puerta de salida

Separar recall de las doce afirmaciones, generadas `OBSERVATION_ONLY`, incompatibilidades de cifra/fecha/negación, routing, recuperación, veredictos, errores, consenso y E2E. Doce noticias por tres repeticiones producen 36 unidades afirmación × repetición; los registros de validadores son otro denominador.

## 11. Fase 6 — Análisis offline y revisión manual

### Comandos

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --analyze tests/data/evaluation/artifacts/REEMPLAZAR_CAMPAIGN_ID
```

Visor local:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.viewer.server \
  --artifacts-root tests/data/evaluation/artifacts \
  --host 127.0.0.1 --port 8765
```

### Revisión y puerta de salida

Revisar, por orden: match de extracción; taxonomía; dominios; URL/descarga/versión temporal; evidencia y hashes; citas; implicación semántica; votos y consenso. Cada desviación termina clasificada como dataset, extracción, routing, recuperación, handoff, validador, grounding, consenso, técnica o indeterminada.

## 12. Fase 7 — Regresión histórica

Los seis recursos encontrados en `postTFM`/`b9003cf` se conservan en `historical/pre-gold-v0`. Incluyen casos sintéticos, versiones solapadas y anotaciones pendientes; no participan en métricas nuevas por defecto.

### Validación histórica

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --dataset tests/data/benchmark/resources/cases/historical/pre-gold-v0 \
  --validate-only
```

### Reproducción deliberada

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --dataset tests/data/benchmark/resources/cases/historical/pre-gold-v0/spain-official-statistics-2025-v2.json \
  --mode full --publish --repetitions 3 \
  --output "tests/data/evaluation/artifacts/historical-spain-v2-$(date -u +%Y%m%dT%H%M%SZ)"
```

Los resultados históricos deben llevar `historical` en el identificador y no se compararán como si tuvieran el mismo gold.

## 13. Fase 8 — Promoción y ampliación

Official Gold v0 solo se promueve cuando las fuentes e implicaciones tienen revisión humana independiente; no quedan ambigüedades provisional/definitiva; los `FALSE` están contradichos directamente; se conservan hashes; y los casos no se han corregido para coincidir con el modelo favorito.

### Revalidación de promoción

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline --dataset "$GOLD_V0" --validate-only
find "$GOLD_V0" -maxdepth 1 -type f -name '*.json' -print0 \
  | sort -z \
  | xargs -0 sha256sum
```

### Ampliación posterior

1. Llegar a 24–30 afirmaciones cubriendo fallos observados.
2. Crear `official-abstention-v0` para `UNKNOWN`, primero en `gold-evidence`.
3. Añadir cuatro noticias compuestas reutilizando hechos homologados; no contarlas como hechos independientes.
4. Reservar un holdout no utilizado para ajustar prompts.
5. Automatizar descarga/hash solo si la curación manual revela trabajo repetitivo estable.

No se construirá un generador completo antes de que v0 muestre qué automatización aporta valor.

## 14. Informe mínimo de campaña

| Dimensión | Métrica o evidencia |
| --- | --- |
| Dataset | IDs, SHA-256, revisión y commit |
| Extracción | Recall gold, incompatibles y observaciones no emparejadas |
| Taxonomía | Accuracy de TopicCode, EvidenceKind y jurisdicción |
| Router | Recall de dominio, rango y caché |
| Recuperación | Descargas, contextos citables y fuente gold |
| Handoff | Hashes de evidencia en ambos límites |
| Validador | Accuracy, distribución, TRUE/FALSE, abstención e inválidas |
| Grounding | Identidad/elegibilidad, separada de implicación humana |
| Consenso | Resultado, votos, errores y pesos |
| Operación | HTTP 429, timeout, latencia y fallos técnicos |

No se publicará una única cifra como “precisión de Assermetry”. Doce casos son diagnóstico y regresión, no una estimación estadísticamente robusta de calidad comercial.

## 15. Orden recomendado

1. Homologar fuentes y congelar hashes.
2. Validar los doce JSON.
3. Ejecutar `gold-evidence`.
4. Ejecutar `gold-domains` WARM y una pasada COLD.
5. Ejecutar `full` directo con contrafactuales.
6. Publicar el flujo completo.
7. Analizar offline y clasificar cada fallo.
8. Corregir primero defectos del gold; después abrir regresiones del producto.
9. Repetir la matriz sobre el mismo hash antes de ampliar el corpus.

Esta secuencia evita atribuir a un LLM un fallo de extracción o búsqueda y evita optimizar el dataset para los resultados observados.
