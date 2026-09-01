# Prueba E2E visual del frontend clásico

`ui-smoke-test.js` automatiza con Chrome una comprobación funcional y visual de
`web_classic`. Utiliza directamente Chrome DevTools Protocol y no necesita
Playwright, Selenium ni dependencias npm.

La prueba ignora el certificado autofirmado de `localhost`. Está pensada para el
entorno local/Kind y no para producción.

## Qué comprueba

Ejecuta exactamente cuatro escenarios dentro de una misma sesión:

1. Abre el frontend, pasa por Keycloak e inicia sesión.
2. Envía una noticia y crea **una única orden**.
3. Sigue esa misma orden hasta un estado final o hasta el timeout, y revisa sus
   pestañas de resultado.
4. Cambia el viewport a tamaño móvil y captura el resultado y el formulario.

Por tanto, cuatro pruebas no significan cuatro órdenes. Solo el escenario 2
modifica datos, consume cuotas y crea una orden. Los escenarios 1, 3 y 4 son
comprobaciones de acceso, lectura y presentación.

## Requisitos

- Node.js 22 o posterior, por el soporte nativo de `fetch` y `WebSocket`.
- Google Chrome. Por defecto se utiliza `/usr/bin/google-chrome`.
- El perfil `apis-frontend` levantado y accesible en
  `https://localhost:7443/gui/`.
- Un usuario de Keycloak con cuotas suficientes.

## Uso

Desde la raíz del repositorio:

```bash
export ASSERMETRY_USERNAME=codex
read -rsp "Password de Keycloak: " ASSERMETRY_PASSWORD
export ASSERMETRY_PASSWORD
printf '\n'

node web_classic/test/ui-smoke-test.js

unset ASSERMETRY_PASSWORD
```

Por defecto se utiliza el contenido de `docs/fake_news/news.txt` y se crea una
validación `LIGHT`.

La ejecución imprime progresivamente estados como:

```text
TEST_1_OK acceso_y_autenticacion
TEST_2_OK order_id=<uuid>
ORDER_STATUS VALIDATION_PENDING
TEST_3_DONE final_status=<estado>
TEST_4_OK responsive
REPORT /tmp/assermetry-ui-<fecha>/report.json
ORDERS_CREATED 1
```

## Configuración opcional

| Variable | Valor predeterminado | Uso |
| --- | --- | --- |
| `ASSERMETRY_URL` | `https://localhost:7443/gui/` | URL del frontend. |
| `ASSERMETRY_USERNAME` | Obligatoria | Usuario de Keycloak. |
| `ASSERMETRY_PASSWORD` | Obligatoria | Contraseña de Keycloak. No se escribe en el informe. |
| `ASSERMETRY_NEWS` | Vacía | Texto literal que se validará. Tiene prioridad sobre el fichero. |
| `ASSERMETRY_NEWS_FILE` | `docs/fake_news/news.txt` | Fichero con el texto que se validará. |
| `ASSERMETRY_VALIDATION_MODE` | `LIGHT` | `LIGHT` o `BLOCKCHAIN`. |
| `ASSERMETRY_RESULT_TIMEOUT_MS` | `300000` | Espera máxima del resultado. |
| `ASSERMETRY_ARTIFACTS_DIR` | Directorio fechado en `/tmp` | Destino del informe y las capturas. |
| `ASSERMETRY_MOBILE_WIDTH` | `390` | Ancho del viewport móvil. |
| `ASSERMETRY_MOBILE_HEIGHT` | `844` | Alto del viewport móvil. |
| `ASSERMETRY_DEBUG_PORT` | `9223` | Puerto local de Chrome DevTools. |
| `CHROME_BIN` | `/usr/bin/google-chrome` | Ruta del ejecutable de Chrome. |

Ejemplo usando otro texto y modo Blockchain:

```bash
ASSERMETRY_NEWS_FILE=/ruta/noticia.txt \
ASSERMETRY_VALIDATION_MODE=BLOCKCHAIN \
node web_classic/test/ui-smoke-test.js
```

## Artefactos

La ruta final se muestra en la línea `REPORT`. El directorio contiene:

- `report.json`: estados, contenido visible, respuestas HTTP fallidas, mensajes
  de consola y datos de la orden;
- `01-login-desktop.png` y `02-home-desktop.png`;
- `03-after-submit-desktop.png` y `04-result-desktop.png`;
- `05-result-mobile.png` y `06-home-mobile.png`.

Los artefactos pueden contener el texto validado, el ID de usuario efectivo, el
ID de orden y evidencias recuperadas. No contienen la contraseña, pero deben
tratarse como datos de prueba y eliminarse cuando ya no sean necesarios.

## Alcance y precauciones

- La prueba acepta certificados no confiables únicamente en el Chrome temporal.
- Cada ejecución completa crea una orden real y consume sus cuotas asociadas.
- No se deben ejecutar varias instancias con el mismo
  `ASSERMETRY_DEBUG_PORT`.
- El perfil temporal de Chrome se elimina al terminar.
- El informe describe lo que mostró la aplicación; no sustituye una auditoría
  de accesibilidad ni una verificación factual independiente.
