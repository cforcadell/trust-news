# S03 — migración de propietarios legacy

`scripts/security/migrate_s03_owners.py` genera asociaciones de membresía para
claves legacy exactas presentes en órdenes o cuotas. Resuelve los `sub` de
usuarios humanos habilitados desde el realm indicado por `KEYCLOAK_ISSUER_URL`
y solo propone claves configuradas como `<prefijo>_<sub>`. Calcula el `org_id`
determinísticamente desde emisor y sujeto.

El motor es reutilizable en cualquier contexto Kubernetes accesible. Siempre
recibe `--context`; por defecto solo consulta. El modo de aplicación requiere
repetir el contexto y el SHA-256 del plan revisado. Antes de aplicar, vuelve a
leer Keycloak y MongoDB y aborta si el plan cambió. No imprime `sub`, IDs de
propietario ni claves legacy. La revisión muestra el nombre de usuario y los
recuentos por asociación.

El motor bloquea la aplicación si encuentra claves ambiguas, una clave ya
asociada a otra identidad/organización o una asociación inactiva. No reactiva
membresías suspendidas, no reasigna claves y no reescribe órdenes ni cuotas.
La actualización es idempotente: crea los índices requeridos y añade aliases
sin borrar los existentes. Una ejecución posterior debe volver a pasar por
inventario y revisión.

## Ejecución operativa

1. Mantener activo y verificado el maintenance lock durante la ventana de
   migración. Ejecutar desde un host autorizado con `kubectl` hacia el destino,
   el checkout de la versión autorizada del script y un entorno Python con
   `httpx` y `pymongo`.
2. Comparar el contexto elegido con el destino previsto y generar el plan:

   ```bash
   CONTEXT=$(kubectl config current-context)
   "$HOME/trust-news-ops-venv/bin/python" scripts/security/migrate_s03_owners.py \
     --context "$CONTEXT"
   ```

3. Revisar `owner username`, `aliases`, `legacy_prefixes`, `orders`, `quotas`,
   los recuentos de claves sin asignar y `plan_sha256`. Si hay conflictos, no
   aplicar: resolverlos mediante un procedimiento separado con propietario
   verificado. No se deben asociar claves por aproximación o solo por nombre.
4. Solo con el contexto y plan exactos revisados, volver a ejecutar con
   aplicación explícita:

   ```bash
   "$HOME/trust-news-ops-venv/bin/python" scripts/security/migrate_s03_owners.py \
     --context "$CONTEXT" \
     --apply \
     --confirm-context "$CONTEXT" \
     --confirm-plan '<SHA256 revisado>'
   ```

   Si el inventario cambió, el motor rechaza el hash y no escribe.
5. Confirmar `s03_owner_migration=APPLIED`, volver a contar las membresías
   activas sin mostrar identificadores y probar el listado autenticado desde la
   aplicación. Mantener el maintenance lock hasta terminar las verificaciones
   de aislamiento y el resto de la ventana.

El reconciliador no abre Cloudflare, no modifica Keycloak y no despliega
servicios. La publicación del script al host operativo sigue el flujo
autorizado de `sync-scripts`; ejecutar el script desde un árbol local sin
publicar ese SHA no demuestra que el host operativo use la misma versión.
