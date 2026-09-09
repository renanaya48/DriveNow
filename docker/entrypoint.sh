#!/bin/sh
set -e

# Only the `api` service uses this entrypoint (the `consumer` overrides it).
# Bring the schema up to date once, then hand off to the CMD (uvicorn).
echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
