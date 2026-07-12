# Assermetry - Flujo GitLab, GitHub y release

Este documento describe el flujo operativo cuando el desarrollo se hace en la
rama `postTFM`, el despliegue se lanza manualmente desde GitLab CI y despues se
promociona el cambio a `main` en GitHub y GitLab.

---

## 1. Remotos Git configurados

Estado actual de `git remote -v`:

```text
gitlab  git@gitlab.com:cforcadell/tfm.git (fetch)
gitlab  git@gitlab.com:cforcadell/tfm.git (push)
origin  https://github.com/cforcadell/trust-news.git (fetch)
origin  https://github.com/cforcadell/trust-news.git (push)
origin  git@gitlab.com:cforcadell/tfm.git (push)
```

Interpretacion:

- `origin` hace `fetch` desde GitHub.
- `origin` tiene dos destinos de `push`: GitHub y GitLab.
- `gitlab` apunta explicitamente a GitLab para `fetch` y `push`.
- GitHub funciona como repositorio principal visible/espejo de codigo.
- GitLab ejecuta el pipeline de build/deploy contra Hetzner.

Para evitar dudas durante despliegues, usar `git push gitlab postTFM` cuando se
quiera activar o preparar el pipeline de GitLab. Usar `git push origin postTFM`
solo cuando se quiera empujar a todos los destinos configurados en `origin`.

---

## 2. Desarrollo en `postTFM`

Antes de empezar, actualizar la rama de trabajo con la base estable:

```bash
git fetch origin main
git checkout postTFM
git merge origin/main
```

Revisar cambios:

```bash
git status --short
git diff --stat
```

Crear el commit:

```bash
git add <ficheros>
git commit -m "<mensaje>"
```

Subir a GitLab para que el commit este disponible en el pipeline:

```bash
git push gitlab postTFM
```

Si tambien se quiere actualizar GitHub en ese momento:

```bash
git push origin postTFM
```

---

## 3. Pipeline manual de despliegue en GitLab

El pipeline esta definido en `.gitlab-ci.yml` y usa la variable `PROFILE`.

Perfiles productivos habituales:

| PROFILE | Uso |
|---|---|
| `infra-prod` | Despliega MongoDB, Kafka, IPFS, Keycloak, mongo-express y logs. |
| `blockchain-prod` | Despliega la red privada geth. |
| `apis-frontend-prod` | Despliega APIs y frontend. Es el valor por defecto. |

Procedimiento normal para actualizar APIs/frontend:

1. Abrir GitLab.
2. Ir a `Build > Pipelines > Run pipeline`.
3. Seleccionar branch `postTFM`.
4. Definir `PROFILE=apis-frontend-prod`.
5. Ejecutar el pipeline.
6. Ejecutar primero el job `build` si queda manual.
7. Ejecutar despues el job `deploy`.

El job `build` genera `build.json` con las imagenes exactas construidas y
publicadas en el GitLab Registry. El job `deploy` ejecuta:

```bash
skaffold deploy --build-artifacts=build.json --profile=$PROFILE
```

Antes de `apis-frontend-prod`, el job `check_mongodb_bootstrap` valida que
MongoDB tenga el perfil `default` de dominios y las taxonomias de normalizacion.
Si falla, desplegar `infra-prod` o ejecutar el bootstrap documentado en
[`k8s-common.md`](k8s-common.md).

---

## 4. Verificacion despues del deploy

Comprobar pods y logs:

```bash
kubectl get pods -n apis -o wide
kubectl get pods -n frontend -o wide
kubectl logs deployment/gateway -n apis --tail=80
kubectl logs deployment/news-handler -n apis --tail=80
kubectl logs deployment/evidence-search -n apis --tail=80
```

Comprobar frontend mediante tunel:

```bash
# En Hetzner
kubectl port-forward service/frontend-service -n frontend 10443:443

# En local
ssh -i ./id_rsa_hetzner_deploy -p 2222 \
  -L 9443:127.0.0.1:10443 \
  <usuario>@<hetzner-ip>
```

Abrir:

```text
https://localhost:9443/
https://localhost:9443/backend/docs
```

Ver tambien:

- [`skaffold-server.md`](skaffold-server.md)
- [`k8s-common.md`](k8s-common.md)

---

## 5. Promocion a `main`

Cuando el despliegue de `postTFM` ya esta validado, promocionar el cambio a
`main` en los dos repositorios.

### 5.1 GitHub

1. Abrir GitHub: `cforcadell/trust-news`.
2. Crear Pull Request de `postTFM` hacia `main`.
3. Revisar diff, checks y descripcion.
4. Hacer merge a `main`.
5. Actualizar localmente:

```bash
git fetch origin main
git checkout main
git pull origin main
```

### 5.2 GitLab

1. Abrir GitLab: `cforcadell/tfm`.
2. Crear Merge Request de `postTFM` hacia `main`.
3. Revisar pipeline/checks si aplica.
4. Hacer merge a `main`.
5. Actualizar localmente si se necesita trabajar contra GitLab:

```bash
git fetch gitlab main
```

Si GitHub y GitLab deben quedar exactamente alineados, verificar ambos `main`:

```bash
git fetch origin main
git fetch gitlab main
git log --oneline --decorate --max-count=5 origin/main
git log --oneline --decorate --max-count=5 gitlab/main
```

---

## 6. Release

Crear la release despues de que `main` este actualizado en GitHub y GitLab.

Checklist previo:

- El commit de `postTFM` esta desplegado y verificado en Hetzner.
- La PR GitHub `postTFM -> main` esta mergeada.
- La MR GitLab `postTFM -> main` esta mergeada.
- Los remotos `origin/main` y `gitlab/main` apuntan al commit esperado.
- No hay secretos ni `.env` versionados.

Procedimiento recomendado:

```bash
git checkout main
git fetch origin main
git pull origin main
git tag -a v<version> -m "Release v<version>"
git push origin v<version>
git push gitlab v<version>
```

Despues, crear la release en GitHub y, si se usa tambien como registro formal,
crear la release equivalente en GitLab con el mismo tag.

Formato sugerido de notas:

```md
## Cambios
- ...

## Despliegue
- Validado en Hetzner desde `postTFM`.
- Perfil desplegado: `apis-frontend-prod`.

## Verificacion
- Frontend accesible.
- Gateway/API docs accesibles.
- Pods `apis` y `frontend` en estado correcto.
```

---

## 7. Resumen rapido

```bash
git checkout postTFM
git fetch origin main
git merge origin/main
git add <ficheros>
git commit -m "<mensaje>"
git push gitlab postTFM
```

En GitLab:

```text
Run pipeline -> branch postTFM -> PROFILE=apis-frontend-prod -> build -> deploy
```

Si el despliegue es correcto:

```text
GitHub PR: postTFM -> main
GitLab MR: postTFM -> main
Release desde main con tag v<version>
```
