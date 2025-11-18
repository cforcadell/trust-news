FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1


WORKDIR /app

COPY news-chain/requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt


# Copia la carpeta 'common' y todo su contenido
COPY common /app/common

# Copia la carpeta 'news' y todo su contenido
COPY news-chain /app/news-chain

EXPOSE 8073

# Ejecutar script de creación de topics antes de arrancar FastAPI
#CMD python init_kafka_topics.py && uvicorn main:app --host 0.0.0.0 --port 8072
CMD uvicorn news-chain.main:app --host 0.0.0.0 --port 8073
