FROM python:3.11-slim

# Variables de entorno agrupadas
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 1. Crear usuario de sistema (Capa 1)
RUN useradd -m -u 1000 appuser

WORKDIR /app

# 2. Copiar requirements y asignar permisos (Capa 2)
COPY --chown=appuser:appuser validate-asertions/requirements.txt .

# 3. Instalar dependencias (Capa 3)
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copiar directorios manteniendo estructura (Capa 4)
# Al usar el punto final (.) como destino, Docker copiará las carpetas
# 'common' y 'validate-asertions' dentro de /app/ manteniendo sus nombres.
COPY --chown=appuser:appuser common/ ./common/
COPY --chown=appuser:appuser validate-asertions/ ./validate-asertions/

# Usuario de ejecución
USER appuser

EXPOSE 8070

# Formato exec para mejor manejo de procesos
CMD ["uvicorn", "validate-asertions.main:app", "--host", "0.0.0.0", "--port", "8070"]