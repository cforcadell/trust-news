La orden 8fd3fa77-2206-44d8-8411-0efe1ecd7eab terminó correctamente: 12/12 validaciones completadas, sin errores de ejecución, en unos 130 segundos. El estado VALIDATED indica que terminó el proceso, no que todas las afirmaciones sean verdaderas.
Resultado
He reproducido el consenso con los votos almacenados; todos tienen peso 1.
Aserción	LOCAL	EXT_OFFICIAL_FIRST	EXT_ONLY_OFFICIAL	Consenso
Suecia: refuerzo de vacunación	UNKNOWN	TRUE	UNKNOWN	UNKNOWN
Alemania: reducción de emisiones	TRUE	TRUE	UNKNOWN	TRUE
Italia: prohibición total a turistas	FALSE	UNKNOWN	FALSE	FALSE
España: eliminación de idiomas obligatorios	FALSE	FALSE	UNKNOWN	FALSE


Suecia queda sin decisión porque solo 1 de 3 votos es decisivo: no supera el umbral del 50 %.
Cómo funcionó LOCAL
Los cambios del clasificador están funcionando. Hubo errores en el primer intento —tipos inventados como GOVERNMENT, GOVERNMENT_OFFICIAL o GOVERNMENT_RECORD usados como tipo de fuente—, pero el segundo intento los corrigió. Al terminar, las cuatro rutas tenían failed_domains=[]. No fue necesario recurrir a perfiles de respaldo.
Suecia: el problema está en el descubrimiento
Consulta exacta enviada a Exa:
official government record health public health SE
Devolvió:
- moh.gov.jm
- govinfo.gov
- gov.br
- sos.state.co.us
- health-new.mo.gov
Ninguno correspondía a Suecia. El router los clasificó y descartó por elegibilidad, devolviendo NO_ELIGIBLE_SOURCES. No llegó a buscar evidencias.
No es otro fallo de clasificación: la consulta no identifica suficientemente el país. Usar únicamente SE como referencia geográfica produce resultados poco fiables.
Alemania: recuperación correcta
Seleccionó bundesfinanzministerium.de y bundeswirtschaftsministerium.de; descartó destatis.de y genesis.destatis.de.
Recuperó cinco documentos y emitió TRUE. Una cita fue rechazada por no aparecer en el texto recuperado, pero conservó otra sobre un paquete de descarbonización industrial.
Italia: recuperación útil, descubrimiento ruidoso
De cinco dominios descubiertos, solo quedó gazzettaufficiale.it. Los otros pertenecían a India, Seychelles y Corea del Sur.
Recuperó cinco documentos y emitió FALSE; de cinco citas propuestas, conservó dos. La justificación requiere cautela: que un documento no mencione una prohibición no demuestra por sí solo que no exista. La referencia al acceso de guías aporta más información, pero tampoco equivale exactamente al acceso de todos los turistas.
España: recuperación correcta, ruta distinta
Seleccionó educacionfpydeportes.gob.es y libreria.educacion.gob.es. Recuperó cinco documentos y emitió FALSE, apoyándose en un fragmento sobre la obligatoriedad de la primera lengua extranjera.
Esta vez el generador asignó GOVERNMENT_RECORD, no LEGAL_TEXT. Por eso creó una ruta diferente a la de boe.es que habíamos eliminado.
Por qué quedan cinco votos UNKNOWN
No tienen todos la misma causa:
- Tres por falta de evidencias: Suecia en LOCAL y Suecia/Alemania en EXT_ONLY_OFFICIAL.
- Dos por citas no verificables o sin apoyo al veredicto: Italia en EXT_OFFICIAL_FIRST y España en EXT_ONLY_OFFICIAL. El modelo había respondido FALSE, pero el control documental lo convirtió en UNKNOWN.
Además, el TRUE de Suecia es débil: el modelo interpreta que evaluar un programa demuestra que se reforzó. La cita acredita seguimiento, no necesariamente refuerzo. El verificador actual comprueba correspondencia textual y la orientación declarada por el modelo, no toda la validez lógica de esa inferencia.
Mejoras prioritarias
1. Mejorar las consultas geográficas: usar nombres completos como Sweden/Sverige, no solo SE, y hacer un segundo descubrimiento cuando todos los candidatos sean descartados. Actualmente se genera una única consulta en [query_builder.py (line 24)](/home/adminu/blockchain/tfm/api/source-router/app/query_builder.py:24).
2. Corregir el límite efectivo de resultados: el router pide 12, pero Exa recibe como máximo 5, porque SEARCH_MAX_RESULTS no está definido y el adaptador aplica ese valor por defecto. [exa.py (line 40)](/home/adminu/blockchain/tfm/api/common/search/exa.py:40).
3. Exigir apoyo semántico suficiente: distinguir “existe/se evalúa” de “se reforzó”, y “no aparece una prohibición” de “se demuestra que es falsa”.
4. Estabilizar la extracción: Alemania se clasificó como ECONOMY_MACRO, y España cambió de tipo de evidencia entre pruebas; eso cambia las fuentes descubiertas.
Se guardaron tres rutas nuevas con vigencia de 30 días; Suecia no creó una ruta vacía. Las búsquedas de evidencias ejecutadas registraron cached=false.
No he modificado datos ni código durante este análisis.