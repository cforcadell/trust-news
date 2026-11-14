# S07a — transporte Kafka cifrado

S07a usa TLS para el listener de clientes (9092), el listener KRaft (9093), los clientes Python y Kafdrop. Los clientes verifican la CA y el nombre `kafka.infra.svc.cluster.local`. S07b queda diferido: no hay identidad de cliente, ACL por topic/acción ni garantía de idempotencia de eventos. El broker sigue permitiendo crear topics automáticamente hasta S07b.

## Contrato único de despliegue

| Recurso | Namespace | Claves |
| --- | --- | --- |
| `s07a-kafka-broker` | `infra` | `broker.p12`, `ca.crt`, `KEYSTORE_PASSWORD`, `kafdrop.properties` |
| `s07a-kafka-ca` | `apis` | `ca.crt` |

Todos los clientes usan `KAFKA_SECURITY_PROTOCOL=SSL`, `KAFKA_CA_FILE=/etc/kafka-tls/ca.crt` y el bootstrap DNS completo. Los dos perfiles de Skaffold renderizan los mismos Deployments y StatefulSet. Solo cambia la provisión de los Secrets.

### kind

Con el directorio PKI S03 existente fuera del repositorio:

```bash
python3 scripts/security/s03_local_pki.py --output-dir /tmp/s03-kind-pki
python3 scripts/security/s07a_local_kafka_tls.py --pki-dir /tmp/s03-kind-pki
skaffold run -p infra-basic
kubectl rollout status deployment/keycloak -n infra
skaffold run -p apis-frontend
```

El script reutiliza la CA local S03 y crea un certificado Kafka con SAN para el Service y el pod KRaft. El PKCS12 permanece fuera del repositorio; el overlay contiene un enlace al PKCS12, la CA pública y el `.env` local, todos ignorados por Git. Kustomize genera ambos Secrets. `infra` incluye Kafdrop y `infra-basic` no. Si cambia la CA o el certificado, eliminar de forma controlada el par externo `infra-kafka.p12`/`kafka-tls.env` y el enlace, regenerar y reiniciar clientes tras reconciliar los Secrets. No rotar solo uno de los dos archivos.

Los perfiles Skaffold incluyen ahora la configuración de ejecución S03 completa, también al recrear los Deployments. El primer despliegue requiere reconciliar clients de Keycloak y generar los `s03-client.env` locales antes de `apis-frontend`; seguir [S03 con Skaffold](s03-skaffold.md). No se necesitan fases imperativas después de cada despliegue.

### Hetzner/K3s

El operador emite el certificado Kafka desde su CA privada. Debe incluir SAN `kafka.infra.svc.cluster.local` y `kafka-0.kafka.infra.svc.cluster.local`, uso `serverAuth` y vigencia comprobada. Con un PKCS12 `broker.p12`, la CA `ca.crt` y un archivo privado `kafka-tls.env` con `KEYSTORE_PASSWORD=<contraseña del PKCS12>`, provisiona manualmente en el contexto K3s:

```bash
kubectl -n infra create secret generic s07a-kafka-broker \
  --from-file=broker.p12 --from-file=ca.crt \
  --from-file=kafdrop.properties=k8s/infra/kafka/kafdrop.properties \
  --from-env-file=kafka-tls.env --dry-run=client -o yaml | kubectl apply -f -
kubectl -n apis create secret generic s07a-kafka-ca \
  --from-file=ca.crt --dry-run=client -o yaml | kubectl apply -f -
skaffold run -p infra-prod
skaffold run -p apis-frontend-prod
```

Ejecutar los comandos solo después de comprobar el contexto K3s y los SAN. El código y las rutas montadas son idénticos a kind. El paso de `PLAINTEXT` a TLS requiere un corte coordinado del broker y los clientes; conservar una copia protegida de los Secrets y el manifiesto anterior para rollback operativo.

Antes de desplegar `infra-prod`, ejecutar desde el checkout del SHA candidato `bash scripts/check_configured_secrets.sh --phase infra`; esta fase valida el Secret del broker, su CA y el certificado PKCS12. Después de reconciliar S03 y antes de `apis-frontend-prod`, ejecutar `bash scripts/check_configured_secrets.sh --phase apis`; esta fase comprueba además `apis/s07a-kafka-ca` y que su CA coincide con la del broker. Ambas fases validan vigencia de la CA y del certificado, password, SAN, `serverAuth` y cadena del certificado. GitLab repite la fase correspondiente en preflight y justo antes del despliegue.

## Aceptación por entorno

En cada entorno, comprobar que Kafka y los clientes están Ready, que un productor/consumidor TLS produce y lee el mismo mensaje con CA y hostname verificados, que una conexión `PLAINTEXT` al puerto 9092 falla, que Kafdrop accede al broker y que el E2E autenticado LIGHT/SMART funciona sin errores Kafka. Registrar identificadores de orden y efecto en cuota, sin incluir secretos. El éxito en kind no acredita Hetzner.

E2E de transporte reproducible desde cualquier pod Python con `kafka-python`, `KAFKA_CA_FILE` y acceso al broker:

```bash
kubectl -n apis exec -i deployment/news-handler -c news-handler -- python - < tests/e2e/kafka_tls_transport.py
```

El motor crea un topic de nombre único, comprueba producción/consumo TLS y rechazo de `PLAINTEXT`, y elimina el topic en `finally`. Usar el contexto Kubernetes previsto para cada entorno.

### Evidencia kind del 09-11-2026

- `s07a-kafka-broker` y `s07a-kafka-ca` generados por Kustomize desde overlays locales; Kafka y todos los Deployments cliente quedaron Ready en la revisión TLS. Kafdrop mostró `fake_news_responses`.
- E2E Kafka desde el contenedor News Handler: producir y consumir el mismo mensaje con CA y hostname verificados, PASS. El cliente `PLAINTEXT` fue rechazado, PASS. El topic temporal `s07a_tls_e2e_edf09009de4b` se eliminó.
- El listener KRaft 9093 respondió TLSv1.3 `TLS_AES_256_GCM_SHA384`; verificación de CA y hostname del pod, OK.
- Suite focalizada: 55 pruebas correctas; renders locales y prod de clientes y broker correctos. El flujo funcional autenticado LIGHT/SMART quedaba pendiente tras esta ejecución. Hetzner/K3s no se desplegó ni se aceptó; el kubeconfig local solo contiene `kind-trust-news`.

### Confirmación posterior

- 11-11-2026: el usuario confirma que los E2E funcionales autenticados LIGHT/SMART de S07a se superaron en kind. Hetzner/K3s continúa pendiente; esta confirmación local no constituye aceptación de preproducción.
