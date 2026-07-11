FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 1000 appuser
WORKDIR /app

COPY --chown=appuser:appuser evidence-search/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser common ./common
COPY --chown=appuser:appuser evidence-search/ ./evidence-search/

USER appuser
EXPOSE 8074
CMD ["uvicorn", "evidence-search.main:app", "--host", "0.0.0.0", "--port", "8074"]
