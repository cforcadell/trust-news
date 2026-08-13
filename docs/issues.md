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
