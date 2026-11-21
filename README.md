# Hostel Management System

FastAPI backend REST API for managing university and private hostels.

## Tech Stack
- Python 3.12
- FastAPI
- Pydantic v2 & Pydantic Settings
- SQLAlchemy 2.0 (async) & Alembic
- PostgreSQL & asyncpg
- Pytest, Ruff, Mypy

## Quick Start
```bash
# Install dependencies
uv sync

# Run development server
uv run uvicorn app.main:app --reload
```

Interactive documentation is available at `http://127.0.0.1:8000/docs`.

## Run Tests & Linting
```bash
# Run test suite with coverage
uv run pytest -q --cov=app

# Run linter and formatter
uv run ruff check . --fix && uv run ruff format .

# Run type checker
uv run mypy app
```

## Modules
- [x] Health Check (`/api/v1/health`)
- [ ] Authentication & Users
- [ ] Hostels & Blocks
- [ ] Rooms & Beds
- [ ] Student Profiles
- [ ] Allocations
- [ ] Fee Structures & Invoices
- [ ] Payments
- [ ] Attendance
- [ ] Leave Requests
- [ ] Visitors
- [ ] Complaints
- [ ] Mess / Meal Plans
- [ ] Notices
- [ ] Audit Logs & Reports

## Environment Variables
| Variable | Description | Default |
|---|---|---|
| `APP_ENV` | Application environment (`development`, `staging`, `production`) | `development` |
| `APP_NAME` | Application name for OpenAPI schema | `Hostel Management System` |
| `APP_VERSION` | Application version | `0.1.0` |
