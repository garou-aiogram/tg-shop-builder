FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Права файлов на хосте могут быть любыми (scp с Windows, umask 077 и т.п.),
# а процесс работает не от root — нормализуем: всё читаемо, каталоги проходимы.
RUN chmod -R a+rX /app && mkdir -p /app/media && useradd --system --uid 10001 app && chown -R app /app/media
USER app

EXPOSE 8000
# Миграции применяются при каждом старте (идемпотентно), затем API + боты
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
