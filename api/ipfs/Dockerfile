# Imagen base oficial de Python 3.11 slim
FROM python:3.11-slim

# Setea el directorio de trabajo
WORKDIR /app

# Copia requirements
COPY requirements.txt .

# Instala dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código
COPY main.py .

# Variables de entorno con valores por defecto
# cambiables en build con --build-arg o en runtime con -e
ARG IPFS_API_HOST=172.17.0.1
ARG IPFS_API_PORT=5001

ENV IPFS_API_ADD=http://${IPFS_API_HOST}:${IPFS_API_PORT}/api/v0/add
ENV IPFS_API_CAT=http://${IPFS_API_HOST}:${IPFS_API_PORT}/api/v0/cat

# Expone el puerto 8060
EXPOSE 8060

# Comando para correr FastAPI con Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8060", "--log-level", "debug"]
