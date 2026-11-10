# S03 en los perfiles Skaffold

Los perfiles `infra-basic`/`infra` y `apis-frontend` de kind, y `infra-prod`/`apis-frontend-prod` de Hetzner/K3s, aplican la misma configuración de ejecución S03: sidecar TLS en 9443, CA interna, identidad de cliente, URLs HTTPS internas, política por servicio y transporte HTTPS de Traefik al Gateway. Los perfiles `-prod` nombran la preproducción actual.

El inventario [s03-local-services.json](s03-local-services.json) conserva nombres de Service, Deployment, puerto HTTP e identidad. `python3 scripts/security/render_s03_runtime.py` genera desde él los parches no sensibles de `k8s/s03/runtime/patches`; `--check` detecta desajustes. Los overlays locales y productivos consumen esos mismos parches. `k8s/s03/runtime/overlays/{local,prod}` solo cambia el issuer público. El sidecar usa el módulo existente `common.security.tls_proxy` de la imagen Gateway; por eso los perfiles de infraestructura también construyen esa imagen.

## Contrato de Secrets

| Secret | Namespace | Claves | Preparación kind | Preparación Hetzner |
| --- | --- | --- | --- | --- |
| `s03-client-<client>` | `apis` | `S03_CLIENT_ID`, `S03_CLIENT_SECRET` | `s03-client.env` ignorado en el overlay local de cada API; un Secret compartido para los tres validadores | Un Secret por client desde el `.env` privado externo |
| `s03-internal-ca` | `infra`, `apis` | `ca.crt` | `secretGenerator` desde la PKI local externa | Secret manual desde la CA privada |
| `s03-tls-<service>` | Namespace del Service | `tls.crt`, `tls.key` | `secretGenerator` desde la PKI local externa | Secret TLS manual por Service |

Las rutas montadas son `/etc/s03-ca/ca.crt` y `/etc/s03-tls/tls.crt`/`tls.key` en ambos entornos. Las claves privadas y los `.env` no se versionan. `keycloak-tls-secret`, usado por otra configuración de Keycloak, no sustituye a `s03-tls-keycloak`.

## Primer despliegue y redespliegues en kind

Desde la raíz del repositorio, con contexto `kind-*`:

```bash
python3 scripts/security/s03_local_pki.py --output-dir /tmp/s03-kind-pki
./skaffold run -p infra-basic
kubectl rollout status deployment/keycloak -n infra
python3 scripts/security/reconcile_s03_keycloak.py --kind-local --local-overlays
./skaffold run -p apis-frontend
python3 scripts/security/render_s03_runtime.py --check
```

El generador de PKI reutiliza certificados existentes, crea los que faltan fuera del repositorio y prepara enlaces `pki` ignorados para los dos overlays locales de TLS. Skaffold genera los Secrets TLS. El reconciliador de clientes necesita Keycloak ya disponible y escribe los `s03-client.env` locales con permisos `0600`. Si esos archivos ya existen y las identidades no han cambiado, un redespliegue ordinario solo necesita el perfil Skaffold correspondiente. `infra` despliega la misma configuración S03 que `infra-basic`.

## Provisión manual en Hetzner/K3s

Comprobar primero el contexto K3s y preparar los certificados y los `.env` en un directorio privado externo. Cada certificado de servicio debe verificar la CA interna, incluir `<service>.<namespace>.svc.cluster.local` en SAN, tener uso `serverAuth` y vigencia suficiente. Para los nombres y puertos, usar el inventario S03. Ejemplo parametrizado sin imprimir los valores:

```bash
set -o pipefail
PRIVATE_S03_DIR=/ruta/privada/s03
kubectl config current-context
for namespace in infra apis; do
  kubectl -n "$namespace" create secret generic s03-internal-ca \
    --from-file=ca.crt="$PRIVATE_S03_DIR/ca.crt" \
    --dry-run=client -o yaml | kubectl apply -f -
done
while IFS=$'\t' read -r namespace service; do
  kubectl -n "$namespace" create secret tls "s03-tls-$service" \
    --cert="$PRIVATE_S03_DIR/$namespace-$service.crt" \
    --key="$PRIVATE_S03_DIR/$namespace-$service.key" \
    --dry-run=client -o yaml | kubectl apply -f -
done < <(python3 - <<'PY'
import json
for row in json.load(open('docs/security/s03-local-services.json', encoding='utf-8')):
    print(f"{row['namespace']}\t{row['service']}")
PY
)
```

Comprobar antes de `infra-prod` con `S03_PREFLIGHT_PHASE=infra bash scripts/security/check_s03_configured_secrets.sh`. Después desplegar `infra-prod` para iniciar Keycloak por HTTPS interno. Reconciliar los clients del realm con el procedimiento de [skaffold-server.md](../deploy/skaffold-server.md#33-identidad-tls-y-credenciales-s03), crear manualmente sus Secrets `s03-client-*` desde los `.env` privados y ejecutar `S03_PREFLIGHT_PHASE=apis bash scripts/security/check_s03_configured_secrets.sh`. El preflight valida clientes, CA, vigencia, SAN, clave y cadena TLS sin mostrar valores. Entonces desplegar `apis-frontend-prod`. La CI ejecuta automáticamente la fase apropiada antes de mutar recursos. Los overlays de Hetzner consumen los Secrets existentes; no generan credenciales ni certificados locales. La activación real y la aceptación de Hetzner siguen pendientes.

## Comprobaciones y rotación

Antes de desplegar, comprobar `render_s03_runtime.py --check`, la presencia y claves de todos los Secrets y que el issuer público corresponda al entorno. Después comprobar que Keycloak y las APIs están Ready, que JWKS responde por HTTPS con CA y hostname verificados, que Traefik alcanza Gateway por HTTPS y que las rutas autenticadas y denegadas conservan sus códigos esperados. Registrar por separado kind y Hetzner.

Los nombres de Secret son estables. El proxy TLS lee certificado y clave al arrancar: después de rotar CA o certificados hay que coordinar el reinicio de Keycloak, APIs y Traefik según el material cambiado. Rotar con solape de confianza y comprobar SAN, vigencia y cadena antes del corte.
