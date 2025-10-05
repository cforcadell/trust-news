import requests

# Endpoint
url = "http://localhost:8072/publishNew"

# Payload JSON
payload = {
    "text": "Catalunya tiene una poblacion de 8 millones de habitantes de los que 2 son menores edad y 3 mayores de 65."
}

# Headers
headers = {
    "Content-Type": "application/json"
}

# Llamada POST
response = requests.post(url, json=payload, headers=headers)

# Mostrar resultados
print("Status code:", response.status_code)
try:
    print("Response:", response.json())
except Exception:
    print("Response content:", response.text)
