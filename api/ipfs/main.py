from fastapi import FastAPI, UploadFile, File, HTTPException
import httpx

app = FastAPI()

LOCAL_IPFS_API_ADD = "http://127.0.0.1:5001/api/v0/add"
LOCAL_IPFS_API_CAT = "http://127.0.0.1:5001/api/v0/cat"

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

@app.post("/ipfs/download/{cid}")
async def download_file(cid: str):
    if not cid.startswith(("Qm", "bafy")):
        raise HTTPException(status_code=422, detail="CID inválido")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                LOCAL_IPFS_API_CAT,
                data={"ipfs-path": cid},
            ) as resp:

                # 1) Si no es 200, lee el body entero antes de fallar
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=error_body.decode(errors="replace")
                    )

                # 2) Si es 200, devuelve el stream
                return StreamingResponse(
                    resp.aiter_bytes(),
                    media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{cid}"'}
                )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))