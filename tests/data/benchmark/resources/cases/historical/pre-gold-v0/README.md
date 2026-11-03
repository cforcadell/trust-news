# Casos históricos anteriores a Official Gold v0

Estos seis recursos son la línea base encontrada en `postTFM`/`b9003cf`. Se conservaron sin alterar al introducir `official-gold-v0` el 15 de octubre de 2026.

No deben incluirse en métricas de aceptación factual: contienen casos sintéticos, versiones solapadas, afirmaciones sin fuentes y anotaciones cuyo alcance temporal o implicación semántica necesita revisión. Siguen siendo útiles para reproducir campañas antiguas y pruebas de compatibilidad.

Para validarlos expresamente:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:api .venv/bin/python \
  -m evaluation.pipeline \
  --dataset tests/data/benchmark/resources/cases/historical/pre-gold-v0 \
  --validate-only
```
