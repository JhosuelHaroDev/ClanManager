FROM python:3.11-slim

# Evita archivos .pyc y fuerza logs en tiempo real para el panel de Railway
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias primero para aprovechar la caché de capas de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el código del backend y las migraciones de Alembic
COPY . .

# Railway inyecta dinámicamente la variable $PORT.
# Antes de arrancar FastAPI, ejecuta las migraciones pendientes en PostgreSQL.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]