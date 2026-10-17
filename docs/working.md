# Ciclo de estabilización por campañas e2e publicadas

**Estado: 17 de octubre de 2026.** Este es el procedimiento de trabajo de [v0.0.13](version.md). La unidad principal de aprendizaje es una orden real creada con `full --publish`, desde `publishNew` hasta extracción, routing, Evidence Search, validadores, consenso y estado terminal. El inventario de causas y criterios de cierre está en [issues.md](issues.md); el contrato del runner está en [evaluation.md](tests/evaluation.md).

## Línea base y límites de la comparación

La campaña [`gold-v0-published-20261017T083319Z`](../tests/data/evaluation/artifacts/gold-v0-published-20261017T083319Z/report.md) publicó **11 casos, una repetición cada uno**, y guardó **33 registros de validador**. El informe cuenta **9/11 unidades e2e correctas**, dos incorrectas; diez órdenes terminaron `VALIDATED` y una `VALIDATED_WITH_ERRORS`. La unidad e2e es caso × repetición, no validador. Hubo dos veredictos individuales contrarios al gold, un desajuste de extracción y un timeout de Evidence Search que dejó dos validadores sin decisión. Veintisiete de 33 validaciones advierten de alguna fuente inutilizable. Las citas y el handoff pasaron en las 31 validaciones completadas, sin acreditar apoyo semántico ni independencia.

La campaña se ejecutó con `c84bb6e` y árbol Git sucio. La anterior del 16 de octubre, con `b9003cf`, tenía doce casos y 39 registros: mostraba `ROUTER_NO_SOURCE`, `CONSENSUS_ERROR` y ausencia total de contexto citable en algunas validaciones terminadas, que no aparecen en la campaña del 17. Cambiaron revisión, corpus y configuración efectiva; esta diferencia es señal de avance, **no una estimación causal de las mejoras recientes ni una tasa de aceptación**. Los cambios locales posteriores de descarga de Evidence Search no están probados por esta campaña. Los once casos actuales conservan exactamente los hashes canónicos registrados en el manifiesto del 17; los SHA-256 de ficheros de abajo son adicionales y difieren de esos hashes porque incluyen el formato del JSON.

`Official Gold v0` activo contiene once casos: seis `TRUE` y cinco `FALSE`. Se retiró el falso de población por ambigüedad provisional/definitiva. Las seis fuentes del expediente siguen `CANDIDATE`; los resultados sirven para depurar, no para certificar precisión factual. No mezclar casos históricos ni usar el número de validadores como denominador de calidad e2e.

## Bucle de cada iteración

1. **Congelar la entrada.** Registrar revisión del repositorio y del despliegue, `git status`, hashes de los once JSON y expediente de procedencia, configuración de validadores sin secretos, entorno, hora UTC y estado de caché. Si hay cambios locales o en los casos, declararlos expresamente; una comparación exacta exige mismos hashes y configuración.
2. **Publicar la campaña.** Ejecutar `full --publish` LIGHT con una repetición de los once casos y un directorio nuevo. La ruta publicada es la puerta principal; una prueba local o `gold-evidence` no la reemplaza.
3. **Leer órdenes y avisos.** Para cada caso distinguir: publicación y estado terminal; extracción y taxonomía; dominios; búsquedas y descargas; fragmentos citables; handoff/citas; veredicto de cada validador; error/timeout; consenso y presentación. Contar por orden, caso y validador con denominadores explícitos.
4. **Priorizar plataforma.** Atender primero órdenes sin respuesta o con error técnico, después veredictos decisivos equivocados o evidencia primaria inutilizable, luego warnings persistentes sin impacto de veredicto. Los desajustes del gold o de perfiles de recurso van en una pista separada y no se usan para ocultar fallos de plataforma.
5. **Corregir como máximo dos causas.** Reproducir el caso original, identificar etapa y causa, aplicar corrección con prueba enfocada; publicar de nuevo ese caso. Tras ello publicar los once casos con los mismos hashes. Registrar qué incidencia se cerró, siguió abierta o se reabrió.
6. **Extender la comprobación.** Repetir el flujo en BLOCKCHAIN cuando afecte a contratos, Kafka/IPFS, consenso, estado o GUI; ejecutar las puertas de identidad, seguridad y móvil de `issues.md` en la misma revisión desplegada. No declarar estable la versión por un único lote LIGHT.

No se sobrescriben campañas. Guardar manifiesto, `report.json`, `report.md`, órdenes y diagnósticos del viewer; conservarlos fuera del directorio ignorado antes de usar el resultado como evidencia de cierre. Evitar secretos y datos personales en artefactos.

## Ejecución mínima desde la raíz del repositorio

Preparar autenticación `ASSERMETRY_*` desde el entorno o un gestor seguro. La URL y la confianza TLS deben corresponder al despliegue probado. El lanzador local de ISSUE-024 contiene aún una credencial literal: retirarla y comprobar su invalidez o rotación antes de otra ejecución compartida o de destino. No poner valores reales en este documento, scripts versionados ni línea de comandos guardada.

