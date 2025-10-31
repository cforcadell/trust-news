FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1


WORKDIR /app

# Copiar requisitos primero (para aprovechar caché)
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8072

# Ejecutar script de creación de topics antes de arrancar FastAPI
#CMD python init_kafka_topics.py && uvicorn main:app --host 0.0.0.0 --port 8072
CMD uvicorn main:app --host 0.0.0.0 --port 8072
