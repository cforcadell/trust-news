# S02 — Diseño del motor de descarga pública

**Estado:** implementación integrada y validación local en kind completadas; el operador confirma que los E2E autenticados LIGHT/SMART y DIRECT terminaron correctamente. La aceptación de preproducción queda pendiente y fuera de esta ejecución. **Ámbito:** SEC-02 y la prueba de seguridad SEC-19. El motor se comparte entre News Handler y Evidence Search; sus límites y formatos son configuración validada, no excepciones por URL o proveedor.

## Punto de partida

- `api/news-handler/main.py`: `_validate_import_url` resuelve con `getaddrinfo`, pero `requests.Session.get` vuelve a resolver. Ya hay bloqueo de direcciones no públicas, redirecciones, reintentos, bytes y `trust_env=False`. Acepta puertos no estándar y cada timeout se aplica por intento.
- `api/evidence-search/app/document_fetcher.py`: `_validate_fetch_url` resuelve antes de `httpx`; el transporte puede usar otra respuesta DNS. Ya hay puertos 80/443, redirecciones, lectura por streaming, límites de bytes y presupuesto de reintentos. `AsyncClient` no fija `trust_env=False`; se debe eliminar el uso de proxies de entorno en esta ruta.
- `tests/api/test_evidence_search_units.py`: un fixture `autouse` sustituye `_validate_fetch_url` por una función que permite todo; la prueba nominal del validador no ejecuta la función real. Algunos dobles HTTP tampoco implementan la firma real.
- `api/evidence-search/app/acquisition.py`: la validación antes de enviar una URL a un extractor externo es una comprobación previa, no controla la conexión que realiza el proveedor. Este contrato queda explícito en la integración.

## Contrato propuesto

Crear `api/common/utils/public_fetch.py` con una API asíncrona `fetch(url, policy, headers) -> FetchResponse` y un adaptador síncrono para el endpoint `def` de News Handler. `FetchPolicy` es inmutable y valida al arrancar: esquemas, puertos, CIDR denegados adicionales, redirecciones, intentos, timeout total y por fase, bytes de respuesta, codificaciones permitidas y tamaños después de descomprimir. El motor rechaza cabeceras de autoridad o transporte suministradas por el llamante (`Host`, `Proxy-*`, `Connection`, `Transfer-Encoding`) y construye `Host` desde la URL aprobada. `FetchResponse` conserva URL final, estado, cabeceras necesarias, cuerpo acotado y diagnóstico estructurado sin datos sensibles. Los adaptadores conservan sus errores, `FetchResult`, extracción HTML/PDF, clasificación de resultados y contratos HTTP actuales.

El motor sirve **solo a URLs públicas no confiables**. Las llamadas a Admin, Keycloak, Kafka, IPFS, APIs internas y proveedores autenticados siguen sus clientes y contratos propios. Ningún parámetro de la petición del usuario puede ampliar `FetchPolicy`.

## Decisión de destino y conexión

1. Analizar la URL de forma estricta: `http`/`https`, host DNS o IP válido, sin usuario/contraseña, host vacío, fragmento significativo ni puerto ambiguo. Normalizar IDNA y puerto una sola vez; rechazar formatos de IP ambiguos. La política inicial admite únicamente 80 para HTTP y 443 para HTTPS. Un puerto adicional exigiría una decisión de configuración por perfil y evidencia de necesidad.
2. Resolver A y AAAA en el componente que entrega las direcciones al conector. Rechazar si el conjunto está vacío o contiene cualquier dirección no global, reservada, multicast, loopback, link-local, privada o dentro de CIDR denegados configurados. Las IP literales pasan por la misma política. Una respuesta DNS mixta se rechaza completa.
3. Usar un conector con resolver propio que entregue al socket **solo** las direcciones aprobadas para ese host y puerto; prohibir un segundo resolver en el camino de conexión. La implementación usa `aiohttp.TCPConnector` con `resolver` controlado, caché DNS desactivada y conexiones sin reutilización entre saltos. La URL original se mantiene como autoridad HTTP y nombre de verificación TLS/SNI; la IP solo selecciona el socket. Verificar certificados con el almacén de CA habitual y `check_hostname`; jamás degradar a `verify=False`.
4. Desactivar proxies de entorno y configuración automática (`trust_env=False` y sin proxy explícito) en esta ruta. Si en el futuro se necesita un proxy, su selección y sus conexiones de salida requieren un contrato distinto que aplique la política en el punto de salida; no basta con validar localmente el destino.
5. Repetir decisión y conexión para cada redirección, variante de hostname y reintento. No seguir redirecciones automáticamente; resolver `Location` relativo, detectar bucles, rechazar HTTPS→HTTP y limitar saltos. Cada intento obtiene una decisión DNS nueva y queda sujeto a la misma política.

