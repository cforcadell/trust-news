# Configuración LLM runtime

La configuración de modelos LLM se administra desde la GUI únicamente para usuarios con el rol realm `trust-admin`. Los componentes configurables son `generate-asertions`, `source-router` y cada instancia registrada de `validate-asertions`.

## Seguridad y frontera

Las APIs de configuración LLM administrativa requieren autenticación mediante certificado cliente. La protección es permanente y se compone de las tres capas siguientes:

```text
cliente con certificado mTLS
  -> Cloudflare (política administrativa permanente)
  -> /backend/admin/llm/* en Gateway
  -> JWT Keycloak válido (issuer, audience y cliente permitido)
  -> realm role trust-admin
  -> Admin API interna
```

El navegador solo llama a Gateway. `Admin`, `generate-asertions`, `source-router` y los workers son servicios `ClusterIP`; sus rutas internas `/admin/config` no se publican mediante Ingress. El Gateway descarta las cabeceras de identidad suministradas por el navegador y crea la identidad de auditoría a partir del JWT validado.

## Origen y precedencia de configuración

| Almacenamiento | Contenido | Uso |
| --- | --- | --- |
| ConfigMap / environment | provider, model y temperatura por defecto | valor de arranque |
| Kubernetes Secret / environment | API keys, private keys y demás credenciales | única fuente de secretos |
| MongoDB `config` | `desired`, `actual`, versión, estado y auditoría no sensibles | override runtime persistente |
| Memoria del proceso | configuración efectiva | aplicación inmediata sin reinicio |

Al iniciar, cada servicio toma sus valores por defecto del environment y pide el override `llm:*` al Admin. Si Admin o Mongo no están disponibles, registra un warning y continúa con los valores por defecto. No se modifican ConfigMaps, Secrets ni se usa la API de Kubernetes.

Los PUT runtime solo admiten `provider`, `model` y `temperature` (la versión es asignada por Admin). Los schemas rechazan campos adicionales: no se aceptan ni se muestran `api_key`, `private_key`, tokens, passwords, ni secretos aunque estén enmascarados. Las respuestas solo exponen el booleano `credentials_configured` cuando resulta útil.

## Operación

La ruta externa es `/backend/admin/llm/*` y las rutas internas de Admin son:

```text
GET/PUT /llm/components/generate-asertions
GET/PUT /llm/components/source-router
GET     /llm/validators?type=&strategy=
GET/PUT /llm/validators/{validator_id}
```

Admin persiste primero `desired` como `PENDING`, llama al `GET/PUT /admin/config` del servicio y compara el resultado efectivo. Si coincide pasa a `APPLIED`; si falla conserva el último `actual` y marca `ERROR`. Cada cambio deja componente o validator, provider/model anterior y nuevo, versión, usuario, fecha y resultado en `config.last_audit`.

Los validators se descubren dinámicamente desde el cache existente de `news-handler`, respaldado por blockchain/IPFS. Su identificador estable es `ACCOUNT_ADDRESS` y su configuración registrada aporta el `service_url` usado solo por Admin dentro del cluster. La GUI nunca envía una URL interna. Antes de leer o modificar un worker, Admin vuelve a descubrirlo y exige que esté activo y accesible. El tipo se deriva del enum `ValidatorType` y se devuelve como `{id, name}`; para RAG se devuelve también la estrategia de evidencia.

Cambiar un validator reutiliza su `PUT /admin/config`: reconstruye el cliente AI y conserva sus actualizaciones de configuración IPFS, blockchain y eventos existentes. El cambio no altera el tipo de validator ni la estrategia de evidencia.

## Trazabilidad

Los documentos de aserciones incluyen provider, model y versión. El router guarda modelo y versión de clasificación en perfiles y rutas nuevas. Las respuestas de validación compatibles incorporan provider, model y versión LLM; la identidad del validator ya forma parte de su contrato.

## Matriz de verificación manual de mTLS

La regla de Cloudflare debe probarse desde un cliente externo, nunca desde el port-forward local:

| Certificado cliente | JWT / rol | Resultado esperado |
| --- | --- | --- |
| Ausente | JWT `trust-admin` válido | Cloudflare rechaza antes de Gateway |
| Válido | Ausente o inválido | Gateway responde 401 |
| Válido | JWT válido sin `trust-admin` | Gateway responde 403 |
| Válido | JWT válido con `trust-admin` | Gateway permite la operación |

La política exacta y el procedimiento de revisión de Cloudflare están en [`skaffold-server.md`](../deploy/skaffold-server.md#12-cloudflare).
