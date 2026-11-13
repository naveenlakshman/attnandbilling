FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    META_STAGING_ENABLED=false

WORKDIR /app

COPY staging/meta_lead_receiver/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && groupadd --system appuser \
    && useradd --system --gid appuser --no-create-home appuser

COPY --chown=appuser:appuser staging /app/staging

USER appuser
EXPOSE 8080

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 30 staging.meta_lead_receiver.wsgi:app"]
