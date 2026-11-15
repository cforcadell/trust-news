# S03 — alta de usuarios GUI

`scripts/security/provision_s03_gui_user.py` da de alta una identidad humana en
el realm configurado en `apis/gateway-config`. **Todos los usuarios GUI usan
`TrustNewsWeb`**: el script comprueba ese cliente y sus audiencias, pero no crea
ni modifica clientes Keycloak. No concede roles administrativos.

El motor crea el usuario deshabilitado, le asigna una contraseña temporal con
`UPDATE_PASSWORD`, crea su membresía S03 con la clave `user_<sub>` y solo
entonces habilita el usuario. El `org_id` usa la misma fórmula determinista que
el migrador de propietarios (`UUIDv5` del emisor y sujeto). Antes de escribir,
rechaza nombres existentes ajenos al motor, membresías inactivas o conflictivas
y configuración S03/Web incompleta. Si se interrumpe con una membresía S03
válida, el usuario deshabilitado puede reanudarse y recibirá una nueva
contraseña temporal. Si el proceso se corta antes de crear la membresía, solo
se puede reanudar con `--resume-unmarked-disabled`, tras confirmar que ese
usuario fue creado por el intento fallido. El plan exige además que siga
deshabilitado y requiera `UPDATE_PASSWORD`. Un usuario ya habilitado no se
modifica en una repetición. El motor no depende de atributos personalizados
del perfil Keycloak.

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

Mantener el maintenance lock activo durante el alta y la prueba de aislamiento.
Desde el host operativo, con `kubectl` hacia el destino y el entorno Python que
tenga `httpx` y `pymongo`:

```bash
cd ~/trust-news
kubectl config current-context
"$HOME/trust-news-ops-venv/bin/python" -c 'import httpx, pymongo; print("dependencias OK")'
"$HOME/trust-news-ops-venv/bin/python" -m scripts.security.provision_s03_gui_user \
  --context default --username usuario_de_prueba
```

El modo inicial solo consulta Keycloak, ConfigMaps y MongoDB. Comprobar que el
plan indica `client=TrustNewsWeb`, `state=NEW`, `s03_gui_provision=DRY_RUN` y
un `plan_sha256`. Para un realm que exige verificación de correo, añadir
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
  --apply --confirm-context default --confirm-plan '<SHA256 revisado>'
```

El motor vuelve a leer el destino y rechaza un plan que haya cambiado. La
salida correcta termina con `s03_gui_provision=APPLIED`,
`client=TrustNewsWeb`, `membership=active` y `quota=not_managed`. Si falla a mitad,
consultar el estado del usuario en Keycloak. Solo reanudar una cuenta sin
membresía cuando la procedencia del intento fallido esté confirmada y el nuevo
plan `RESUME_UNMARKED_DISABLED` haya sido revisado.

Entregar la contraseña temporal al titular por un canal privado y retirarla del
host cuando haya cambiado la contraseña. La clave `quota_client_id` del archivo
privado sirve para crear una cuota mediante la API Admin existente; el script
no inserta ni modifica `clients_quotas`. Sin cuota, el usuario puede iniciar
sesión y consultar su lista vacía, pero no debe iniciar trabajos con gasto.
Para la prueba S03 pendiente, iniciar sesión con la nueva cuenta, comprobar
que no ve las órdenes del primer usuario y que el detalle de una orden ajena
se deniega. Registrar los resultados sin tokens ni secretos y devolver el
maintenance lock al estado operativo acordado al terminar la ventana.
