# Assermetry - GitLab flow, GitHub and release

This document describes the operating flow when the development is done in the `postTFM` branch, the deployment is manually launched from GitLab CI and then the switch to `main` is promoted in GitHub and GitLab.

---

## 1. Remotos Git configurados

Current status of `git remote -v`:

```text
gitlab  git@gitlab.com:cforcadell/tfm.git (fetch)
gitlab  git@gitlab.com:cforcadell/tfm.git (push)
origin  https://github.com/cforcadell/trust-news.git (fetch)
origin  https://github.com/cforcadell/trust-news.git (push)
origin  git@gitlab.com:cforcadell/tfm.git (push)
```

Interpretacion:

- `origin` makes `fetch` from GitHub.
- `origin` has two destinations for `push`: GitHub and GitLab.
- `gitlab` explicitly points to GitLab for `fetch` and `push`.
- GitHub functions as the main visible/espejo code repository.
- GitLab runs the build/deploy pipeline against Hetzner.

To avoid any doubts during deployments, use `git push gitlab postTFM` when you want to activate or prepare the GitLab Pipeline. Use `git push origin postTFM` only when you want to push all destinations configured in `origin`.

---

## 2. Development at `postTFM`

Before starting, update the work branch with the stable base:

```bash
git fetch origin main
git checkout postTFM
git merge origin/main
```

Review changes:

```bash
git status --short
git diff --stat
```

Create commit:

```bash
git add <ficheros>
git commit -m "<mensaje>"
```

Upload to GitLab so that the commit is available in the pipeline:

```bash
git push gitlab postTFM
```

If you also want to upgrade GitHub at that time:

```bash
git push origin postTFM
```

---

## 3. Pipeline manual deployment in GitLab

The pipeline is defined in `.gitlab-ci.yml` and uses the `PROFILE` variable.

Perfiles productivos habituales:

| PROFILE | Uso |
|---|---|
| `infra-prod` | Dispatch MongoDB, Kafka, IPFS, Keycloak, Mongo-Express and log. |
| `blockchain-prod` | Deploy the private geth network. |
| `apis-frontend-prod` | Deploy APIs and frontend. It is the default value. |

Normal procedure for updating APIs/frontend:

1. Abrir GitLab.
2. Ir a `Build > Pipelines > Run pipeline`.
3. Seleccionar branch `postTFM`.
4. Definir `PROFILE=apis-frontend-prod`.
5. Run the pipeline.
6. Run the job `build` first if manual is left.
7. Run the job `deploy` later.

The `build` job generates `build.json` with the exact images built and published in the GitLab Registry. The `deploy` job runs:

```bash
skaffold deploy --build-artifacts=build.json --profile=$PROFILE
```

La verificación posterior del pipeline ejecuta
`scripts/k8s/infra/reconcile-keycloak-web-prod.sh` cuando el perfil es
`infra-prod` o `apis-frontend-prod`. Este paso es obligatorio para Hetzner:
alinea las URLs productivas y configura la audiencia OIDC
`TrustNewsGateway` para `TrustNewsWeb` y `TrustNewsApi`. No debe sustituirse
por comandos manuales ni añadirse un client secret al YAML; el script usa la
configuración administrativa del pod de Keycloak y el pipeline solo debe
tener las variables protegidas de acceso al clúster.

Before `apis-frontend-prod`, the job `check_mongodb_bootstrap` validates that MongoDB has the `default` profile of domains and the normalization taxonomies. If it fails, deploy `infra-prod` or run the bootstrap documented in [`k8s-common.md`](k8s-common.md).

---

## 4. Verification after the deploy

Check pods and logs:

```bash
kubectl get pods -n apis -o wide
kubectl get pods -n frontend -o wide
kubectl logs deployment/gateway -n apis --tail=80
kubectl logs deployment/news-handler -n apis --tail=80
kubectl logs deployment/evidence-search -n apis --tail=80
```

The main check is done against the real edge, not against `frontend-service`: direct access to the Service omite Traefik, Gateway, Keycloak and canonical routing. Before testing, deciding and registering the status of the lock; for the functional matrix it must be disabled.

From an authorized client with a valid temporary mTLS certificate, verify `https://assermetry.com` with the validated server TLS string:

- the frontend responds and the resources are charged;
- discovery publica exactamente
`https://assermetry.com/auth/realms/TrustNews` as issuer;
- a secure Gateway route rejects without JWT and works with a valid JWT;
- `/backend/docs`, Swagger, Redoc and OpenAPI return `403` or `404`;
- administrative routes require mTLS and Keycloak authentication;
- Light and Blockchain complete their journeys when they are released.

Do not disable TLS validation. As long as the time rule is still active, verification requests include `--cert <cert.pem>` and `--key <key.pem>`.

If Cloudflare needs to be isolated during a diagnosis, use the Tráfik tunnel of [`skaffold-server.md`](skaffold-server.md#43-diagnostico-por-tunel), preserving hostname, SNI and validation of the source CA. That check is complementary and does not replace the public border test.

See also:

- [`skaffold-server.md`](skaffold-server.md)
- [`k8s-common.md`](k8s-common.md)

---

## 5. Promocion a `main`

When the deployment of `postTFM` is already validated, promote the switch to `main` in both repositories.

### 5.1 GitHub

1. Abrir GitHub: `cforcadell/trust-news`.
2. Create Pull Request from `postTFM` to `main`.
3. Check diff, checks and description.
4. Hacer merge a `main`.
5. Actualizar localmente:

```bash
git fetch origin main
git checkout main
git pull origin main
```

### 5.2 GitLab

1. Abrir GitLab: `cforcadell/tfm`.
2. Create Merge Request from `postTFM` to `main`.
3. Revisar pipeline/checks si aplica.
4. Hacer merge a `main`.
5. Update locally if you need to work against GitLab:

```bash
git fetch gitlab main
```

If GitHub and GitLab must be exactly aligned, check both `main`:

```bash
git fetch origin main
git fetch gitlab main
git log --oneline --decorate --max-count=5 origin/main
git log --oneline --decorate --max-count=5 gitlab/main
```

---

## 6. Release

Create the release after `main` is updated in GitHub and GitLab.

Checklist previo:

- The `postTFM` commit is deployed and verified in Hetzner.
- The PR GitHub `postTFM -> main` is being looted.
- MR GitLab `postTFM -> main` is being looted.
- The `origin/main` and `gitlab/main` remotes point to the expected commit.
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

Then create the release in GitHub and, if used as a formal record, create the equivalent release in GitLab with the same tag.

Suggested note format:

```md
## Cambios
- ...

## Despliegue
- Validado en Hetzner desde `postTFM`.
- Perfil desplegado: `apis-frontend-prod`.

## Verificacion
- Frontend accesible.
- Gateway rechaza sin JWT y acepta un JWT valido.
- Documentacion API no publica: `403` o `404`.
- OIDC, mTLS y rutas administrativas verificados en el borde canonico.
- Pods `apis` y `frontend` en estado correcto.
```

---

## 7. Quick summary

```bash
git checkout postTFM
git fetch origin main
git merge origin/main
git add <ficheros>
git commit -m "<mensaje>"
git push gitlab postTFM
```

In GitLab:

```text
Run pipeline -> branch postTFM -> PROFILE=apis-frontend-prod -> build -> deploy
```

If the deployment is correct:

```text
GitHub PR: postTFM -> main
GitLab MR: postTFM -> main
Release desde main con tag v<version>
```
