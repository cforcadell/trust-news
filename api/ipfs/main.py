import os
from fastapi import FastAPI, UploadFile, File, HTTPException
import httpx
from fastapi.responses import StreamingResponse

app = FastAPI()

# Variables de entorno (con valores por defecto)
LOCAL_IPFS_API_ADD = os.getenv("IPFS_API_ADD", "http://127.0.0.1:5001/api/v0/add")
LOCAL_IPFS_API_CAT = os.getenv("IPFS_API_CAT", "http://127.0.0.1:5001/api/v0/cat")


@app.post("/ipfs/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                LOCAL_IPFS_API_ADD,
                files={"file": (file.filename, file_bytes)},
            )

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        data = response.json()
        cid = data.get("Hash")

        return {"cid": cid}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ipfs/{cid}")
async def get_ipfs_file(cid: str):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{LOCAL_IPFS_API_CAT}?arg={cid}")

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        # devolvemos el contenido tal cual (puede ser binario o texto)
        return {"cid": cid, "content": response.text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
