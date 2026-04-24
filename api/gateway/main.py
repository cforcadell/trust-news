import os
import logging
from typing import Any
import aiohttp
from fastapi import FastAPI, Request, HTTPException, Depends, APIRouter, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from dotenv import load_dotenv

# Cargar env
load_dotenv()

# Logging
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("api-gateway")

app = FastAPI(
    title="Unified API Gateway",
    root_path="/backend",
)

# ============================================================
# Config / constantes (desde env)
# ============================================================
NEWS_HANDLER_URL = os.getenv("NEWS_HANDLER_URL", "http://news-handler.apis.svc.cluster.local:8072")
NEWS_CHAIN_URL = os.getenv("NEWS_CHAIN_URL", "http://news-chain.apis.svc.cluster.local:8073")
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs-fastapi.apis.svc.cluster.local:8060")
GENERATE_ASSERTIONS_URL = os.getenv("GENERATE_ASSERTIONS_URL", "http://generate-asertions.apis.svc.cluster.local:8071")

KEYCLOAK_SERVER_INNER_URL = os.getenv("KEYCLOAK_SERVER_INNER_URL", "http://localhost:8080")
KEYCLOAK_SERVER_HOSTNAME = os.getenv("KEYCLOAK_SERVER_HOSTNAME", "https://localhost")
KEYCLOAK_SERVER_PORT = os.getenv("KEYCLOAK_SERVER_PORT", "7443")
KEYCLOAK_SERVER_PATH = os.getenv("KEYCLOAK_SERVER_PATH", "auth")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "TrustNews")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "TrustNewsWeb")

KEYCLOAK_REALM_EXTERNAL_URL = f"{KEYCLOAK_SERVER_HOSTNAME}:{KEYCLOAK_SERVER_PORT}/{KEYCLOAK_SERVER_PATH}/realms/{KEYCLOAK_REALM}"
KEYCLOAK_CERTS_URL = f"{KEYCLOAK_SERVER_INNER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

# ============================================================
# Autenticación Keycloak (OAuth2 / OIDC)
# ============================================================

# FIX: Definición del esquema que faltaba (el NameError)
# El tokenUrl debe ser la ruta relativa desde la raíz del API para Swagger
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

@app.post("/auth/login")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Intercambia credenciales por un token de Keycloak."""
    token_url = f"{KEYCLOAK_SERVER_INNER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    
    payload = {
        "grant_type": "password",
        "client_id": KEYCLOAK_CLIENT_ID,
        "username": form_data.username,
        "password": form_data.password,
        "scope": "openid profile email",
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(token_url, data=payload) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Keycloak login failed: {data}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Credenciales incorrectas en Keycloak"
                    )
                return {
                    "access_token": data["access_token"],
                    "token_type": "bearer",
                    "expires_in": data.get("expires_in"),
                    "refresh_token": data.get("refresh_token")
                }
        except Exception as e:
            logger.error(f"Error de conexión con Keycloak: {e}")
            raise HTTPException(status_code=502, detail="Servidor de identidad no disponible")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Valida el token JWT emitido por Keycloak."""
    # En entornos K8s a veces es necesario forzar el Host si Keycloak es estricto
    headers_for_keycloak = {"Host": "localhost"}
    
    try:
        # 1. Obtener JWKS
        async with aiohttp.ClientSession() as session:
            async with session.get(KEYCLOAK_CERTS_URL, headers=headers_for_keycloak, ssl=False) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=500, detail="Error contactando Keycloak")
                jwks = await resp.json()

        # 2. Obtener KID
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header.get("kid"):
                rsa_key = {k: key[k] for k in ["kty", "kid", "use", "n", "e"]}
                break
        
        if not rsa_key:
            raise HTTPException(status_code=401, detail="Clave de token no válida")

        # 3. Decodificación
        # Nota: 'audience' suele ser el client_id o 'account' en Keycloak
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=["account", KEYCLOAK_CLIENT_ID], 
            issuer=KEYCLOAK_REALM_EXTERNAL_URL
        )
        
        logger.info(f"Token validado: {payload.get('preferred_username')}")
        return payload

    except JWTError as e:
        logger.error(f"JWT Validation Error: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected Auth Error: {e}")
        raise HTTPException(status_code=401, detail="Error interno de autenticación")

# ============================================================
# Helper Proxy Asíncrono
# ============================================================
async def proxy_request(request: Request, target_url: str):
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    body = await request.body()
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body
            ) as response:
                # Intentamos parsear JSON si es posible, si no, devolvemos raw
                resp_content = await response.read()
                try:
                    content_json = await response.json()
                    return JSONResponse(content=content_json, status_code=response.status)
                except:
                    return JSONResponse(content=resp_content.decode(), status_code=response.status)
        except Exception as e:
            logger.error(f"Error conectando con {target_url}: {e}")
            raise HTTPException(status_code=502, detail="Error de comunicación interna")

# ============================================================
# Router Principal
# ============================================================
router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/extraer")
async def proxy_extraer(request: Request):
    return await proxy_request(request, f"{GENERATE_ASSERTIONS_URL}/extraer")

@router.post("/publishNew")
async def proxy_publish_new(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/publishNew")

@router.post("/publishWithAssertions")
async def proxy_publish_with_assertions(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/publishWithAssertions")

@router.get("/news")
async def proxy_get_news(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/news")

# IPFS Proxy
@router.get("/ipfs/{cid}")
async def proxy_get_ipfs(cid: str, request: Request):
    return await proxy_request(request, f"{IPFS_API_URL}/ipfs/{cid}")

# Ethereum Proxy
@router.get("/tx/{hash}")
async def proxy_get_tx(hash: str, request: Request):
    return await proxy_request(request, f"{NEWS_CHAIN_URL}/tx/{hash}")

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8500")))