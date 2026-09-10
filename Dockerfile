FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential libpq-dev libjpeg62-turbo-dev zlib1g-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/media /data/backups /app/logs /app/data \
 && DJANGO_SECRET_KEY=build-only DJANGO_DEBUG=1 python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 app \
 && chown -R app:app /app /data
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz/ || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--threads", "4", \
     "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
