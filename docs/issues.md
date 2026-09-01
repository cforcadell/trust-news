# Issues detectados

Este documento registra incidencias descubiertas durante el despliegue y las
pruebas de cada version de Assermetry. No sustituye a un gestor de tareas: sirve
como inventario tecnico versionado, sin secretos, direcciones de infraestructura
ni datos personales.

Estados utilizados:

- **Abierto**: reproducido y pendiente de correccion.
- **Mitigado**: existe una recuperacion operativa, pero la causa permanece.
- **Resuelto**: la correccion esta implementada y validada.
- **Descartado**: no requiere cambio, con la justificacion documentada.

---

## v0.0.12 - Exposicion controlada de Assermetry en Internet

### ISSUE-001 - Carrera de inicializacion en la cache de validadores LIGHT

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-08-13 |
| Entorno | Hetzner, perfil `apis-frontend-prod` |
| Fase | 5.2 - Metodos, cuerpos y rechazos |
| Estado | **Mitigado; correccion pendiente** |
| Versión objetivo | `v0.0.13` |
| Componentes | `news-handler`, `validate-asertions`, Kafka, blockchain/IPFS |

#### Comportamiento detectado

Tras desplegar simultaneamente News Handler y los tres workers, una orden LIGHT
con tres aserciones genero solo tres eventos `light_validation_request`: cada
asercion se asigno al mismo validador. El resultado esperado eran nueve eventos,
uno por cada pareja asercion/validador.

Los tres deployments estaban preparados, sus Services resolvian correctamente y
los tres endpoints `/health` devolvian `200`, con tipo automatico, `ai_ready=true`
y categorias `[1,2,3,4,5,6,7,8,9,10]`. Los workers tambien publicaron sus eventos
de configuracion durante el arranque.

#### Diagnostico

News Handler selecciona los validadores antes de publicar en Kafka. Usa una
cache en memoria cargada desde blockchain/IPFS y actualizada mediante eventos de
configuracion. Durante el reinicio conjunto, la seleccion uso una vista
transitoria en la que solo un validador resultaba elegible.

La presencia de tres pods no garantiza por si sola tres validaciones: News
Handler filtra previamente por estado, tipo automatico, categoria, `service_url`
y healthcheck. Kafka solo recibe los destinos que sobreviven a esa seleccion.

El mecanismo exacto de intercalado entre la carga inicial y los eventos de
configuracion debe cubrirse con pruebas de concurrencia; el refresco posterior
demostro que la fuente autoritativa contenia correctamente los tres validadores.

#### Mitigacion aplicada

Se forzo un refresco de la cache de News Handler desde blockchain/IPFS mediante
el endpoint interno de validadores con `recover_ipfs=true`. No se modificaron
blockchain, IPFS ni MongoDB.

La siguiente orden LIGHT genero correctamente:

- tres aserciones;
- tres validadores por asercion;
- nueve eventos `light_validation_request`;
- nueve respuestas de validacion.

La mitigacion recupera el estado actual, pero la incidencia puede repetirse en
otro despliegue simultaneo.

#### Propuesta de mejora

Implementar una cache con frescura acotada dentro de News Handler:

1. Registrar `validators_cache_refreshed_at` con reloj monotonico.
2. Antes de despachar una orden LIGHT, refrescar una sola vez desde
   blockchain/IPFS si la cache supera un TTL inicial de 30 segundos.
3. Proteger el refresco con `asyncio.Lock` para que ordenes concurrentes
   compartan una unica consulta.
4. Construir la nueva cache fuera de la referencia activa y sustituirla de forma
   atomica solo tras una carga completa valida.
5. Si la carga falla o devuelve un vacio inesperado, conservar la ultima cache
   valida y emitir un warning.
6. Mantener los eventos Kafka como via de actualizacion inmediata y añadir un
   refresco periodico de respaldo, inicialmente cada 60 segundos.
7. Registrar por despacho los contadores `cached`, `eligible`, `healthy` y
   `selected`, junto con la razon de descarte de cada candidato.

No se propone refrescar por asercion: una sola instantanea coherente debe usarse
para toda la orden.

#### Pruebas de aceptacion propuestas

