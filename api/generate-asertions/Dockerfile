# Imagen base oficial de Python
FROM python:3.11-slim

# Crear directorio de la aplicación
WORKDIR /app

# Copiar requisitos primero (para aprovechar caché)

COPY generate-asertions/requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common

# Copia la carpeta 'news' y todo su contenido
COPY generate-asertions /app/generate-asertions

# Exponer el puerto donde correrá la API
EXPOSE 8071

# Comando por defecto: lanzar uvicorn
CMD ["uvicorn", "generate-asertions.main:app", "--host", "0.0.0.0", "--port", "8071"]
