# Official Gold v0

Este directorio contiene once casos atómicos: seis `TRUE` y cinco `FALSE`. Cada noticia contiene exactamente la afirmación que Generate Assertions debe extraer. Las falsedades están contradichas directamente por una fuente primaria documentada en el expediente de procedencia.

Los casos tienen estado `status:candidate` hasta que una persona complete y firme la revisión indicada en `tests/data/benchmark/resources/provenance/official-gold-v0.json`. Son utilizables para depuración, pero no deben presentarse como evidencia de aceptación independiente mientras quede una fuente sin aprobar.

Los antiguos recursos se conservan en `../historical/pre-gold-v0/` y no se cargan al pasar este directorio al runner.