- Una cache reciente no provoca consultas adicionales.
- Una cache caducada se refresca una vez por orden.
- Varias ordenes concurrentes producen un unico refresco.
- Un fallo de blockchain/IPFS conserva la ultima cache valida.
- Una carga vacia inesperada no borra una cache valida.
- Los eventos de configuracion recibidos durante un refresco no se pierden ni
  quedan sobrescritos por una instantanea anterior.
- Un arranque donde los validadores aparecen de forma escalonada converge a los
  tres sin intervencion manual.
- Tres aserciones y tres validadores elegibles generan exactamente nueve
  solicitudes y nueve respuestas LIGHT.

#### Criterio de resolucion

Marcar como **Resuelto** cuando la mejora este implementada, las pruebas de
concurrencia pasen y un despliegue conjunto en Kind y Hetzner seleccione los
tres validadores sin refresco manual.


### ISSUE-002 - Secret OIDC no vacio como valor por defecto en tests

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-08-19 |
| Entorno | Repositorio y credenciales de tests; produccion descartada |
| Fase | 6 - Despliegue definitivo todavia cerrado (cerrada) |
| Estado | **Resuelto** |
| Componentes | `api/tests`, Keycloak, clientes B2B y CI/CD |

#### Comportamiento detectado

La fixture de autenticacion de las pruebas define un valor por defecto no vacio
para `AUTH_CLIENT_SECRET`. El valor no se reproduce en este documento. El operador comparo el valor por una via que no lo expuso en logs ni
documentacion y confirmo que no coincide con el secret productivo de
`TrustNewsApi`. No se requiere rotacion productiva por este hallazgo. Falta
determinar si corresponde a una credencial de tests todavia activa. La copia de
trabajo sustituye el valor por defecto no vacio por uno vacio, sin revelar el
valor anterior. Esta correccion resuelve la incidencia y no bloquea la Fase 7.

La prueba operativa del 2026-08-19 obtuvo un token `client_credentials` mediante
un secret proporcionado de forma interactiva. No se registra si era el mismo
valor y no debe compararse mediante logs, comandos versionados o documentacion.

#### Seguimiento recomendado no bloqueante

1. En una mejora posterior, hacer que la fixture exija `AUTH_CLIENT_SECRET`
   explicitamente y falle antes de realizar una peticion cuando la variable no
   exista.
2. Revisar de forma autorizada el historial y el entorno de tests para
   determinar a que credencial pertenece, sin copiar el valor a incidencias ni
   logs.
3. Si la credencial de tests sigue activa, revocarla o rotarla y actualizar su
   gestor de secretos. No rotar `TrustNewsApi` de produccion por este hallazgo.
4. Ejecutar una busqueda de secretos y conservar solo evidencias anonimizadas.

#### Resolucion

**Resuelto el 2026-08-19.** El valor por defecto no vacio se elimino y el
operador confirmo que no coincide con el secret productivo. No se requiere
rotacion de `TrustNewsApi`. La comprobacion y eventual revocacion de una
credencial historica de tests se conserva como recomendacion independiente.

### ISSUE-003 - CI no autentica el API de K3s con su CA

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-08-21 |
| Entorno | GitLab CI, acceso al API de K3s mediante tunel SSH |
| Fase | Revision independiente de confianza del pipeline |
| Estado | **Abierto** |
| Prioridad | **P1** |
| Version objetivo | `v0.0.16` |
| Componentes | `.gitlab-ci.yml`, `KUBECONFIG_DATA`, `kubectl`, K3s |

#### Comportamiento detectado

La plantilla `.kube_access` restaura `KUBECONFIG_DATA`, cambia el endpoint del
cluster `default` a `https://127.0.0.1:6443` y activa
`--insecure-skip-tls-verify=true`. Esta opcion evita que `kubectl` autentique el
certificado del API de K3s, incluso si el kubeconfig contiene la CA correcta.
El tunel cifra y limita el recorrido de red, pero no sustituye la validacion TLS
del servidor.

#### Riesgo

El pipeline puede aceptar un API que no presente un certificado firmado por la
CA esperada. El impacto aumenta al combinarse con `ISSUE-004`: actualmente la
identidad del servidor tampoco queda fijada en la capa SSH. Una suplantacion de
ambas capas podria proporcionar respuestas falsas al pipeline y, segun el tipo
de credencial del kubeconfig, exponer credenciales reutilizables.

#### Correccion prevista

1. Exigir que el kubeconfig productivo incluya la CA real de K3s mediante
   `certificate-authority-data` o una CA proporcionada como variable protegida.
