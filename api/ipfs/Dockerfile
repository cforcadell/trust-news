# Imagen base oficial de Python 3.11 slim
FROM python:3.11-slim

# Crear un usuario de sistema sin privilegios (llamado 'appuser')
RUN useradd -m -r appuser

# Setear el directorio de trabajo
WORKDIR /app

# Copiar requisitos primero para aprovechar el caché de Docker
COPY ipfs/requirements.txt .

# Instalar dependencias como root para que estén disponibles globalmente
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente transfiriendo la propiedad al usuario 'appuser'
COPY --chown=appuser:appuser common ./common
COPY --chown=appuser:appuser ipfs ./ipfs

# Variables de entorno con valores por defecto
# (Se declaran después de instalar dependencias para que si cambian en el build, 
# no se invalide el caché de pip install)
ARG IPFS_API_HOST=172.17.0.1
ARG IPFS_API_PORT=5001

ENV IPFS_API_ADD=http://${IPFS_API_HOST}:${IPFS_API_PORT}/api/v0/add
ENV IPFS_API_CAT=http://${IPFS_API_HOST}:${IPFS_API_PORT}/api/v0/cat

# Cambiar la ejecución al usuario sin privilegios
USER appuser

# Expone el puerto 8060
EXPOSE 8060

# Comando para correr FastAPI con Uvicorn
CMD ["uvicorn", "ipfs.main:app", "--host", "0.0.0.0", "--port", "8060", "--log-level", "debug"]