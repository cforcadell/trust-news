FROM python:3.11-slim

# Agrupar variables de entorno no crea capas extra, pero mejora la legibilidad
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Crear un usuario y grupo del sistema sin privilegios (UID 1000 por convención)
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copiar requirements y asignar propietario en la misma capa
COPY --chown=appuser:appuser news-handler/requirements.txt .

# Instalar dependencias como root (antes de cambiar de usuario)
# Así evitamos problemas de permisos y evitamos crear un entorno virtual
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código asignando el propietario directamente
# El flag --chown evita tener que hacer un "RUN chown -R", lo cual duplicaría el peso de los archivos en otra capa
COPY --chown=appuser:appuser common ./common
COPY --chown=appuser:appuser news-handler ./news-handler

# Cambiar al usuario sin privilegios
USER appuser

EXPOSE 8072

# Usar el formato exec (array JSON) para el CMD es una mejor práctica
# Permite que la aplicación reciba correctamente las señales del sistema (como SIGTERM para un apagado limpio)
CMD ["uvicorn", "news-handler.main:app", "--host", "0.0.0.0", "--port", "8072"]