2. Eliminar `--insecure-skip-tls-verify=true` y cualquier valor equivalente del
   kubeconfig efectivo.
3. Mantener el endpoint del tunel y, solo si el certificado lo requiere, fijar
   un nombre TLS que forme parte de sus SAN.
4. Verificar antes del despliegue que existen CA y validacion de nombre, sin
   imprimir certificados, credenciales ni datos de infraestructura.
5. Añadir pruebas negativas con CA ausente o incorrecta y nombre TLS no valido.

#### Criterio de resolucion

Marcar como **Resuelto** cuando todos los jobs que usan `.kube_access`
autentiquen K3s con la CA real, no permitan omitir TLS y fallen antes de
desplegar ante una CA o un nombre TLS incorrectos. La configuracion valida debe
seguir permitiendo las comprobaciones y despliegues de todos los perfiles.


### ISSUE-004 - CI no fija la clave SSH del servidor

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-08-21 |
| Entorno | GitLab CI, tunel SSH hacia Hetzner por `2222/tcp` |
| Fase | Revision independiente de confianza del pipeline |
| Estado | **Abierto** |
| Prioridad | **P1** |
| Version objetivo | `v0.0.16` |
| Componentes | `.gitlab-ci.yml`, GitLab CI/CD, OpenSSH, tunel de K3s |

#### Comportamiento detectado

La plantilla `.kube_access` ejecuta `ssh-keyscan` contra la direccion recibida
por el job y guarda inmediatamente esa respuesta en `known_hosts`. La conexion
posterior comprueba que la clave coincide con la observada en ese mismo
pipeline, pero no con una clave aprobada previamente por un canal independiente.
La opcion `-H` oculta el host almacenado; no autentica la clave.

#### Riesgo

Un intermediario presente durante `ssh-keyscan` y la conexion puede presentar
su propia clave y recibir el tunel. La clave privada de despliegue autentica el
cliente ante el servidor, pero no demuestra al cliente que el servidor sea el
Hetzner esperado. La ausencia simultanea de validacion TLS descrita en
`ISSUE-003` elimina la segunda barrera de autenticacion del API.

#### Correccion prevista

1. Obtener y verificar fuera de banda la clave publica SSH del servidor, sin
   registrar en Git la direccion ni la huella concretas.
2. Guardar la entrada exacta de `known_hosts` en una variable protegida de
   GitLab y escribirla con permisos restrictivos durante el job.
3. Eliminar `ssh-keyscan` del pipeline.
4. Abrir el tunel con `StrictHostKeyChecking=yes`, `BatchMode=yes` y un
   `UserKnownHostsFile` explicito.
5. Documentar la rotacion autorizada de la clave y probar claves ausentes,
   modificadas y desconocidas sin imprimir sus valores.

#### Criterio de resolucion

Marcar como **Resuelto** cuando el tunel solo acepte la clave fijada, una clave
incorrecta falle antes de cualquier acceso a Kubernetes y el pipeline no use
confianza obtenida dinamicamente. La clave valida debe seguir permitiendo los
preflight y despliegues de todos los perfiles.

---

## v0.0.13 - Correccion de consistencia, consenso y evidencia de validacion

### ISSUE-005 - Fechas, zonas horarias y estados temporales inconsistentes en la GUI de resultados

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-09-01 |
| Entorno | Frontend y API de validacion; perfiles LIGHT y BLOCKCHAIN |
| Fase | Regresion de GUI y validacion de ordenes |
| Estado | **Abierto** |
| Prioridad | **P0** |
| Version objetivo | `v0.0.13` |
| Componentes | `web`, `gateway`, `api`, `validate-asertions`, `news-handler` |

#### Comportamiento detectado

En una misma pantalla aparecen eventos con hora local y hora de orden no
alineadas, la orden muestra un tiempo de finalizacion distinto del del mensaje
"Ultima validacion recibida hace 120 min" y la UI mezcla fechas naive con
fechas renderizadas en zona del usuario. El mismo contenido puede mostrarse con
formato estadounidense o sin zona horaria, incluso cuando la validacion acaba de
terminar.

#### Riesgo

El usuario puede interpretar que el resultado tiene una antiguedad distinta a la
real, o que los eventos se produjeron en un orden distinto del que ocurrieron.
Esto afecta directamente a la confianza, a la auditable y a la reproducibilidad
operativa.

