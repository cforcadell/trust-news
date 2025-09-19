from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

# Configuración
import os





# Inicializar FastAPI
app = FastAPI(title="API de Extracción de Aserciones Verificables")

# Modelo de entrada
class TextoEntrada(BaseModel):
    texto: str

# Función que llama a Mistral API
def extraer_aserciones_verificables(texto: str):
    
    url = os.getenv("API_URL")
    API_KEY = os.getenv("MISTRAL_API_KEY")
    MODEL = os.getenv("MISTRAL_MODEL", "mistral-tiny")
    print(url)

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
                    "Extrae solo las aserciones verificables que contengan cifras objetivables y eliminen cualquier valoración subjetiva. "
                    "Formatea el resultado como una lista de aserciones con sus fuentes sugeridas para verificación con su pais asociado, en formato JSON. "
                    "La lista debe contener objetos con las claves 'asercion','fuente sugerida' y 'pais'. "
                    "Los valores de fuentes son: ECONOMIA, INE, EUROSTAT, FMI, BANCO MUNDIAL, ONU, OMS, UNESCO, OIT, OCDE, UNICEF, FAO, PNUD, CEPAL, ECDC, JHU, WHO... "
                    "Los valores de pais son los paises existentes: España, Francia, Alemania, Italia, Portugal, Reino Unido, Estados Unidos, Canada, Mexico, Argentina, Brasil, Chile, Colombia, Peru, Venezuela... "
                    "Si no hay aserciones verificables, devuelve una lista vacía.\n\n"
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
@app.post("/extraer")
def extraer(texto_entrada: TextoEntrada):
    resultado = extraer_aserciones_verificables(texto_entrada.texto)
    return {"aserciones": resultado}
