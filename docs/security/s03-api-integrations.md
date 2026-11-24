# S03 — integraciones API con cliente propio

**Estado:** implementación local sin despliegue ni aceptación E2E. `S03_INTEGRATIONS_ENABLED=false` en los overlays local y productivo. No habilitar acceso autónomo por la presencia de este código. [Diseño y contrato](../architecture/designs/oauth-api-integrations-design.md).

## Identidad y alcance

Cada alta crea `tnapi-<integration_id>` como cliente confidencial de Keycloak con cuenta de servicio, audiencias mínimas, asociación `issuer + azp + sub` a una organización, acciones aprobadas y cuota. Los tokens de `TrustNewsApi` se rechazan como integraciones; `reconcile_s03_keycloak.py` lo deshabilitará cuando el operador ejecute la conciliación en el entorno elegido. No se adoptan clientes, credenciales, cuotas ni órdenes de `TrustNewsApi` en las altas nuevas.

En la TUI, el ID de integración sugerido es el primer `integration-NNN`
disponible en el inventario de asociaciones, cuotas y clientes gestionados.
Ese ID lo asigna la aplicación y no es el UUID interno del cliente Keycloak.
Enter acepta la sugerencia; si se introduce un número positivo, por ejemplo
`3`, se normaliza a `integration-003`.
En el alta, la TUI muestra las acciones del catálogo: introduce una acción por
prompt para elegir varias, pulsa Enter vacío tras la primera para terminar, o
escribe `all` para seleccionar todas las acciones del catálogo actual. La
selección `all` se expande a las acciones concretas del catálogo al crear la
integración; no autoriza automáticamente acciones añadidas después.
El `org_id` no se genera en esta operación: debe ser el UUID de una
organización activa ya registrada. Si el registro de organización aún no existe,
el motor permite inicializarlo desde una membresía S03 activa existente.

La TUI también permite **crear una organización API** con un UUID generado por
la aplicación y límites iniciales de generación y validación, y listar las
organizaciones registradas con límites, consumo, reservas e integraciones. La
creación inicializa `s03_organizations` con consumo y reservas en cero; no crea
un usuario humano ni una identidad Keycloak. Una organización API activa puede
existir antes de su primera integración. En las altas, las cuotas propuestas
por defecto son `9999` para generación y `9999` para validación. La expiración
predeterminada de la integración es dos años desde la fecha de alta; el operador
puede cambiar estos valores antes de revisar el plan. Estos valores no se
aplican al cambiar límites de integraciones existentes.

`TrustNewsWeb` conserva el login OpenID Connect, scopes, refresh/logout, membresías y cuotas humanos. Los scripts de la GUI no forman parte del alta API. Las rutas de integraciones aceptadas se definen una sola vez en `api/common/security/integration-routes.json`; una ruta ausente queda denegada. Gateway y cada destinatario comprueban el token; Admin resuelve la asociación activa y la cuota. Una integración no puede usar roles humanos de administración.

La cuota autónoma vive en `s03_organizations`. Cada reserva, consumo o liberación modifica en **un único documento** el contador de organización y el de integración. `Idempotency-Key` es obligatorio en las rutas con coste y admite 8–96 letras, dígitos, `_` o `-`; el mismo identificador con otro cuerpo recibe 409. El libro de operaciones tiene un máximo de 10 000 entradas por organización y falla cerrado al alcanzarlo. `BLOCKCHAIN` está deshabilitado para peticiones de integración; su cuota de validación requiere aceptación propia antes de habilitarse.

## Alta y mantenimiento

El script `scripts/security/provision_s03_integration.py` consulta el contexto Kubernetes indicado, Keycloak y MongoDB mediante port-forward local. El modo inicial es de **solo lectura**; `--apply` exige `--confirm-context` y el `plan_sha256` de una vista previa nueva. Para organizaciones ya registradas, el estado y los límites deben coincidir con los aprobados. Para una organización heredada que aún no tiene documento en `s03_organizations`, se exige una membresía S03 activa y se inicializa el documento durante la primera alta. El alta de integración no modifica límites existentes; solo `--operation limits` puede hacerlo con un plan revisado.

Ejemplo de vista previa, sustituyendo los marcadores por valores aprobados:

```bash
cd ~/trust-news
"$HOME/trust-news-ops-venv/bin/python" -m scripts.security.provision_s03_integration \
  --context '<contexto>' --integration-id '<slug-nuevo>' \
  --org-id '<uuid-organizacion>' --expires-at '<fecha-ISO8601-con-zona>' \
  --action orders:create --action orders:read --action orders:list \
  --news-generation-limit 10 --blockchain-validation-limit 0 \
  --org-news-generation-limit 20 --org-blockchain-validation-limit 0
```

El resultado indica `READY`, `RESUME` o `BLOCKED_*`, las acciones, los límites y el hash, sin mostrar secretos. `RESUME` solo acepta un cliente creado por este motor, con marca y datos parciales coherentes. Tras revisar el plan, repetir los mismos argumentos y añadir:

```text
--apply --confirm-context '<contexto>' --confirm-plan '<SHA256 revisado>'
```

La credencial queda en `secrets/clients/api-<integration_id>.json` con directorios `0700` y archivo `0600`, fuera de Git y de la sincronización CI. Entregarla al consumidor por canal privado. No imprimirla ni copiarla a ConfigMaps. El cliente permanece deshabilitado hasta registrar y verificar la asociación y la cuota; un fallo parcial obliga a revisar el estado antes de reanudar.

Para `rotate`, `suspend`, `reactivate`, `retire` o `limits`, usar el mismo script con `--context`, `--integration-id` y `--operation`, primero sin `--apply`. `limits` exige los cuatro límites nuevos; los demás no aceptan campos de creación. Suspensión y baja bloquean nuevas peticiones antes de deshabilitar Keycloak y se rechazan mientras haya reservas pendientes. Rotación escribe un secreto nuevo en el archivo privado; distribuirlo al consumidor antes de considerar completado el cambio. La baja conserva atribución y consumo históricos.

## Puerta de aceptación pendiente

Antes de cambiar `S03_INTEGRATIONS_ENABLED` a `true`, probar en kind y después en Hetzner/K3s con SHA/configuración efectivos:

- dos integraciones de una organización y otra de una segunda; aislamiento de órdenes, acciones y límites propios y de organización;
- token `TrustNewsApi`, `azp`/audiencia incorrectos, asociación ausente/suspendida, cuota agotada y ruta administrativa denegados;
- concurrencia de reservas, reintentos con el mismo `Idempotency-Key`, fallo después de reservar, rotación, suspensión, baja y expiración;
- login, refresh, logout, rutas y cuotas GUI con `TrustNewsWeb` sin regresión;
- reconciliación de reservas pendientes y eventos Kafka sin doble cobro, además de rollback y observabilidad sin secretos.

La aceptación de MongoDB/Kafka, los límites de gasto y el corte de `TrustNewsApi` **no se han ejecutado** por esta implementación local. Mantener NO-GO para clientes hasta completar las puertas de v0.0.13d y la decisión explícita de release.
