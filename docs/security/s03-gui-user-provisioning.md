# S03 — alta de usuarios GUI

`scripts/security/provision_s03_gui_user.py` da de alta una identidad humana en
el realm configurado en `apis/gateway-config`. **Todos los usuarios GUI usan
`TrustNewsWeb`**: el script comprueba ese cliente y sus audiencias, pero no crea
ni modifica clientes Keycloak. No concede roles administrativos.

El motor crea el usuario deshabilitado, le asigna una contraseña temporal con
`UPDATE_PASSWORD`, crea su membresía S03 con la clave `user_<sub>` y solo
entonces habilita el usuario. En el dry-run se deben indicar límites explícitos
para `news_generation` y `blockchain_validation`; ambos forman parte del hash
revisado. Crea una cuota activa con consumo inicial cero y no cambia cuotas
existentes. El `org_id` usa la misma fórmula determinista que
el migrador de propietarios (`UUIDv5` del emisor y sujeto). Antes de escribir,
rechaza nombres existentes ajenos al motor, membresías inactivas o conflictivas
y configuración S03/Web incompleta. Si se interrumpe con una membresía S03
válida, el usuario deshabilitado puede reanudarse y recibirá una nueva
contraseña temporal. Si el proceso se corta antes de crear la membresía, solo
se puede reanudar con `--resume-unmarked-disabled`, tras confirmar que ese
usuario fue creado por el intento fallido. El plan exige además que siga
deshabilitado y requiera `UPDATE_PASSWORD`. Una cuenta habilitada no se vuelve a
provisionar ni se le cambia la contraseña. Si tiene una membresía activa válida
pero carece de cuota, se permite únicamente el modo `ADD_QUOTA_ONLY` descrito
más abajo. El motor no depende de atributos personalizados del perfil Keycloak.

La contraseña y la clave de cuotas se guardan en
`secrets/clients/gui-<username>.json`, directorio privado `0700` y archivo
`0600`, excluidos de Git y de la sincronización CI. No se imprimen la
contraseña, el `sub`, el `org_id` ni la clave `user_<sub>` en los logs.

## Publicación en Hetzner

Tras revisar y publicar un SHA autorizado, usar en GitLab un pipeline web con
`PIPELINE_ACTION=sync-scripts` y `PROFILE=scripts-hetzner`. Ejecutar el job
manual `sync_operations_scripts` y comprobar que instaló desde ese SHA el
script, `migrate_s03_owners.py`, `reconcile_s03_keycloak.py` y
`s03-keycloak-clients.json`. El job copia solo ficheros versionados; no crea
cuentas ni transporta credenciales. No iniciar un despliegue de APIs para esta
alta: el runtime S03 existente ya acepta usuarios de `TrustNewsWeb`.

## Ejecución

Mantener el maintenance lock activo durante el alta. Desactivarlo solo durante
la ventana autorizada de pruebas de navegador que lo necesiten y restaurar
después el estado operativo acordado. Desde el host operativo, con `kubectl`
hacia el destino y el entorno Python que tenga `httpx` y `pymongo`:

```bash
cd ~/trust-news
kubectl config current-context
"$HOME/trust-news-ops-venv/bin/python" -c 'import httpx, pymongo; print("dependencias OK")'
"$HOME/trust-news-ops-venv/bin/python" -m scripts.security.provision_s03_gui_user \
  --context default --username usuario_de_prueba \
  --news-generation-limit 10 --blockchain-validation-limit 10
```

El modo inicial solo consulta Keycloak, ConfigMaps y MongoDB. Comprobar que el
plan indica `client=TrustNewsWeb`, `state=NEW`, `s03_gui_provision=DRY_RUN`, los
dos límites elegidos y un `plan_sha256`. Sustituir los valores de ejemplo por
topes aprobados para la cuenta; no reutilizar automáticamente los límites de
otro cliente. Para un realm que exige verificación de correo, añadir
`--email <correo>` en ambos comandos. Si el estado es `BLOCKED`, no aplicar.

Para reanudar un usuario deshabilitado sin membresía tras un intento fallido
confirmado, incluir `--resume-unmarked-disabled` en el dry-run. Revisar que el
estado sea `RESUME_UNMARKED_DISABLED` y que el usuario sea el esperado; usar la
misma opción y el hash nuevo al aplicar. Esta opción no sirve para adoptar
usuarios deshabilitados preexistentes.

