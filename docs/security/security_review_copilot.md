# Revisión de seguridad - Assermetry / trust-news

Fecha: 2026-11-03

## Resumen ejecutivo

La roadmap adjunta (`docs/next_releases.md`) es coherente con el estado real del repositorio: admite explícitamente que varios controles críticos aún no están cerrados y que la transición a producción requiere endurecimiento de identidad, segmentación de red, y recuperación verificable. Sin embargo, el repositorio actual todavía contiene evidencias de riesgo concreto en CI y en los manifiestos de despliegue.

Los riesgos más relevantes no son teóricos: el pipeline de despliegue sigue usando `ssh-keyscan` sin clave de host verificable y desactiva la validación TLS del API de K3s. La política de red y el aislamiento de servicios tampoco están probados ni implementados de forma consistente con la hoja de ruta.

## Hallazgos principales

### 1) CI con confianza SSH y TLS desactivada para K3s

**Evidencia**
- `.gitlab-ci.yml`:
  - `ssh-keyscan -p 2222 -H "$HETZNER_IP" >> ~/.ssh/known_hosts`
  - `kubectl config set-cluster default --server=https://127.0.0.1:6443 --insecure-skip-tls-verify=true`

**Riesgo**
- Un atacante con capacidad de interceptar la ruta de preparación o un endpoint falso podría hacer que la CI confíe en un host no legítimo o en un k8s API incorrecto.
- El resultado podría permitir despliegue de software o exfiltración de credenciales del runner.

**Comparación con la hoja de ruta**
- `docs/next_releases.md` y `docs/issues.md` ya documentan este problema como ISSUE-003 y ISSUE-004, y lo sitúan en la versión v0.0.16.
- Es decir, la amenaza está reconocida, pero no corregida en la rama actual.

### 2) Exposición potencial de servicios administrativos y falta de aislamiento neto

**Evidencia**
- `api/admin/main.py` expone endpoints de administración sin validación local de JWT/rol en el servicio.
- `k8s/apis/gateway/configmap.yaml` usa JWKS interno vía HTTP y no hay evidencia de `NetworkPolicy` claros en la estructura revisada.
- `k8s/blockchain/rpc/statefulset.yaml` sigue mostrando opciones inseguras (`--allow-insecure-unlock`, `--http.api=...admin,personal`, wildcards de CORS y hosts virtuales). 

**Riesgo**
- Un pod comprometido o un flujo interno no autorizado podría llegar a servicios administrativos o cambiar configuración crítica.
- En la ruta con Blockchain enabled, los RPC administrativos expuestos aumentarían la superficie de ataque.

**Comparación con la hoja de ruta**
- `docs/next_releases.md` exige explícitamente quitar `admin`, `personal`, unlock remoto y wildcards de CORS, además de implementar default-deny y políticas de red.
- Esta hardening no está implementada todavía.

### 3) Recuperación y respaldos no suficientemente demostrados para producción

**Evidencia**
- `scripts/k8s/backup-mongodb.sh` genera copias comprimidas con comprobación de checksum, pero no se observa cifrado externo ni restauración aislada demostrada.
- La hoja de ruta exige backups cifrados externos, restauración aislada de MongoDB/Keycloak y validación de hash, tamaño, legibilidad y recuperación.

**Riesgo**
- Pérdida de datos, corrupción del estado o incapacidad de restauración tras incidente.

### 4) Validación de identidad y control de borde: mejorado, pero sin evidencia de cierre de la ventana de riesgo

**Evidencia**
- `api/gateway/main.py` valida RS256, issuer, audience y `azp`/`client_id` con `KEYCLOAK_ALLOWED_CLIENT_IDS`.
- `k8s/traefik/values-prod.yaml` limita la cabecera `forwardedHeaders` a rangos de Cloudflare.

**Riesgo**
- Esto es una base sólida, pero no reemplaza la necesidad de verificar la regla efectiva de Cloudflare, el firewall de Hetzner, el lock de mantenimiento y la prueba de revocación/certificado admin.
- La transición de reglas mTLS descrita en `docs/next_releases.md` requiere validación funcional y prueba de rechazo, no solo configuración declarada.

## Síntesis de control

### Lo que está bien

- El Gateway realiza validación JWT razonable: firma, issuer, audience y cliente presentador.
- La documentación es explícita sobre los riesgos y establece una ruta de hardening por versiones.
- La guía de despliegue documenta controles de mantenimiento y mTLS, aunque aún no están evidenciados en la operación efectiva.

### Lo que falta para una operación segura

- Host key fijada y verificada externamente.
- Validación de CA y nombre del API de K3s.
- Red de clúster por defecto denegada.
- NetworkPolicy verificados para servicios y administraciones.
- Backups cifrados y restauración aislada probada.
- Comprobación formal de la ventana de mTLS/locks antes de abrir acceso externo.

## Tabla de hallazgos

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🔴 CRITICAL | .gitlab-ci.yml | 43-52 | CI trusts the SSH host key via `ssh-keyscan` and disables K3s TLS verification with `--insecure-skip-tls-verify=true` | 9/10 |
| 2 | 🟠 HIGH | api/admin/main.py | 1087-1354 | Admin API routes lack local authentication/authorization enforcement and can be reached from compromised internal workloads | 8/10 |
| 3 | 🟡 MEDIUM | k8s/blockchain/rpc/statefulset.yaml | 8, 77-89 | Geth RPC exposes admin/personal APIs, wildcard CORS and insecure unlock options that are explicitly scheduled for removal in v0.0.16 | 8/10 |
| 4 | 🟡 MEDIUM | scripts/k8s/backup-mongodb.sh | 35, 58-61 | Backup process lacks proven encrypted external backup and isolated restore verification | 7/10 |

## Conclusión

El repositorio no está en estado listo para producción sin más endurecimiento. La hoja de ruta presenta una secuencia razonable de mitigación, pero la rama actual aún conserva riesgos de autenticación y despliegue perfectamente reconocidos por la documentación propia del proyecto.

No es una auditoría de penetración completa ni un análisis exhaustivo de dependencias, pero sí confirma que hay una brecha de seguridad material en la configuración actual de CI y en la segregación de servicios que debe resolverse antes de aceptar acceso externo o producción real.
