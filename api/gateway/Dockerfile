# Imagen base oficial de Python
FROM python:3.11-slim

# 1. Crear un usuario de sistema sin privilegios de root (llamado 'appuser')
RUN useradd -m -r appuser 

# Establecer el directorio de trabajo
WORKDIR /app

# 2. Copiar SOLO requisitos primero (Mantiene el caché de dependencias intacto)
COPY gateway/requirements.txt .

# 3. Instalar dependencias 
# (Se ejecuta como root para instalarlas globalmente; 'appuser' podrá leerlas sin problema)
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copiar el código fuente y transferir la propiedad al usuario no-root en un solo paso
COPY --chown=appuser:appuser common ./common
COPY --chown=appuser:appuser gateway ./gateway

# 5. Cambiar la ejecución al usuario sin privilegios
USER appuser

# Exponer el puerto donde correrá la API
EXPOSE 8500

# Comando por defecto: lanzar uvicorn
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8500"]
