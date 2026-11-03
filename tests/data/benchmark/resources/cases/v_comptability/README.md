# Casos de compatibilidad

Estos recursos se conservan para repetir benchmarks históricos, pero no son
casos activos: usan el contrato `schema_version: 1`, que no expresa la
taxonomía, el contexto ni las referencias que el pipeline de evaluación y el
visor actuales pueden mostrar. `load_datasets()` no desciende a este directorio
cuando recibe `resources/cases`, por lo que no entran en campañas nuevas.

Sus reemplazos activos son los archivos con sufijo `-v2.json` en el directorio
padre. No modificar los originales: una repetición histórica debe referirse a
esta copia de compatibilidad explícitamente.
