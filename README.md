# Hostel Management System

FastAPI backend REST API for managing university and private hostels.

![Coverage](https://img.shields.io/badge/Coverage-96%25-brightgreen.svg)
![Services Coverage](https://img.shields.io/badge/Services_Coverage-99%25-brightgreen.svg)
![Python](https://img.shields.io/badge/Python-3.12-blue.svg)

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

# Seed realistic demo data (Hostels, Rooms, Students, Allocations, Invoices, Attendance, Complaints)
uv run python scripts/seed.py --reset

# Run development server
uv run uvicorn app.main:app --reload
```

### Demo Login Credentials
| Role | Email | Password |
|---|---|---|
| Admin | `admin@hostel.example.com` | `AdminPass123` |
| Warden (Boys) | `warden.boys@hostel.example.com` | `WardenPass123` |
| Warden (Girls) | `warden.girls@hostel.example.com` | `WardenPass123` |
| Student (Male) | `student.b001@hostel.example.com` | `StudentPass123` |
| Student (Female) | `student.g001@hostel.example.com` | `StudentPass123` |

Interactive documentation is available at `http://127.0.0.1:8000/docs`.

## Run Tests & Linting
```bash
# Run test suite with strict coverage enforcement and randomized execution
uv run pytest -q -W error --cov=app --cov-fail-under=90 -p randomly

# Run full test suite against PostgreSQL (Docker container)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/hostel_db uv run pytest -q

# Run PostgreSQL-only migration reversibility tests
uv run pytest tests/integration/test_migrations.py -v

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
- [x] Complaints (`/api/v1/complaints`) ✅
- [x] Mess (`/api/v1/hostels/{id}/menu`, `/api/v1/meals/opt-outs`, `/api/v1/meals/headcount`) ✅
- [x] Notices (`/api/v1/notices`, `/api/v1/notices/unread-count`) ✅
- [x] Audit Log (`/api/v1/audit-logs`) ✅
- [x] Reports & Dashboard (`/api/v1/dashboard/summary`, `/api/v1/reports/*`, `/api/v1/students/me/dashboard`) ✅
- [x] Test Hardening & Bug Hunt Sweep (96% Coverage, Permission Matrix, Property Testing, E2E Scenarios, N+1 Query Elimination, Reversible Migrations) ✅
- [x] Security & Performance Hardening (Rate limiting, Account lockout, Refresh token rotation/revocation, Security headers, DB indexes, GZip, Load testing) ✅

## Security

| Feature | Detail |
|---|---|
| Rate Limiting | `5/min` per IP+email on `/auth/login`; `100/min` global default (slowapi) |
| Account Lockout | 5 consecutive failures → 15-minute lockout; auto-unlocks on cooldown |
| Refresh Token Rotation | Every refresh issues new token pair; reuse of rotated token revokes entire family (theft detection) |
| Logout | `POST /api/v1/auth/logout` — revokes token family immediately |
| Security Headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, HSTS in production |
| Secret Key | Must be ≥32 chars and non-default in `production` (enforced at startup) |
| Docs | `/docs` and `/redoc` disabled in production unless `ENABLE_DOCS=true` |
| Body Limit | 5 MB maximum request body enforced by middleware |

### Critical Production Variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | **Must be ≥32 chars, non-default** — rejected on startup otherwise |
| `APP_ENV` | Set to `production` to enable HSTS, disable docs, enforce key validation |
| `ENABLE_DOCS` | Set to `true` to re-enable `/docs`/`/redoc` in production |
| `FAILED_LOGIN_LIMIT` | Max consecutive failed logins before account lockout (default: `5`) |
| `LOCKOUT_DURATION_MINUTES` | Account lockout duration in minutes (default: `15`) |

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
| `MEAL_OPTOUT_CUTOFF_HOURS` | Meal opt-out cancellation cutoff window in hours | `12` |