```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=tests:api
export GOLD_V0=tests/data/benchmark/resources/cases/official-gold-v0

.venv/bin/python -m evaluation.pipeline \
  --dataset "$GOLD_V0" --validate-only

find "$GOLD_V0" -maxdepth 1 -type f -name '*.json' -print0 \
  | sort -z | xargs -0 sha256sum
sha256sum tests/data/benchmark/resources/provenance/official-gold-v0.json

tag="gold-v0-published-$(date -u +%Y%m%dT%H%M%SZ)"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --dataset "$GOLD_V0" --mode full --publish \
  --base-url "$ASSERMETRY_API_URL" \
  --result-timeout 600 --repetitions 1 \
  --output "tests/data/evaluation/artifacts/$tag"
```

El runner utiliza la configuración real del despliegue. Con certificado local autofirmado puede requerirse `--no-verify-tls`; en destino, usar `--verify-tls`. Registrar cuál se empleó. `--publish` no admite `--model`, `--cache` ni `--counterfactuals`; esos modos se ejecutan aparte para aislar causas. Si la publicación falla, preservar el directorio y clasificar la etapa de autenticación/publicación/polling antes de reintentar. `COMPLETED_WITH_ERRORS` es fallo de la puerta operativa aunque existan veredictos.

Analizar offline sin volver a llamar servicios:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline --analyze \
  tests/data/evaluation/artifacts/REEMPLAZAR_CAMPAIGN_ID
```

`--analyze` crea `analysis/` y exige que no exista ya; usar una copia de la campaña para repetirlo. El viewer puede abrirse con `python -m evaluation.viewer.server --artifacts-root tests/data/evaluation/artifacts --host 127.0.0.1 --port 8765`.

## Triage de la campaña del 17 de octubre

| Prioridad | Observación | Causa/acción siguiente | Incidencia |
| --- | --- | --- | --- |
| 1 | Una orden `VALIDATED_WITH_ERRORS`; dos validadores sin decisión por `EVIDENCE_SEARCH timed out` | Medir y corregir límite, concurrencia o dependencia; republicar `EU_RENEWABLE_SHARE_2023_FALSE` y el lote | 025; verificar 008/019 |
| 2 | 27/33 validaciones con `SOME_SOURCES_UNUSABLE`; 21 `empty_text` de `eur-lex.europa.eu`, 12 de `europarl.europa.eu` | Probar recuperación de HTML/PDF, redirecciones y URL final; exigir fuente primaria auditable o abstención | 021 |
| 3 | `EU_RENEWABLE_SHARE_2023_TRUE`: categoría generada `1`, gold `9` | Revisar extractor y contrato de categoría con el caso publicado; confirmar gold antes de cambiarlo | 017 |
| 4 | `ES_RENEWABLE_GENERATION_2024_TRUE`: un validador `FALSE`; `EU_PARLIAMENT_MEMBERS_FALSE`: un validador `TRUE` | Revisar los contextos exactos, fragmentos y soporte semántico; usar contrafactual con evidencia congelada si la fuente es insuficiente | 017/021 |
| 5 | Un router LOCAL no seleccionó `ree.es`; warnings menores de entidades/periodo esperado | Comprobar relevancia de dominios, taxonomía y anotaciones del gold por separado; no bloquear la corrección técnica anterior | 015/022/017 |

`SOME_SOURCES_UNUSABLE` indica degradación aunque haya contextos alternativos y consenso correcto. Un `GROUNDING_PASS` solo confirma identidad y elegibilidad de la cita. Los dos veredictos individuales equivocados tienen causa `UNDETERMINED` en el informe: sin contrafactual comparable y revisión del fragmento no se atribuyen automáticamente al LLM. El warning por omitir `100` en “toda la generación” puede ser equivalencia lingüística; revisarlo antes de considerarlo fallo de extracción.

## Contrafactuales puntuales

Después de publicar, usar el **mismo JSON, revisión, modelo, temperatura y plantilla** para aislar una etapa; guardar cada salida nueva. `gold-domains` pregunta si Evidence Search funciona al partir del dominio primario; `gold-evidence` pregunta si el validador interpreta evidencia congelada. Un fallo en publish con éxito en `gold-domains` apunta al router; un fallo en ambos con éxito en `gold-evidence` apunta a recuperación. Si ambos fallan, examinar cita, soporte y contrato antes de culpar al modelo. Los contrafactuales no pasan por Generate Assertions ni por el consenso del despliegue, por lo que no cierran por sí solos una incidencia e2e.

## Puertas de cierre de v0.0.13

Para cada incidencia: reproducir el fallo original, aportar corrección y prueba enfocada, publicar el caso afectado sin el síntoma, y publicar el lote completo sobre la misma revisión desplegada. La campaña debe terminar sin errores técnicos ni nuevos P1; las fuentes primarias decisivas deben tener fragmentos citables y soporte revisado; los warnings residuales deben tener causa y mitigación explícitas. Repetir campañas completas consecutivas según el criterio de [version.md](version.md), con hashes estables y sin reabrir el mismo fallo. Acreditar además BLOCKCHAIN, GUI, identidad, seguridad y móvil mediante las puertas específicas de [issues.md](issues.md).

La homologación humana del gold y los umbrales de aceptación se fijan antes de llamar “calidad factual” a cualquier porcentaje. Hasta entonces cada campaña es una herramienta para estabilizar la plataforma y cerrar incidencias con evidencia reproducible.
