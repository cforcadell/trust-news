from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

# Configuración
import os



# Inicializar FastAPI
app = FastAPI(title="API de Validación de Aserciones ")

# Modelo de entrada
class TextoEntrada(BaseModel):
    texto: str

# Función que llama a Mistral API
def verificar_asercion(texto: str):
    url = os.getenv("API_URL")
    API_KEY = os.getenv("MISTRAL_API_KEY")
    MODEL = os.getenv("MISTRAL_MODEL", "mistral-tiny")
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                   "Validame la siguiente aserción. Devueve dos tags. En 'resultado': TRUE, FALSE o UNKNOWN. A continuacion en el tag 'descripcion' la explicacion si es necesaria. Ajustate al formato.\n\n"
                    f"Texto a analizar:\n{texto}"
                )
            }
        ],
        "temperature": 0.3,
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)

# Endpoint
@app.post("/verificar")
def verificar(texto_entrada: TextoEntrada):
    resultado = verificar_asercion(texto_entrada.texto)
    return {"verificación": resultado}
