# Contributing to CloudSite

Thank you for your interest in contributing to CloudSite. This guide covers the supported development setup, repository layout, quality gates and pull request expectations.

## Development environment

### Requirements

- Python 3.12+
- Node.js 24+
- pnpm 10.15+
- Git
- Docker Engine + Docker Compose plugin for container and integration checks

### Backend setup

```bash
git clone https://github.com/nathanxiangang-web/CloudSite.git
cd CloudSite/apps/api
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate  # Windows
pip install -e ".[test]"
pytest
```

The backend tests use temporary databases and do not require a production AList instance.

### Frontend setup

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run lint
pnpm run test
pnpm run build
```

### Development stack

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

The development Compose file exposes Web on port `3000` and API on port `8000`.

## Repository layout

```text
apps/
  api/                    FastAPI backend and backend tests
  web/                    Next.js frontend and frontend tests
docs/                     Public user, operator and architecture documentation
scripts/                  Release, backup, recovery and repository checks
.github/                   CI, issue and pull request templates
```

Private product plans, AI-agent scratch files, local editor/tool settings and work-in-progress development notes are intentionally not part of the public repository.

## Engineering conventions

### Backend

- Keep HTTP concerns in routers and reusable business logic in services or focused domain modules.
- Keep transaction ownership explicit; do not hide commits inside unrelated helpers.
- New provider-specific behavior should go through provider capabilities/adapters instead of name checks scattered through business code.
- Preserve stable resource IDs and compatibility contracts unless a documented migration exists.
- Avoid expanding already-large shared modules when a focused module boundary is available.

### Migrations

- Schema changes must be explicit, deterministic and safe to run during upgrades.
- Migration tests must cover both fresh initialization and upgrade paths where applicable.
- Never modify production data formats without a recovery or rollback story.

### Routes and security

- Admin routes belong under the protected admin routing boundary.
- State-changing routes must preserve existing authentication and origin/CSRF protections.
- Never commit credentials, tokens, `.env` files, databases, logs or production backups.

### Tests

Changes should include the smallest relevant regression test. Depending on scope, CI may run:

- backend pytest suite;
- frontend typecheck, lint, tests and production build;
- Docker Compose validation and smoke tests;
- dependency audits;
- version consistency checks;
- backup/restore hardening checks.

## Pull request process

1. Fork the repository and create a focused branch from `main`.
2. Keep each pull request limited to one coherent change.
3. Add or update tests when behavior changes.
4. Update public documentation when user-visible behavior changes.
5. Run the relevant local checks before opening the pull request.
6. Use the repository pull request template and describe migration or compatibility impact when applicable.

## Public documentation policy

Public documentation should help users, operators and contributors use or maintain released code. Internal product blueprints, unpublished architecture drafts and temporary agent context should stay outside the repository.

## License

CloudSite is released under the MIT License. By contributing, you agree that your contribution will be licensed under the same terms.
