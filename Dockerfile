# syntax=docker/dockerfile:1

# ---- base -------------------------------------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# ---- builder: resolve runtime deps into an isolated virtualenv -----------
FROM base AS builder
ENV POETRY_VERSION=2.4.3
RUN pip install "poetry==${POETRY_VERSION}" "poetry-plugin-export"
COPY pyproject.toml poetry.lock README.md ./
# Export the locked runtime deps and install them into /opt/venv - Poetry and
# the export plugin stay in this stage and never reach the runtime image.
RUN poetry export --only main --without-hashes -f requirements.txt -o /tmp/requirements.txt \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# ---- runtime: just the venv + app code ----------------------------------
FROM base AS runtime
LABEL org.opencontainers.image.source="https://github.com/renanaya48/DriveNow" \
      org.opencontainers.image.description="DriveNow vehicle-management API"

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN chmod +x ./docker/entrypoint.sh

# Run as an unprivileged user. /app/logs is created and owned here so a named
# volume mounted there is writable without the usual bind-mount UID friction.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# stdlib only - no curl/wget in slim. urlopen raises (non-zero exit) on failure.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"]

ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
