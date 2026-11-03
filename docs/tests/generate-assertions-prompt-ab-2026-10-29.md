# Comparación de prompts de Generate Assertions — 2026-10-29

Decisión: **mantener el prompt original**. En esta prueba pequeña, quitar el
ejemplo JSON o compactar las instrucciones redujo los tokens de entrada, pero
no mejoró la latencia y produjo pérdidas observables de calidad.

## Método

- Clúster local `kind-trust-news`, servicio `generate-asertions`, modelo
  configurado `openai/gpt-5-nano` vía OpenRouter. Misma imagen, esquema
  estructurado y tres textos para todas las variantes.
- Casos: `eu-official-statistics-2025-v2`,
  `spain-official-statistics-2025-v2` y `eu-institutions-and-law-v1` de
  `tests/data/benchmark/resources/cases/historical/pre-gold-v0/`. Cada caso
  contiene tres afirmaciones factuales.
- Se cambió temporalmente solo `PROMPT` en el ConfigMap y se reinició el
  deployment antes de cada tanda. La generación se invocó dentro del pod
  mediante `extract_assertions_from_text`, sin leer la clave del proveedor ni
  consumir cuota de usuario en `/extraer`. Se midió la duración y el uso de
  tokens registrados por el servicio; no se midieron cuotas ni latencia HTTP.
- Una ejecución por caso y variante, en orden original → sin ejemplo →
  compacto. Por tanto, las diferencias de tiempo no son una estimación
  estadística robusta y pueden incluir variación del proveedor.

| Prompt | Caracteres de instrucciones | Tokens de entrada, mediana | Tokens de salida, suma | Duración mediana | Respuestas válidas / reparaciones |
| --- | ---: | ---: | ---: | ---: | --- |
| Original | 3.841 | 3.701 | 21.201 | 52,0 s | 3/3; 0 |
| Sin ejemplo JSON | 2.689 | 3.386 | 26.637 | 56,5 s | 3/3; 0 |
| Compacto | 741 | 2.930 | 28.138 | 65,0 s | 3/3; 0 |

Duraciones por caso, en el orden indicado: original `52,0 / 48,5 / 55,8 s`;
sin ejemplo `56,5 / 55,1 / 76,9 s`; compacto `45,8 / 65,0 / 100,8 s`.
Las nueve respuestas contienen tres aserciones y pasan el esquema Pydantic,
pero eso no equivale a mantener la calidad semántica.

## Revisión de calidad

- En el caso del RGPD, el original conserva «se aplica desde 2018, no desde
  2020»; ambas variantes acortadas omiten la negación «no desde 2020». El gold
  de este caso formula positivamente 2020, en contradicción con el texto de
  entrada, por lo que el emparejamiento automático lo marca incompatible
  incluso para el original. Esta diferencia se revisó directamente en las
  aserciones generadas.
- En el caso de España/Alemania/Francia, el prompt compacto asigna
  `jurisdiction.scope=GLOBAL` a las tres aserciones, mientras que el original
  y la variante sin ejemplo asignan respectivamente `COUNTRY/ES`,
  `COUNTRY/DE` y `COUNTRY/FR`. También omite `100 %` en las consultas sugeridas
  para Francia.
- La variante sin ejemplo retiene «según las estadísticas demográficas
  oficiales» en una aserción, pese a que el original elimina esa atribución
  no esencial.
- El evaluador existente de generación detecta emparejamientos léxicos en los
  tres casos, pero sus diagnósticos `PARTIAL` incluyen anotaciones gold
  imperfectas. No se ha usado esa etiqueta como prueba de equivalencia.

## Estado final

Se restauró el contenido original completo del ConfigMap, se reinició el
deployment y se comprobó que quedó disponible. El `PROMPT` activo y los
demás valores del ConfigMap coinciden con los anteriores a la prueba. No se
modificó el ConfigMap versionado ni el código de producción.

La hipótesis de que acortar solo el prompt acelera la generación no queda
respaldada por esta muestra. Una siguiente optimización tendría que preservar
las negaciones y la jurisdicción, y controlar el volumen de tokens generados;
requeriría un nuevo ensayo emparejado antes de activarse.
