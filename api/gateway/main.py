import os
import logging
from typing import Any, List
import aiohttp
from fastapi import FastAPI, Request, HTTPException, Depends, APIRouter, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from pydantic import BaseModel
from dotenv import load_dotenv
from jose import jwt
from common.async_models import (
    TextoEntrada, 
    PublishRequest, 
    PreGeneratedAssertion,
    PublishWithAssertionsRequest
)

# ============================================================
# Cargar env y Logging
# ============================================================
load_dotenv()

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

KEYCLOAK_REALM_EXTERNAL_URL = f"{KEYCLOAK_SERVER_HOSTNAME}:{KEYCLOAK_SERVER_PORT}/{KEYCLOAK_SERVER_PATH}/realms/{KEYCLOAK_REALM}"
KEYCLOAK_CERTS_URL = f"{KEYCLOAK_SERVER_INNER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

# ============================================================
# Autenticación (Simple Bearer para Swagger)
# ============================================================
security = HTTPBearer()

async def get_current_user(auth: HTTPAuthorizationCredentials = Depends(security)):
    """Valida el token JWT pegado en Swagger o enviado por el cliente."""
    token = auth.credentials
    headers_for_keycloak = {"Host": "localhost"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(KEYCLOAK_CERTS_URL, headers=headers_for_keycloak, ssl=False) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=500, detail="Error contactando Keycloak")
                jwks = await resp.json()

        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header.get("kid"):
                rsa_key = {k: key[k] for k in ["kty", "kid", "use", "n", "e"]}
                break
        
        if not rsa_key:
            raise HTTPException(status_code=401, detail="Clave de token no válida")

        # ============================================================
        # INICIO: Logs añadidos para aud y iss
        # ============================================================
        unverified_claims = jwt.get_unverified_claims(token)
        token_iss = unverified_claims.get("iss", "No especificado")
        token_aud = unverified_claims.get("aud", "No especificado")
        
        logger.info("=== Debug de JWT ===")
        logger.info(f"Issuer recibido (iss): {token_iss}")
        logger.info(f"Issuer esperado      : {KEYCLOAK_REALM_EXTERNAL_URL}")
        logger.info(f"Audience (aud)       : {token_aud}")
        logger.info("====================")
        # ============================================================
        # FIN: Logs añadidos para aud y iss
        # ============================================================

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_REALM_EXTERNAL_URL,
            options={"verify_aud": False}
        )
        
        user = payload.get('preferred_username') or payload.get('client_id') or "service-account"
        logger.info(f"Token validado para: {user}")
        return payload

    except JWTError as e:
        logger.error(f"JWT Validation Error: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected Auth Error: {e}")
        raise HTTPException(status_code=401, detail="Error interno de autenticación")


# ============================================================
# Helpers
# ============================================================
async def proxy_request(request: Request, target_url: str):
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    # Recuperamos el body en bytes. FastAPI ya lo ha parseado y validado
    # con Pydantic en el endpoint, pero lo mantiene en memoria.
    body = await request.body()
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body
            ) as response:
                resp_content = await response.read()
                try:
                    content_json = await response.json()
                    return JSONResponse(content=content_json, status_code=response.status)
                except:
                    return JSONResponse(content=resp_content.decode(), status_code=response.status)
        except Exception as e:
            logger.error(f"Error conectando con {target_url}: {e}")
            raise HTTPException(status_code=502, detail="Error de comunicación interna")


# Función auxiliar para extraer el client_id con la fórmula solicitada
def get_computed_client_id(token: str) -> str:
    unverified_claims = jwt.get_unverified_claims(token)
    sub = unverified_claims.get("sub", "unknown_sub")
    token_client_id = unverified_claims.get("client_id")
    
    if token_client_id:
        return f"{token_client_id}_{sub}"
    else:
        return f"user_{sub}"
    
    
# ============================================================
# Router Principal
# ============================================================
router = APIRouter(dependencies=[Depends(get_current_user)])

# Añadimos los modelos (body: Modelo) para que Swagger exija el JSON correcto

@router.post("/assertions/generate", tags=["Assertions"])
async def proxy_extraer(request: Request, body: TextoEntrada):
    return await proxy_request(request, f"{GENERATE_ASSERTIONS_URL}/extraer")

@router.post("/orders/publishNew", tags=["Orders"])
async def proxy_publish_new(
    request: Request, 
    auth: HTTPAuthorizationCredentials = Depends(get_current_user) # O Depends(security) según tu setup
):
    # Calcular client_id desde el token
    client_id = get_computed_client_id(auth.credentials)
    
    # Inyectar el client_id como query param al microservicio
    target_url = f"{NEWS_HANDLER_URL}/publishNew?client_id={client_id}"
    
    return await proxy_request(request, target_url)

@router.post("/orders/publishWithAssertions", tags=["Orders"])
async def proxy_publish_with_assertions(
    request: Request, 
    auth: HTTPAuthorizationCredentials = Depends(get_current_user)
):
    client_id = get_computed_client_id(auth.credentials)
    
    target_url = f"{NEWS_HANDLER_URL}/publishWithAssertions?client_id={client_id}"
    
    return await proxy_request(request, target_url)

# Los GET se mantienen igual ya que no llevan body
@router.get("/orders/list", tags=["Orders"])
async def proxy_get_news(request: Request):
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/news")

@router.get("/ipfs/{cid}", tags=["IPFS"])
async def proxy_get_ipfs(cid: str, request: Request):
    return await proxy_request(request, f"{IPFS_API_URL}/ipfs/{cid}")

@router.get("/blockchain/tx/{hash}", tags=["Blockchain"])
async def proxy_get_tx(hash: str, request: Request):
    return await proxy_request(request, f"{NEWS_CHAIN_URL}/tx/{hash}")

@router.get("/blockchain/block/{block_id}", tags=["Blockchain"])
async def proxy_get_block(block_id: int, request: Request):
    """
    Obtiene información detallada de un bloque específico y sus transacciones.
    """
    # Cambia NEWS_CHAIN_URL por la URL de tu microservicio de blockchain
    return await proxy_request(request, f"{NEWS_CHAIN_URL}/block/{block_id}")

@router.get("/blockchain/post/{post_id}", tags=["Blockchain"])
async def proxy_get_blockchain_post(post_id: int, request: Request):
    """
    Recupera la información completa de un Post directamente desde el Smart Contract,
    incluyendo su CID de IPFS, aserciones y todas las validaciones asociadas.
    """
    # Se redirige al microservicio que maneja la lógica de web3 (news-chain)
    return await proxy_request(request, f"{NEWS_CHAIN_URL}/blockchain/post/{post_id}")

@router.get("/orders/{order_id}", tags=["Orders"])
async def proxy_get_order(order_id: str, request: Request):
    """Enruta la petición de consulta de una orden al news-handler"""
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/orders/{order_id}")

@router.get("/orders/checkOrderConsistency/{order_id}", tags=["Orders"])
async def proxy_check_order_consistency(order_id: str, request: Request):
    """
    Enruta la petición para comprobar la consistencia de una orden (Order -> IPFS -> Blockchain).
    """
    # Si la función vive en news-chain, cambia NEWS_HANDLER_URL por NEWS_CHAIN_URL
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/checkOrderConsistency/{order_id}")

@router.get("/orders/{order_id}/events", tags=["Orders"])
async def proxy_get_news_events(order_id: str, request: Request):
    """
    Recupera el histórico de eventos de una orden específica (Pipeline events).
    """
    return await proxy_request(request, f"{NEWS_HANDLER_URL}/news/{order_id}/events")

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8500")))