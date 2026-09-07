# syntax=docker/dockerfile:1

# ---- base -------------------------------------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# ---- builder: resolve and install runtime dependencies --------------------
FROM base AS builder
ENV POETRY_VERSION=2.4.3 \
    POETRY_VIRTUALENVS_CREATE=false
RUN pip install "poetry==${POETRY_VERSION}" "poetry-plugin-export"
COPY pyproject.toml poetry.lock README.md ./
# Export the locked runtime deps and install them into the system site-packages.
RUN poetry export --only main --without-hashes -f requirements.txt -o /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# ---- runtime --------------------------------------------------------------
FROM base AS runtime
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY app ./app
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN chmod +x ./docker/entrypoint.sh
# alembic/ and alembic.ini are added to this COPY list in step 2.

EXPOSE 8000
ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