Con el plan exacto revisado:

```bash
"$HOME/trust-news-ops-venv/bin/python" -m scripts.security.provision_s03_gui_user \
  --context default --username usuario_de_prueba \
  --news-generation-limit 10 --blockchain-validation-limit 10 \
  --apply --confirm-context default --confirm-plan '<SHA256 revisado>'
```

El motor vuelve a leer el destino y rechaza un plan que haya cambiado. La
salida correcta termina con `s03_gui_provision=APPLIED`,
`client=TrustNewsWeb`, `membership=active` y `quota=active`, mostrando los topes
aplicados. Si falla a mitad, consultar el estado del usuario en Keycloak. Solo
reanudar una cuenta sin membresía cuando la procedencia del intento fallido
esté confirmada y el nuevo plan `RESUME_UNMARKED_DISABLED` haya sido revisado.

Para una cuenta ya habilitada con una membresía S03 válida pero sin cuota, el
plan puede indicar `state=ADD_QUOTA_ONLY`. Revisar los dos límites y el hash;
el apply de ese plan crea únicamente la cuota y no cambia la cuenta, contraseña,
roles ni membresía. Si la cuota ya existe con límites distintos o está inactiva,
el plan queda bloqueado; este motor no ajusta cuotas existentes. Al aplicar,
confirmar `mode=quota_only quota=active`; después se puede verificar en
`clients_quotas` que `status=Active`, los límites coinciden y el consumo inicial
es cero, sin imprimir el `client_id`.

Entregar la contraseña temporal al titular por un canal privado y retirarla del
host cuando haya cambiado la contraseña. La clave `quota_client_id` del archivo
privado identifica la cuota para futuras operaciones de administración. Aunque
el alta establezca límites, S05 sigue pendiente: usar solo topes aprobados y
mantener supervisión de gasto en las pruebas.
Para la prueba S03, iniciar sesión con cada cuenta y buscar por ID una orden de
la otra. Registrar el código y el cuerpo sin tokens ni secretos. Una respuesta
`403 Resource denied` en las dos direcciones confirma la denegación de esas
consultas cruzadas; no sustituye las demás pruebas de borde ni la aceptación
integral. Devolver el maintenance lock al estado operativo acordado al terminar
la ventana.

## Registro Hetzner/K3s — 2026-11-15

El operador reanudó y habilitó `s03_test_02` con `TrustNewsWeb`. Tras detectar
que faltaba su cuota, el plan `ADD_QUOTA_ONLY` se aplicó sin tocar Keycloak ni la
membresía. MongoDB confirmó `status=Active`, consumo inicial cero y estos
límites: `news_generation=99999999999`,
`blockchain_validation=9999999999999`. El operador confirma que el E2E B ya
funciona con esta cuenta. La prueba cruzada de acceso entre las dos cuentas se
completó: desde `cforcadellm` se
buscó una orden de `s03_test_02`, y desde `s03_test_02` una orden de
`cforcadellm`; ambas consultas devolvieron HTTP 403 con `Resource denied` en la
GUI. Esto confirma el aislamiento de esas dos consultas directas. El operador
confirmó la reactivación del maintenance lock y el bloqueo de la consola en una
ventana privada. La aceptación integral de S03 en Hetzner continúa pendiente.

## Pruebas de borde S11-D — 2026-11-15

En una ventana posterior, el operador desactivó temporalmente el maintenance
lock. Sin certificado cliente, cookies ni sesión, se probaron mediante GET
`/gui/`, `/backend/orders/list`,
`/auth/realms/TrustNews/.well-known/openid-configuration` y
`/auth/admin/realms/master`; las cuatro rutas respondieron `403 text/html`.
Para `/gui/`, la respuesta incluyó `server: cloudflare` y
`cf-ray=a5ae0000dd2a1ec4-MAD`, consistente con el gate del borde. Sin consultar
los eventos de Cloudflare no se atribuye cada 403 a una regla concreta. No se
probó el acceso positivo con certificado/sesión. Después se solicitó reactivar el maintenance lock y el operador mostró la GUI
bloqueada por Cloudflare; la captura no identifica la regla concreta que produjo el bloqueo.
