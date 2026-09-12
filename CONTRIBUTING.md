# Contributing to CloudSite

Thank you for your interest in contributing to CloudSite. This guide covers the development setup, project structure, coding conventions, and the different ways you can contribute.

## Development environment

### Requirements

- Python 3.12+
- Node.js 20+ (for web frontend changes)
- Git

### Setup

```bash
git clone https://github.com/nathanxiangang-web/CloudSite.git
cd CloudSite
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows
pip install -r apps/api/requirements.txt
```

### Run tests

```bash
cd apps/api
python -m pytest -q --tb=short
```

All tests use temporary SQLite databases and run in seconds. No external services are required.

### Run the API locally

```bash
cd apps/api
uvicorn cloudsite.main:app --reload
```

The API is available at `http://localhost:8000`. Use the setup token flow to configure an AList instance.

## Project structure

```
apps/
  api/                    FastAPI backend
    cloudsite/
      main.py             Application entry, router registration
      models.py           SQLAlchemy ORM models (StateBase / IndexBase)
      migrations.py       Schema version + migration chain
      database.py         Engine setup, init_databases()
      services/           Pure application services (no FastAPI imports)
      routers/            HTTP route handlers
        admin/            Admin-only routes (protected by middleware)
      *_schemas.py        Pydantic request/response schemas
    tests/                pytest test suite
  web/                    Next.js frontend
docs/                     User-facing documentation
scripts/                  Operational scripts (backup, checks, etc.)
开发文档/                  Product development handbook (Chinese)
```

## Coding conventions

### Services

- Pure functions, no FastAPI imports.
- Return `Result` dataclass or raise domain exceptions.
- Transactions are managed by the caller (service receives a session).
- Use lazy imports for service modules to avoid circular dependencies.

### Models

- All ORM models live in `models.py`.
- IDs are generated as `prefix + secrets.token_hex(16)` (e.g., `ct_` for quality todos).
- Tables use `CREATE TABLE IF NOT EXISTS` in migrations.

### Migrations

- Explicit `CURRENT_SCHEMA_VERSION` constant in `migrations.py`.
- Each migration is a `Migration(from_version, to_version, upgrade)` where `upgrade` is idempotent.
- After adding a migration, update `CURRENT_SCHEMA_VERSION` and fix all test files that hard-assert the version number.

### Routes

- Admin routes go in `routers/admin/` and are auto-protected by `admin_session_middleware`.
- Register new routers in `main.py` following the existing pattern.

### Tests

- Service tests: `tmp_path` SQLite + `async_sessionmaker`.
- Route tests: `httpx.ASGITransport` + monkeypatch `main.StateSession` / `IndexSession` + admin cookies.
- No mocking of the database — tests use real SQLite.

## Ways to contribute

### Code

Bug fixes and feature implementations following the conventions above. Check the [roadmap](docs/ROADMAP.md) for planned work.

### Templates

Site presentation templates, email notification templates, and collection layout templates. These live under `apps/web/` and `apps/api/cloudsite/` respectively.

### Translations

UI strings in `apps/web/` are ready for i18n. Contribute language files following the existing locale structure.

### Parse rules

Content detection and organization rules in `apps/api/cloudsite/services/`. Each rule set defines how files are categorized into content types (software, tutorial, image, video, document, etc.).

### Provider compatibility fixtures

Test fixtures for different AList storage provider configurations. These help ensure CloudSite works across diverse backend setups.

### API examples

Example scripts and documentation for the public API. Contribute to `docs/api-examples/` with `curl` or Python `httpx` examples.

## Pull request process

1. Fork the repository and create a branch from `main`.
2. Write tests for your changes.
3. Ensure `python -m pytest -q` passes with no failures.
4. If you added a schema migration, update all test assertions that hard-code the version number.
5. Open a pull request using the PR template.

## License

CloudSite is MIT licensed. By contributing, you agree that your contributions will be licensed under the same terms.