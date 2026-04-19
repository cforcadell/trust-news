import os
import logging
from typing import Any
import aiohttp
from fastapi import FastAPI, Request, HTTPException, Depends, APIRouter, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from dotenv import load_dotenv


# Cargar env
load_dotenv()

# Logging
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("api-gateway")

app = FastAPI(title="Unified API Gateway (Keycloak Protected)")

# ============================================================
# Config / constantes (desde env)
# ============================================================
# URLs internas en Kubernetes
NEWS_HANDLER_URL = os.getenv("NEWS_HANDLER_URL", "http://news-handler.apis.svc.cluster.local:8072")
NEWS_CHAIN_URL = os.getenv("NEWS_CHAIN_URL", "http://news-chain.apis.svc.cluster.local:8073")
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs-fastapi.apis.svc.cluster.local:8060")
GENERATE_ASSERTIONS_URL = os.getenv("GENERATE_ASSERTIONS_URL", "http://generate-asertions.apis.svc.cluster.local:8071")

# Keycloak config
KEYCLOAK_SERVER_INNER_URL = os.getenv("KEYCLOAK_SERVER_INNER_URL", "http://localhost:8080")

KEYCLOAK_SERVER_HOSTNAME = os.getenv("KEYCLOAK_SERVER_HOSTNAME", "https://localhost")
KEYCLOAK_SERVER_PORT  = os.getenv("KEYCLOAK_SERVER_PORT", "7443")
KEYCLOAK_SERVER_PATH  = os.getenv("KEYCLOAK_SERVER_PATH", "auth")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "TrustNews")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "TrustNewsWeb")
KEYCLOAK_REALM_EXTERNAL_URL = f"{KEYCLOAK_SERVER_HOSTNAME}:{KEYCLOAK_SERVER_PORT}/{KEYCLOAK_SERVER_PATH}/realms/{KEYCLOAK_REALM}"

# Obtén la clave pública de tu Keycloak o usa el endpoint de JWKS para validación
KEYCLOAK_CERTS_URL = f"{KEYCLOAK_SERVER_INNER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

# ============================================================
# Autenticación Keycloak (OAuth2 / OIDC)
# ============================================================
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Valida el token JWT emitido por Keycloak con trazas detalladas de depuración.
    """
    token = credentials.credentials
    headers_for_keycloak = {"Host": "localhost"}
    
    try:
        # 1. Obtener las claves públicas (JWKS) de Keycloak
        async with aiohttp.ClientSession() as session:
            async with session.get(KEYCLOAK_CERTS_URL, headers=headers_for_keycloak,ssl=False) as resp:
                if resp.status != 200:
                    logger.error(f"Error conectando a Keycloak JWKS: {resp.status}")
                    raise HTTPException(status_code=500, detail="No se pudo contactar con el servidor de identidad")
                jwks = await resp.json()

        # 2. Extraer el header para identificar la clave (KID)
        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as e:
            logger.error(f"No se pudo leer el header del token: {e}")
            raise HTTPException(status_code=401, detail="Token mal formado")

        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header.get("kid"):
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
                break
        
        if not rsa_key:
            logger.error(f"No se encontró una clave pública que coincida con el kid: {unverified_header.get('kid')}")
            raise HTTPException(status_code=401, detail="Clave de token no válida")

        # 3. Preparar validación y Logs de depuración para 'Invalid Issuer'
        expected_issuer = KEYCLOAK_REALM_EXTERNAL_URL
        
        # Extraemos los claims sin validar para comparar en el log si hay error
        unverified_claims = jwt.get_unverified_claims(token)
        actual_issuer = unverified_claims.get("iss")
        
        logger.info(f"Validando token - Issuer esperado: {expected_issuer}")
        logger.info(f"Validando token - Issuer en token: {actual_issuer}")

        # 4. Decodificación y Validación Real
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience="account",  # Cambia a tu Client ID si es necesario
            issuer=expected_issuer,
            options={
                "verify_iss": True  # This bypasses the strict string comparison
            }
        )
        
        logger.info(f"Token validado exitosamente para el usuario: {payload.get('preferred_username')}")
        return payload

    except JWTError as e:
        # Aquí capturamos específicamente el error de "Invalid issuer" entre otros
        logger.error(f"Error de validación JWT: {str(e)}")
        
        # Log extra para diagnosticar diferencias de strings
        unverified_claims = jwt.get_unverified_claims(token)
        logger.error(f"DETALLE: iss en token: '{unverified_claims.get('iss')}'")
        logger.error(f"DETALLE: iss esperado: '{expected_issuer}'")
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token inválido: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error inesperado en autenticación: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Error interno de autenticación"
        )
# ============================================================
# Helper Proxy Asíncrono
# ============================================================
async def proxy_request(request: Request, target_url: str):
    """
    Reenvía la petición HTTP de manera transparente al microservicio de destino.
    """
    # Excluimos el host para evitar conflictos de enrutamiento en Nginx/Ingress internos
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    
    # Leemos el body si existe
    body = await request.body()
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body
            ) as response:
                content = await response.read()
                return JSONResponse(
                    content=await response.json() if "application/json" in response.headers.get("Content-Type", "") else content.decode(),
                    status_code=response.status
                )
        except aiohttp.ClientError as e:
            logger.error(f"Error al conectar con {target_url}: {e}")
            raise HTTPException(status_code=502, detail="Error de comunicación con el servicio interno")

# ============================================================
# Router Principal (Todas las rutas expuestas en el JS)
# ============================================================
router = APIRouter(dependencies=[Depends(get_current_user)])

# --- GENERATE API ---
@router.post("/extraer")
async def proxy_extraer(request: Request):
    return await proxy_request(request, f"{GENERATE_ASSERTIONS_URL}/extraer")

# --- NEWS API ---
@router.post("/publishNew")
async def proxy_publish_new(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/publishNew")

@router.post("/publishWithAssertions")
async def proxy_publish_with_assertions(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/publishWithAssertions")

@router.post("/find-order-by-text")
async def proxy_find_order_by_text(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/find-order-by-text")

@router.get("/news")
async def proxy_get_news(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/news")

@router.get("/orders/{order_id}")
async def proxy_get_order(order_id: str, request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/orders/{order_id}")

@router.get("/news/{order_id}/events")
async def proxy_get_events(order_id: str, request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/news/{order_id}/events")

@router.get("/checkOrderConsistency/{order_id}")
async def proxy_check_consistency(order_id: str, request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/checkOrderConsistency/{order_id}")

@router.post("/extract_text_from_url")
async def proxy_extract_text_from_url(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/extract_text_from_url")

# --- IPFS API ---
@router.get("/ipfs/{cid}")
async def proxy_get_ipfs(cid: str, request: Request):
    return await proxy_request(request, f"{IPFS_API_URL}/ipfs/{cid}")

# --- ETHEREUM API ---
@router.get("/tx/{hash}")
async def proxy_get_tx(hash: str, request: Request):
    return await proxy_request(request, f"{NEWS_CHAIN_URL}/tx/{hash}")

@router.get("/block/{block_id}")
async def proxy_get_block(block_id: str, request: Request):
    return await proxy_request(request, f"{NEWS_CHAIN_URL}/block/{block_id}")

@router.get("/blockchain/post/{post_id}")
async def proxy_get_post(post_id: str, request: Request):
    return await proxy_request(request, f"{NEWS_CHAIN_URL}/blockchain/post/{post_id}")


# Registramos el router bajo el path /backend para unificar
app.include_router(router, prefix="/trustnews")

if __name__ == "__main__":
    import uvicorn
    logger.info("Iniciando API Gateway Unificado")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8500")))