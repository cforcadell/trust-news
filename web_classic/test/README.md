# Regresión reproducible del frontend clásico

Este directorio contiene dos niveles de ejecución:

- `ui-smoke-test.js` ejecuta un único escenario mediante Chrome DevTools
  Protocol, sin Playwright, Selenium ni dependencias npm;
- `run-regression.js` valida y ejecuta de forma secuencial los casos sintéticos
  Light y Blockchain, agrega sus resultados y devuelve error si falla cualquier
  comprobación.

El runner está pensado para el entorno local/Kind servido en
`https://localhost:7443/gui/`. Chrome acepta el certificado autofirmado dentro
de un perfil temporal aislado.

## Contenido

```text
web_classic/test/
├── run-regression.js
├── ui-smoke-test.js
├── identities.example.json
└── cases/
    ├── light.json
    ├── light-news.txt
    ├── blockchain.json
    └── blockchain-news.txt
```

Los textos son sintéticos. Los resultados esperados son invariantes
estructurales y operativas; no se compara literalmente el texto producido por
un LLM.

## Qué se comprueba

Cada escenario:

1. abre el frontend y completa el login de Keycloak;
2. publica exactamente una noticia con el modo indicado;
3. exige un `order_id` UUID válido;
4. sigue la orden hasta un estado terminal;
5. falla ante timeout, `ERROR`, `FAILED`, `QUOTA_EXCEDED`,
   `ASSERTIONS_NOT_AVAILABLE`, `NO_VALIDATORS_AVAILABLE` o cualquier estado no
   permitido por el caso;
6. comprueba modo, campos de orden, aserciones, validaciones, validadores
   pendientes y pestañas habilitadas/deshabilitadas;
7. falla ante respuestas HTTP o errores de consola no incluidos expresamente
   en la lista permitida;
8. captura vistas de escritorio y móvil.

El caso Blockchain exige además `cid`, `post_id`, `tx_hash` y la pestaña IPFS
habilitada. El caso Light exige esa pestaña deshabilitada.

## Requisitos

- Node.js 22 o posterior, por el soporte nativo de `fetch`, `WebSocket` y
  `AbortSignal.timeout`.
- Google Chrome; por defecto `/usr/bin/google-chrome`.
- El perfil `apis-frontend` desplegado y accesible.
- Dos usuarios pseudónimos de Keycloak con cuotas suficientes: uno asociado a
  `org-alpha` y otro a `org-beta`.
- Validadores disponibles para las categorías generadas.

`identities.example.json` define los alias y los nombres de variables para
administradores, usuarios y clientes API de las dos organizaciones. No contiene
usuarios reales, contraseñas ni secretos.

## Validar el paquete sin ejecutar la aplicación

La validación comprueba los JSON, modos, identidades y ficheros de noticias, sin
abrir Chrome ni necesitar credenciales:

```bash
node web_classic/test/run-regression.js --validate
```

Se escriben `manifest.json` y `summary.json` en un directorio temporal y el
proceso termina con código cero si los casos son válidos.

## Ejecutar Light y Blockchain

Las contraseñas se leen de forma interactiva y se mantienen únicamente en
variables de entorno del runner:

```bash
export ASSERMETRY_ORG_ALPHA_USERNAME=regression-alpha-user
read -rsp "Password org-alpha: " ASSERMETRY_ORG_ALPHA_PASSWORD
export ASSERMETRY_ORG_ALPHA_PASSWORD
printf '\n'

export ASSERMETRY_ORG_BETA_USERNAME=regression-beta-user
read -rsp "Password org-beta: " ASSERMETRY_ORG_BETA_PASSWORD
export ASSERMETRY_ORG_BETA_PASSWORD
printf '\n'

node web_classic/test/run-regression.js

unset ASSERMETRY_ORG_ALPHA_PASSWORD ASSERMETRY_ORG_BETA_PASSWORD
```

El orquestador asigna un perfil nuevo de Chrome a cada escenario y ejecuta los
casos secuencialmente. Las credenciales de una organización no se entregan al
escenario de la otra y Chrome se inicia con las variables sensibles eliminadas
de su entorno.

La línea final es una de estas:

```text
REGRESSION_RESULT PASS
REGRESSION_RESULT FAIL
```

