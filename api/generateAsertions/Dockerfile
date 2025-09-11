# Imagen base oficial de Python
FROM python:3.11-slim

# Crear directorio de la aplicación
WORKDIR /app

# Copiar requisitos primero (para aprovechar caché)
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY . .

# Exponer el puerto donde correrá la API
EXPOSE 8071

# Comando por defecto: lanzar uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8071"]
