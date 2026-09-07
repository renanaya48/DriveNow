#!/bin/sh
set -e

# Run DB migrations before starting the app. The alembic setup is added in step 2;
# until then this is skipped gracefully so the skeleton image still boots.
if [ -f "alembic.ini" ]; then
  echo "[entrypoint] Running database migrations (alembic upgrade head)..."
  alembic upgrade head
else
  echo "[entrypoint] No alembic.ini yet - skipping migrations."
fi

echo "[entrypoint] Starting: $*"
exec "$@"