Un `PASS` sin ciclo de datos configurado certifica las comprobaciones
funcionales, pero `summary.json` mantiene `managedState: false`. Para afirmar
que la ejecución parte de un estado reproducible debe usarse el modo estricto
descrito a continuación.

## Inicialización y limpieza

La API pública no ofrece una operación segura para borrar una orden completa y
una ejecución Blockchain deja efectos no reversibles en IPFS y en la cadena.
El orquestador no borra colecciones, PVC ni datos ajenos.

La preparación y la limpieza se integran mediante dos ejecutables controlados
por el operador:

```bash
export ASSERMETRY_SETUP_HOOK=/ruta/segura/setup-regression
export ASSERMETRY_CLEANUP_HOOK=/ruta/segura/cleanup-regression
export ASSERMETRY_REQUIRE_MANAGED_STATE=true

node web_classic/test/run-regression.js
```

Los hooks se ejecutan directamente, sin `shell`, argumentos ni interpolación.
Reciben estas variables:

| Variable | Significado |
| --- | --- |
| `ASSERMETRY_RUN_ID` | Identificador único de la ejecución. |
| `ASSERMETRY_ARTIFACTS_DIR` | Directorio donde leer o escribir evidencia. |
| `ASSERMETRY_CASES` | Lista separada por comas de los casos ejecutados. |

Contrato recomendado:

- `setup` crea o restablece exclusivamente cuotas y datos de las identidades
  sintéticas declaradas;
- ambos hooks son idempotentes;
- `cleanup` lee los `report.json`, actúa únicamente sobre los IDs incluidos en
  `createdResources` y conserva evidencia de lo retirado;
- no se intenta revertir una transacción Blockchain ni eliminar contenido IPFS
  por su CID;
- cualquier error devuelve un código distinto de cero.

Con `ASSERMETRY_REQUIRE_MANAGED_STATE=true`, la ausencia o el fallo de uno de
los hooks hace fallar la regresión. Sin esa variable, los hooks son opcionales y
su estado queda reflejado en el informe.

## Repetir tres veces

Una vez configurados hooks idempotentes, pueden obtenerse tres ejecuciones
comparables:

```bash
for repetition in 1 2 3; do
  ASSERMETRY_RUN_ID="regression-${repetition}" \
    ASSERMETRY_ARTIFACTS_DIR="/tmp/assermetry-regression-${repetition}" \
    node web_classic/test/run-regression.js || break
done
```

Cada repetición debe terminar en `PASS`, partir de las mismas cuotas/datos y
mantener las mismas invariantes. Los IDs, timestamps, duraciones y textos LLM
pueden variar.

## Línea base de Kubernetes

El orquestador puede capturar una fotografía de nodos, pods, reinicios, consumo
de CPU/memoria y PVC mediante operaciones de solo lectura:

```bash
ASSERMETRY_CAPTURE_K8S_BASELINE=true \
  node web_classic/test/run-regression.js
```

Esto crea `kubernetes-baseline.json`. Si la captura debe ser obligatoria:

```bash
ASSERMETRY_REQUIRE_K8S_BASELINE=true \
  node web_classic/test/run-regression.js
```

En el segundo caso, cualquier fallo de `kubectl` hace fallar la ejecución.

## Ejecutar un único caso

El runner individual mantiene un modo interactivo compatible:

```bash
export ASSERMETRY_USERNAME=regression-alpha-user
read -rsp "Password: " ASSERMETRY_PASSWORD
export ASSERMETRY_PASSWORD

ASSERMETRY_CASE_FILE=web_classic/test/cases/light.json \
  node web_classic/test/ui-smoke-test.js

unset ASSERMETRY_PASSWORD
```

Sin `ASSERMETRY_CASE_FILE` usa `docs/fake_news/news.txt` y modo Light, pero esa
ejecución es un smoke manual y no sustituye el paquete sintético completo.