#### Correccion prevista

1. Normalizar todas las fechas a UTC ISO 8601 con offset (`2026-08-31T18:19:27.431Z`).
2. Renderizar en la zona horaria del usuario, con formato local y con locale ES.
3. Separar `process_status` y `decision_status` en el modelo de la UI y del API.
4. Sustituir mensajes relativos ambiguos por `hace 2 min` solo si se calcula a
   partir del mismo timestamp origen.
5. Probar trazas sobre horas de inicio, fin, orden y ultimo evento en la misma
   pantalla.

#### Criterio de resolucion

Marcar como **Resuelto** cuando la GUI muestre siempre una fecha unificada por
evento, la zona horaria del usuario sea aplicada de forma consistente y la UI no
mezcle estados temporales con decisiones definitivas.

### ISSUE-006 - Estado provisional/final mezclado en la pantalla de proceso

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-09-01 |
| Entorno | Frontend validacion |
| Fase | Salida de resultado |
| Estado | **Abierto** |
| Prioridad | **P0** |
| Version objetivo | `v0.0.13` |
| Componentes | `web`, `api`, `validate-asertions` |

#### Comportamiento detectado

Cuando la validacion alcanza el 100 %, la pestaña de proceso sigue mostrando
"Resultado provisional" y "Este resultado puede cambiar" aunque el estado del
proceso ya se considera completado. El componente sigue visualmente abierto y el
usuario percibe que el resultado no esta cerrado.

#### Riesgo

El estado final se ve contradictorio con la realidad del flujo. Esto puede llevar
a que se publican conclusiones con una semantica inestable, especialmente en
entornos de demostracion, beta y pilotos externos.

#### Correccion prevista

1. Introducir un estado formal de decision (`PROVISIONAL`, `FINAL`, `NO_CONSENSUS`).
2. Mantener `process_status` distinto de `decision_status`.
3. Cuando un proceso termine correctamente, mostrar `Resultado definitivo` y
   ocultar la advertencia provisional.
4. Probar mensajes en estados `RUNNING`, `COMPLETED`, `COMPLETED_WITH_ERRORS` y
   `NO_CONSENSUS`.

#### Criterio de resolucion

La pantalla debe mostrar un estado coherente y no volver a comunicar un resultado
como provisional una vez que el sistema haya terminado el calculo final.

### ISSUE-007 - Veredicto global y calculo de consenso no explican empates ni decisiones

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-09-01 |
| Entorno | Frontend y motor de evaluacion |
| Fase | Consolidacion del resultado |
| Estado | **Abierto** |
| Prioridad | **P0** |
| Version objetivo | `v0.0.13` |
| Componentes | `validate-asertions`, `gateway`, `web` |

#### Comportamiento detectado

La interfaz puede mostrar un veredicto global "Desmentida" o "Falsa" aunque la
afirmacion haya recibido un reparto como `FALSE 50 %` y `UNKNOWN 50 %`. El
sistema decide sin explicar la regla de desempate ni la diferencia entre votos y
resultado factico final.

#### Riesgo

El usuario no sabe si el sistema aplica un criterio oculto, si hay empate o si la
decision es una conclusion del producto. Esto destruye la confianza en la
valoracion de resultados y complica la auditabilidad.

#### Correccion prevista

1. Evitar que un empate se resuelva automaticamente a favor de uno de los
   resultados.
2. Introducir `NO_CONSENSUS` y mostrar la distribucion exacta de votos.
3. Diferenciar claramente `consenso de validadores` de `resultado factual`.
4. Mostrar siempre la desglose por afirmacion y la distribucion por validador.
5. Probar escenarios `TRUE/TRUE/UNKNOWN`, `FALSE/UNKNOWN/UNKNOWN` y empate 50/50.

#### Criterio de resolucion

Una afirmacion con empate no puede resolverse como efectiva sin explicacion y sin
un estado de consenso declarado. La interfaz debe mostrar la distribucion de
votos y la regla aplicada.

### ISSUE-008 - Validadores con timeout tratados como resultado valido

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-09-01 |
| Entorno | Backend de validacion y frontend |
| Fase | Reintentos y tratamiento de errores |
| Estado | **Abierto** |
| Prioridad | **P0** |
| Version objetivo | `v0.0.13` |
| Componentes | `news-handler`, `validate-asertions`, `web` |

