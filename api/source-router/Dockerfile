FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 1000 appuser
WORKDIR /app
COPY --chown=appuser:appuser source-router/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser common ./common
COPY --chown=appuser:appuser source-router ./source-router
USER appuser
EXPOSE 8075
CMD ["uvicorn", "source-router.main:app", "--host", "0.0.0.0", "--port", "8075"]