## Configuración

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `ASSERMETRY_URL` | `https://localhost:7443/gui/` | URL del frontend. |
| `ASSERMETRY_CASES` | Casos Light y Blockchain incluidos | Lista de JSON separada por comas. |
| `ASSERMETRY_CASE_FILE` | Vacío | Caso usado por el runner individual. |
| `ASSERMETRY_RUN_ID` | Fecha y hora | Identificador de ejecución. |
| `ASSERMETRY_ARTIFACTS_DIR` | Directorio fechado en `/tmp` | Evidencia agregada. |
| `ASSERMETRY_ORG_ALPHA_USERNAME` | Obligatoria | Usuario pseudónimo del caso Light. |
| `ASSERMETRY_ORG_ALPHA_PASSWORD` | Obligatoria | Contraseña del caso Light; nunca se informa. |
| `ASSERMETRY_ORG_BETA_USERNAME` | Obligatoria | Usuario pseudónimo del caso Blockchain. |
| `ASSERMETRY_ORG_BETA_PASSWORD` | Obligatoria | Contraseña del caso Blockchain; nunca se informa. |
| `ASSERMETRY_RESULT_TIMEOUT_MS` | Valor del caso | Límite de seguimiento. |
| `ASSERMETRY_CDP_TIMEOUT_MS` | `15000` | Timeout de cada operación CDP. |
| `ASSERMETRY_DEBUG_PORT` | `9223` | Primer puerto CDP; se incrementa por caso. |
| `ASSERMETRY_MOBILE_WIDTH` | `390` | Ancho móvil. |
| `ASSERMETRY_MOBILE_HEIGHT` | `844` | Alto móvil. |
| `CHROME_BIN` | `/usr/bin/google-chrome` | Ejecutable de Chrome. |
| `ASSERMETRY_STOP_ON_FAILURE` | `false` | No iniciar más casos tras el primero fallido. |
| `ASSERMETRY_SETUP_HOOK` | Vacío | Ejecutable de preparación idempotente. |
| `ASSERMETRY_CLEANUP_HOOK` | Vacío | Ejecutable de limpieza acotada. |
| `ASSERMETRY_REQUIRE_MANAGED_STATE` | `false` | Exigir preparación y limpieza. |
| `ASSERMETRY_CAPTURE_K8S_BASELINE` | `false` | Capturar recursos de Kubernetes. |
| `ASSERMETRY_REQUIRE_K8S_BASELINE` | `false` | Exigir una captura completa. |
| `ASSERMETRY_PROVIDER` | Vacío | Metadato no secreto del proveedor. |
| `ASSERMETRY_MODEL` | Vacío | Metadato no secreto del modelo. |
| `ASSERMETRY_HTTP_TIMEOUT_SECONDS` | Vacío | Metadato del timeout LLM. |

`ASSERMETRY_NEWS`, `ASSERMETRY_NEWS_FILE` y
`ASSERMETRY_VALIDATION_MODE` siguen disponibles para el smoke individual. El
orquestador los elimina de cada proceso hijo para que no sobrescriban los casos
versionados.

El directorio de artefactos debe ser nuevo o estar vacío. El runner nunca
mezcla ni sobrescribe evidencia de una ejecución anterior.

## Artefactos

```text
assermetry-regression-<run-id>/
├── manifest.json
├── summary.json
├── kubernetes-baseline.json       # opcional
├── synthetic-light-01/
│   ├── report.json
│   └── 01-...06-*.png
└── synthetic-blockchain-01/
    ├── report.json
    └── 01-...06-*.png
```

`manifest.json` registra commit, estado limpio/sucio del repositorio, versiones
de Node/Chrome, casos y metadatos no secretos. `summary.json` agrega duración,
órdenes creadas, comprobaciones y fallos HTTP.

Los informes no guardan contraseñas, tokens, query strings, prompts, respuestas
LLM completas, texto completo de la noticia, orden o pestañas. Los textos se
representan mediante tamaño y SHA-256. Las capturas sí contienen datos visibles
de las identidades pseudónimas y deben conservarse con la misma protección que
el resto de la evidencia de prueba.

## Resultado y código de salida

El código es cero únicamente cuando:

- se ejecutan todos los casos solicitados;
- todos sus checks terminan en `PASS`;
- no hay estados terminales, errores HTTP o errores de consola inesperados;
- los hooks obligatorios terminan correctamente;
- la línea base obligatoria se captura por completo.

Un fallo sigue generando `report.json` y `summary.json` siempre que haya sido
posible inicializar sus directorios, facilitando el diagnóstico sin convertir
el error en un falso positivo.