El invariante verificable es: **toda conexión abierta por el motor tiene un destino IP/puerto aprobado en esa misma operación, y Host/SNI/TLS corresponden al hostname solicitado**. No se deduce de una llamada previa de validación. Un firewall o NetworkPolicy en S04 añadirá defensa de red, pero no sustituye este invariante.

## Presupuesto y errores

- Un único plazo monotónico cubre DNS, conexión, TLS, redirecciones, reintentos, esperas y lectura. Cada timeout de fase se acota por el tiempo restante. Agotado el plazo, no se inicia otro intento.
- Un límite por respuesta acota bytes recibidos y otro el cuerpo descomprimido; se leen bloques y se cierra la conexión al superar cualquiera. `Content-Length` permite rechazo temprano, pero no sustituye el contador real. Las codificaciones admitidas deben decodificarse en streaming con límites; una codificación no soportada falla de forma cerrada.
- Rechazos de política (`UNSAFE_TARGET`, `UNSAFE_PORT`, `DNS_MIXED`, `PROXY_FORBIDDEN`, `TLS_INVALID`, `TOO_LARGE`, `TIME_BUDGET`) son resultados estables. IP, cabeceras sensibles y URL con query no se registran en logs ordinarios. Un rechazo de política no es reintentable; un fallo transitorio de red puede reintentarse si queda presupuesto.
- Los valores actuales de News Handler (2 MiB, 3 redirecciones, 2 reintentos; timeout configurado a 20 s en Kubernetes) y Evidence Search (4 MiB general, 15 MiB PDF, 5 redirecciones, 2 intentos, presupuesto de reintentos de 15 s) son la base para perfiles separados. El presupuesto **total** nuevo se configura explícitamente tras medir su impacto; no se infiere sumando timeouts existentes.

## Secuencia de implementación

1. **Hecho localmente:** motor común y perfiles desde configuración, `aiohttp` fijado en ambas imágenes y rutas de build con `api/common`.
2. **Hecho localmente:** News Handler usa el adaptador síncrono y Evidence Search el asíncrono. La extracción y sus resultados externos se conservan. El proveedor externo conserva su semántica; su conexión queda fuera del motor.
3. **Hecho localmente:** además de IP, DNS mixto, cambio de respuesta DNS, redirección y descompresión, hay pruebas controladas de TLS/SNI y de plazo total. La prueba TLS genera un certificado efímero válido para el hostname solicitado y comprueba SNI y verificación de nombre; el límite total cancela una respuesta lenta sin iniciar un reintento tardío.
4. **Kind validado:** smoke del endpoint de importación de News Handler con HTML público, extracción HTML/PDF directa desde el proceso de Evidence Search y revisión de una orden LIGHT en `DIRECT` con el motor nuevo. El operador confirma además que los E2E autenticados LIGHT/SMART y DIRECT terminaron correctamente. El ConfigMap y los Deployments quedaron sanos en `DIRECT`. El resultado E2E se registra como confirmación del operador, sin artefacto o ID de ejecución aportado en esta bitácora. No se modificaron parámetros por una muestra aislada. La validación de preproducción queda pendiente antes de la aceptación global del paquete.

## Ganancia, costes y límites

La mejora principal es cerrar la ventana entre validar DNS y conectar, manteniendo un único contrato para ambos servicios. Se suma control uniforme de proxy, puertos, redirecciones y presupuesto total, con diagnósticos comparables.

El coste es otra dependencia HTTP en Evidence Search y una migración de transporte en ambos servicios. Resolver por intento, no reutilizar conexiones entre saltos y verificar cada destino aumenta latencia y consultas DNS. El bloqueo de respuestas DNS mixtas, puertos no estándar y codificaciones no admitidas puede rechazar páginas antes accesibles; la regresión debe medir esos casos antes de ajustar política. La verificación TLS puede revelar sitios con certificados defectuosos que hoy solo funcionan por rutas alternativas. El motor no controla el tráfico del extractor de terceros ni elimina riesgos de analizadores HTML/PDF; esos límites se tratan por separado.
