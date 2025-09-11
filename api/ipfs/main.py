from fastapi import FastAPI, UploadFile, File, HTTPException
import httpx

app = FastAPI()

INFURA_IPFS_API = "https://ipfs.infura.io:5001/api/v0/add"


@app.post("/ipfs/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # leemos el archivo en memoria
        file_bytes = await file.read()

        # enviamos a IPFS vía Infura
        async with httpx.AsyncClient() as client:
            response = await client.post(
                INFURA_IPFS_API,
                files={"file": (file.filename, file_bytes)},
            )

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        data = response.json()
        # Infura devuelve {"Name": "...", "Hash": "Qm...", "Size": "..."}
        cid = data.get("Hash")

        return {"cid": cid}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

