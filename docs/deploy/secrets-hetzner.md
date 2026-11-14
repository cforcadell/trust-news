# Secrets y certificados para Hetzner/K3s

Esta guía compara el `create-secrets.sh` usado en el servidor con los contratos de Secrets de los overlays kind y los perfiles `infra-prod` y `apis-frontend-prod`. Los Secrets se preparan antes de reconciliar cada perfil. El script usa `kubectl apply`; no elimina el Secret activo antes de actualizarlo.

Los valores, claves privadas y ficheros `.env` deben permanecer fuera del repositorio. No reutilizar la CA ni los certificados de kind. La CA interna S03/Kafka es distinta del certificado público Cloudflare Origin CA.

## Qué cubría el script anterior y qué faltaba

| Namespace | Ya estaba en el script del servidor | Falta añadir para los perfiles actuales |
| --- | --- | --- |
| `infra` | `mongodb-secret`, `keycloak-admin-secret`, `keycloak-db-secret`, `mongo-express-secret` | `s03-internal-ca`, `s03-tls-keycloak`, `s07a-kafka-broker` |
| `apis` | `validator-secret-{1,2,3}`, `api-keys`, `news-chain-secrets`, `news-handler-secrets`, `gate-config`, `mongodb-secret`, `search-secret`, `mongodb-app-secret`, `source-router-enc` | `s03-internal-ca`, nueve `s03-tls-*`, siete `s03-client-*`, `s07a-kafka-ca` |
| `blockchain` | `ethereum-secrets` | Ninguno para el Secret de credenciales. `ethereum-keystores` se aplica como manifiesto del overlay blockchain, no lo crea este script. Solo desplegar blockchain cuando esté autorizado y sus credenciales correspondan al entorno. |
| `kube-system` | `trustnews-origin-tls` | Ninguno; el certificado y la clave Cloudflare Origin son independientes de S03/Kafka. |
| `frontend` | Nada en el script pegado | `gitlab-pull-secret` se gestiona por separado, si el namespace frontend necesita descargar imágenes privadas. Ver §3.4 de [skaffold-server.md](skaffold-server.md#34-pull-secret). |

Los nueve Secrets TLS de `apis` corresponden a los servicios del inventario: `gateway`, `admin-service`, `news-handler`, `generate-asertions`, `source-router`, `evidence-search` y `validate-service-{1,2,3}`. Los siete Secrets S03 de cliente son `s03-client-assermetry-{gateway,admin,news-handler,generate,source-router,evidence-search,validator}`. Un único Secret `validator` sirve a los tres workers.

Kind también genera `infra/keycloak-tls-secret` con su certificado local. Hetzner no debe copiarlo: el TLS interno de Keycloak usa `infra/s03-tls-keycloak`; el TLS público de Traefik usa por separado `kube-system/trustnews-origin-tls`.

`gate-config`, `news-handler-secrets` y `mongodb-secret` de `apis` se mantienen en el script por compatibilidad con los ficheros operativos existentes. La comprobación de Secrets de aplicación del preflight actual requiere `source-router-enc`, `api-keys`, `search-secret`, `mongodb-app-secret` y `validator-secret-{1,2,3}`; no elimines los demás sin revisar primero los manifiestos y el uso de ese entorno.

## 1. Preparar una PKI interna nueva

Hazlo una sola vez para el entorno. Si ya existe una CA S03/Kafka usada por servicios, **reutilízala**: no ejecutes la creación de CA ni sustituyas solo algunos certificados. Una rotación debe planificarse como cambio coordinado y conservar material para rollback.

El ejemplo genera la CA y certificados de servicio fuera del checkout. Cada certificado lleva SAN de servicio Kubernetes, EKU `serverAuth` y validez de 90 días. Kafka comparte esta CA, como en kind, e incluye también el DNS del pod KRaft.

Desde la raíz del checkout, con `openssl` y `python3` instalados:

```bash
set -euo pipefail
umask 077
export S03_PKI_DIR="$HOME/trust-news-secrets/s03-pki"
install -d -m 700 "$S03_PKI_DIR"

# Esta parte solo es para una PKI nueva. Falla si ya existe cualquiera de los dos ficheros.
test ! -e "$S03_PKI_DIR/ca.crt" && test ! -e "$S03_PKI_DIR/ca.key"
openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 1825 \
  -subj '/CN=TrustNews Hetzner Internal CA' \
  -keyout "$S03_PKI_DIR/ca.key" -out "$S03_PKI_DIR/ca.crt"
chmod 600 "$S03_PKI_DIR/ca.key"

issue_server_cert() {
  local namespace="$1" service="$2" extra_dns="${3:-}"
  local stem="$S03_PKI_DIR/$namespace-$service"
  local dns="$service.$namespace.svc.cluster.local"
  local sans="DNS:$dns,DNS:$service.$namespace.svc"
  local csr="$stem.csr" ext="$stem.ext"

  test ! -e "$stem.crt" && test ! -e "$stem.key"
  [[ -z "$extra_dns" ]] || sans="$sans,DNS:$extra_dns"
  openssl req -new -newkey rsa:2048 -nodes -sha256 \
    -subj "/CN=$dns" -keyout "$stem.key" -out "$csr"
  chmod 600 "$stem.key"
  cat > "$ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$sans
EOF
  openssl x509 -req -sha256 -days 90 \
    -in "$csr" -CA "$S03_PKI_DIR/ca.crt" -CAkey "$S03_PKI_DIR/ca.key" \
    -CAcreateserial -out "$stem.crt" -extfile "$ext"
  rm -f "$csr" "$ext"
}

issue_server_cert infra keycloak
while IFS=$'\t' read -r namespace service; do
  [[ "$namespace" == apis ]] && issue_server_cert "$namespace" "$service"
done < <(python3 - docs/security/s03-local-services.json <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as source:
    for row in json.load(source):
        print(f"{row['namespace']}\t{row['service']}")
PY
)
issue_server_cert infra kafka kafka-0.kafka.infra.svc.cluster.local

# PKCS12 del broker y contraseña privada que consumirá create-secrets.sh.
test ! -e "$S03_PKI_DIR/broker.p12" && test ! -e "$S03_PKI_DIR/kafka-tls.env"
S07A_STORE_PASSWORD="$(openssl rand -hex 32)"
export S07A_STORE_PASSWORD
openssl pkcs12 -export -name kafka \
  -in "$S03_PKI_DIR/infra-kafka.crt" \
  -inkey "$S03_PKI_DIR/infra-kafka.key" \
  -certfile "$S03_PKI_DIR/ca.crt" \
  -out "$S03_PKI_DIR/broker.p12" \
  -passout env:S07A_STORE_PASSWORD
printf 'KEYSTORE_PASSWORD=%s\n' "$S07A_STORE_PASSWORD" > "$S03_PKI_DIR/kafka-tls.env"
chmod 600 "$S03_PKI_DIR/broker.p12" "$S03_PKI_DIR/kafka-tls.env"
unset S07A_STORE_PASSWORD
```

El comando termina si detecta CA, certificado o PKCS12 existentes; no los pisa. Si solo hay parte de los ficheros, investigar y recuperar la copia protegida antes de continuar. No copiar `ca.key` al clúster: solo se sube `ca.crt`.

La identidad `kafka` debe verificar ambos nombres del listener:

```text
kafka.infra.svc.cluster.local
kafka-0.kafka.infra.svc.cluster.local
```

Las credenciales de clientes S03 no se generan en este paso. Se reconcilian con Keycloak después de que `infra-prod` esté disponible; véase §4.

## 2. Crear/actualizar Secrets de `infra`

El directorio privado por defecto para los ficheros del script es `$HOME/trust-news/secrets`. Debe contener los mismos `.env` ya usados por el script del servidor. Para aplicar el bloque de infraestructura:

```bash
bash scripts/create-secrets.sh --phase infra
bash scripts/check_configured_secrets.sh --phase infra
```

Este bloque actualiza `infra/mongodb-secret`, `infra/keycloak-admin-secret`, `infra/keycloak-db-secret` y `infra/mongo-express-secret`, y crea/actualiza:

- `infra/s03-internal-ca` con `ca.crt`;
- `infra/s03-tls-keycloak` con `tls.crt` y `tls.key`;
- `infra/s07a-kafka-broker` con `broker.p12`, `ca.crt`, `KEYSTORE_PASSWORD` y `kafdrop.properties`.

La contraseña de MongoDB debe seguir coincidiendo con las cuentas ya inicializadas en el PVC. Actualizar el Secret no cambia por sí solo las credenciales persistidas de MongoDB.

## 3. Crear/actualizar Secrets de `apis`

Después de desplegar `infra-prod`, esperar a Keycloak y reconciliar los clients S03 siguiendo §3.3 de [skaffold-server.md](skaffold-server.md#33-identidad-tls-y-credenciales-s03). El directorio debe contener un `.env` por client con `S03_CLIENT_ID` y `S03_CLIENT_SECRET`, con nombre `<client-id>.env`.

Una vez existan esos ficheros:

```bash
bash scripts/create-secrets.sh --phase apis
bash scripts/check_configured_secrets.sh --phase apis
```

Este bloque conserva y actualiza los Secrets de aplicación del script anterior, y añade:

- `apis/s03-internal-ca` con la misma CA que `infra`;
- `apis/s03-tls-*` para los nueve servicios del inventario;
- `apis/s03-client-*` para los siete clients de servicio;
- `apis/s07a-kafka-ca` con la misma `ca.crt` usada por el broker.

El preflight de `apis` comprueba la igualdad de las CA de S03 y de las copias Kafka, además de la vigencia, SAN, cadena y pareja clave/certificado donde aplica. No continuar si falla.

## 4. Secuencia de despliegue

1. Confirmar contexto K3s, backup recuperable, namespaces y checkout/SHA previsto. No usar el contexto kind.
2. Preparar o reutilizar la PKI interna, y provisionar los Secrets de `infra` con `--phase infra`.
3. Ejecutar `scripts/check_configured_secrets.sh --phase infra`; si pasa, desplegar `infra-prod` desde el SHA autorizado.
4. Esperar a Keycloak; reconciliar clients S03 contra el realm de ese entorno y revisar que sus `.env` quedaron fuera del repositorio con permisos privados.
5. Ejecutar `scripts/create-secrets.sh --phase apis` y luego `scripts/check_configured_secrets.sh --phase apis`.
6. Solo si el preflight pasa, desplegar `apis-frontend-prod` desde el mismo SHA. Mantener `BLOCKCHAIN_ENABLED=OFF` para el perfil LIGHT/SMART previsto.
7. Comprobar rollouts y configuración efectiva en K3s. El resultado local kind no constituye aceptación de Hetzner.

Para completar el TLS público, si se requiere actualizarlo, usar `--phase edge` después de comprobar por separado el certificado Cloudflare Origin. El flujo de imagen privada (`gitlab-pull-secret`) se mantiene separado, según [skaffold-server.md §3.4](skaffold-server.md#34-pull-secret). Blockchain se puede aprovisionar con `--phase blockchain` únicamente cuando esa fase esté planificada.

## 5. Rutas privadas y variables

El script usa estos valores por defecto y permite sobrescribirlos por entorno:

| Variable | Valor por defecto |
| --- | --- |
| `SECRETS_DIR` | `$HOME/trust-news/secrets` |
| `S03_PKI_DIR` | `$HOME/trust-news-secrets/s03-pki` |
| `S03_CLIENTS_DIR` | `$HOME/trust-news-secrets/s03-clients` |
| `ORIGIN_TLS_CERT` | `$HOME/trustnews-origin-ca/assermetry-origin.pem` |
| `ORIGIN_TLS_KEY` | `$HOME/trustnews-origin-ca/assermetry-origin.key` |

Para ejecutar desde otra sesión o checkout, exportar la ruta correspondiente antes de llamar al script. No activar `set -x` en sesiones con variables, contraseñas o rutas sensibles.
