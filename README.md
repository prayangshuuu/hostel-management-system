# Hostel Management System

FastAPI backend REST API for managing university and private hostels.

## Tech Stack
- Python 3.12
- FastAPI
- Pydantic v2 & Pydantic Settings
- SQLAlchemy 2.0 (async) & Alembic
- PostgreSQL 16 & asyncpg
- Pytest, Ruff, Mypy

## Quick Start
```bash
# Start PostgreSQL database
docker compose up -d db

# Install dependencies
uv sync

# Run database migrations
uv run alembic upgrade head

# Create first admin user
uv run python scripts/create_admin.py --email admin@example.com --password AdminPassword123 --name "System Admin"

# Run development server
uv run uvicorn app.main:app --reload
```

Interactive documentation is available at `http://127.0.0.1:8000/docs`.

## Run Tests & Linting
```bash
# Run test suite with coverage
uv run pytest -q --cov=app

# Run PostgreSQL-only tests (requires Docker Postgres)
uv run pytest -m postgres

# Run linter and formatter
uv run ruff check . --fix && uv run ruff format .

# Run type checker
uv run mypy app
```

## Modules
- [x] Core infra (Settings, DB session, Alembic, Unified Errors, Structured Logging) ✅
- [x] Health Check (`/api/v1/health`) ✅
- [x] Authentication & Users (`/api/v1/auth`, `/api/v1/users`) ✅
- [x] Hostels & Blocks (`/api/v1/hostels`, `/api/v1/blocks`) ✅
- [x] Rooms & Beds (`/api/v1/rooms`, `/api/v1/blocks/{id}/rooms`) ✅
- [x] Student Profiles (`/api/v1/students`, `/api/v1/students/me`) ✅
- [x] Allocations (`/api/v1/allocations`, `/api/v1/rooms/{id}/occupants`) ✅
- [x] Billing (/api/v1/fee-structures, /api/v1/invoices, /api/v1/payments) ✅
- [x] Attendance, Leave, Visitors (`/api/v1/attendance`, `/api/v1/leaves`, `/api/v1/visitors`) ✅
- [ ] Complaints
- [ ] Mess / Meal Plans
- [ ] Notices
- [ ] Audit Logs & Reports

## Environment Variables
| Variable | Description | Default |
|---|---|---|
| `APP_NAME` | Application name for OpenAPI schema | `Hostel Management System` |
| `APP_VERSION` | Application version | `0.1.0` |
| `APP_ENV` | Application environment (`development`, `staging`, `production`) | `development` |
| `DEBUG` | Enable SQLAlchemy debug query logging | `false` |
| `DATABASE_URL` | PostgreSQL async connection URL | `postgresql+asyncpg://postgres:postgres@localhost:5432/hostel_db` |
| `SECRET_KEY` | Secret key for JWT token signing | `insecure-dev-secret-key-change-in-production` |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime in minutes | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime in days | `7` |
| `CORS_ORIGINS` | Allowed CORS origins (JSON array or comma-separated) | `["*"]` |
| `LOG_LEVEL` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) | `INFO` |
| `VISIT_START` | Daily hostel visiting hours start window (`HH:MM`) | `08:00` |
| `VISIT_END` | Daily hostel visiting hours end window (`HH:MM`) | `20:00` |
