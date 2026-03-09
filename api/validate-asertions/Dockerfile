# Imagen base oficial de Python
FROM python:3.11-slim

# Crear directorio de la aplicación
WORKDIR /app

# Copiar requisitos primero (para aprovechar caché)
COPY validate-asertions/requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
#COPY . .

# Copia la carpeta 'common' y todo su contenido
COPY common /app/common

# Copia la carpeta 'news' y todo su contenido
COPY validate-asertions /app/validate-asertions

# Exponer el puerto donde correrá la API
EXPOSE 8070

# Comando por defecto: lanzar uvicorn
CMD ["uvicorn", "validate-asertions.main:app", "--host", "0.0.0.0", "--port", "8070"]
