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

# Expone el puerto 8080
EXPOSE 8080

# Comando para correr FastAPI con Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
