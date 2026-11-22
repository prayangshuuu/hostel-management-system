#!/usr/bin/env bash
# ==============================================================================
# Container Entrypoint Script for Hostel Management System
# ==============================================================================
set -eo pipefail

# Configure worker concurrency from WORKERS or WEB_CONCURRENCY environment variables
if [ -n "${WORKERS:-}" ]; then
    export WEB_CONCURRENCY="$WORKERS"
fi
export WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"

echo "==> [entrypoint] Container startup initiated (WEB_CONCURRENCY=${WEB_CONCURRENCY})"

# Wait for PostgreSQL database readiness if configured
if [ -n "${DATABASE_URL:-}" ]; then
    echo "==> [entrypoint] Checking PostgreSQL database readiness..."
    python3 - << 'EOF'
import asyncio
import os
import sys
import time
from urllib.parse import urlparse

database_url = os.environ.get("DATABASE_URL", "")
if not database_url.startswith("postgresql"):
    print("[entrypoint] DATABASE_URL does not use PostgreSQL; skipping connection check.")
    sys.exit(0)

# Normalize URL for parser
clean_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
parsed = urlparse(clean_url)
host = parsed.hostname or "127.0.0.1"
port = parsed.port or 5432
user = parsed.username or "postgres"
password = parsed.password or ""
database = parsed.path.lstrip("/") or "postgres"

timeout = int(os.environ.get("DB_WAIT_TIMEOUT", "60"))
start = time.time()

async def wait_for_db():
    import asyncpg
    print(f"[entrypoint] Waiting for database at {host}:{port}/{database} (timeout: {timeout}s)...")
    while True:
        try:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                timeout=3,
            )
            await conn.execute("SELECT 1;")
            await conn.close()
            print("[entrypoint] PostgreSQL is online and accepting connections.")
            return
        except Exception as exc:
            elapsed = int(time.time() - start)
            if elapsed >= timeout:
                print(f"[entrypoint] ERROR: Timed out waiting for PostgreSQL after {elapsed}s: {exc}", file=sys.stderr)
                sys.exit(1)
            time.sleep(1)

asyncio.run(wait_for_db())
EOF

    # Run database migrations
    if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
        echo "==> [entrypoint] Applying database migrations (alembic upgrade head)..."
        alembic upgrade head
        echo "==> [entrypoint] Database migrations applied successfully."
    else
        echo "==> [entrypoint] SKIP_MIGRATIONS=true; skipping database migrations."
    fi
fi

# Fallback default command if none provided
if [ $# -eq 0 ]; then
    set -- uvicorn app.main:app --host 0.0.0.0 --port 8000
fi

echo "==> [entrypoint] Executing application command: $@"
exec "$@"