#### Comportamiento detectado

Uno de los validadores termina con `The read operation timed out` y la UI lo
presenta como un resultado valido, sin distinguir la ausencia de evidencia del
resultado `UNKNOWN`.

#### Riesgo

Se produce una mezcla entre resultado de validacion y fallo tecnico. Eso reduce la
fiabilidad del consenso y puede ocultar una degradacion del sistema.

#### Correccion prevista

1. Diferenciar `ERROR`, `TIMEOUT`, `UNKNOWN` y `NO_RESULT` directamente en el
   modelo.
2. Mostrar una alerta legible en español con el validador afectado y la
   afirmacion implicada.
3. Permitir reintento granular de una validacion individual sin repetir el
   conjunto completo.
4. Registrar metricas de fallo por validador y por afirmacion.

#### Criterio de resolucion

Un timeout no debe contarse como voto ni como evidencia; la UI debe indicar que
se ha producido una falla tecnica y cual es el impacto sobre el consenso.

### ISSUE-009 - Flujo de extraccion y clasificacion de afirmaciones no revisable

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-09-01 |
| Entorno | Flujo de validacion de contenido |
| Fase | Generacion y revision de aserciones |
| Estado | **Abierto** |
| Prioridad | **P1** |
| Version objetivo | `v0.0.14` |
| Componentes | `generate-asertions`, `web`, `api` |

#### Comportamiento detectado

Se detectan afirmaciones sin permitir una revision humana previa. La categoria que
asignan puede ser incorrecta, como en el caso de contenido demografico que se
clasifica como ECONOMIA. El flujo actual publica directamente, sin revision ni
edicion.

#### Riesgo

Los errores de extraccion y de clasificacion pueden arrastrarse al resultado
final, degradando la calidad de la validacion y la reputacion del producto.

#### Correccion prevista

1. Cambiar el flujo a `texto -> afirmaciones detectadas -> revisión -> validación`.
2. Permitir editar, eliminar, añadir y re-categorizar afirmaciones antes de
   validarlas.
3. Corregir la taxonomia desde prompts y ejemplos para distinguir demografia,
   economia, salud, tecnologia, etc.
4. Probar casos con expresiones aproximadas y ambiguas.

#### Criterio de resolucion

Un usuario debe poder revisar, corregir y confirmar el conjunto de afirmaciones
antes de iniciar la validacion formal.

### ISSUE-010 - Resultado no presenta evidencia principal ni informe reutilizable

| Campo | Valor |
| --- | --- |
| Fecha de deteccion | 2026-09-01 |
| Entorno | Frontend y exportacion de resultados |
| Fase | Evidencia y pilotaje |
| Estado | **Abierto** |
| Prioridad | **P1** |
| Version objetivo | `v0.0.14` |
| Componentes | `web`, `api`, `evidence-search` |

#### Comportamiento detectado

La pantalla principal exige navegar entre validadores y fuentes para recuperar
la conclusion. No existe un resumen principal de evidencia por afirmacion ni un
informe descargable o compartible con contenido original, veredicto, fuente,
fecha, enlace y limitaciones.

#### Riesgo

La herramienta resulta dificil de usar para analistas, periodistas y equipos de
comunicacion, y su valor real queda oculto si no puede exportarse en formato de
trabajo.

#### Correccion prevista

1. Mostrar por cada afirmacion: original, veredicto, fuente principal, fecha,
   enlace y fragmento relevante.
2. Crear un informe reutilizable con texto original, afirmaciones, veredictos,
   fuentes y limitaciones del analisis.
3. Incluir metadata de procedencia, contexto de contenido generado por IA y
   banderas de revision humana, si aplica.
4. Probar la exportacion en formato texto y PDF o HTML.

#### Criterio de resolucion

El usuario debe poder comprender la conclusion de la orden sin recorrer la
totalidad de los detalles de validacion, y compartir el resultado con una
evidencia clara y legible.

---

Las incidencias anteriores resumen el diagnostico fusionado de la prueba de dos
IAs y se incorporan a la linea de trabajo de la `v0.0.13` y la `v0.0.14`.
La prioridad P0 corresponde a correcciones de coherencia y confianza que deben
resolverse antes de abrir la beta cerrada; la prioridad P1 corresponde a la
revision humana y a la evidencia primera que necesita un piloto con design
partners.
