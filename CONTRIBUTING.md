# Contributing to Savi GPS

Thanks for your interest in contributing.

**Owner & primary contributor:** Raghuram Madiraju  
**License:** [Apache License 2.0](LICENSE)  
**Maturity:** Alpha

If the project helps you, please **star the repository** — it helps visibility and sustains the work.

## Before you start

1. Read the [README](README.md) (product overview, limitations, roadmap) and [SECURITY](SECURITY.md).
2. Open an **issue** for larger or architectural changes before investing significant time.
3. Keep **tenancy** intact — do not remove `tenant_id` / multi-tenant isolation unless an ADR explicitly supersedes that decision ([ADR 0001](docs/architecture/decisions/0001-internal-enterprise-platform.md) and related).
4. Prefer changes that match the [release plan](docs/releases/RELEASE_PLAN.md) scope for the current maturity (Alpha → Beta → v1).

## Ways to contribute

- Bug reports with repro steps (backend API path, frontend route, logs)
- Documentation fixes and clearer guides under `docs/`
- Tests for tenant isolation, analysis, wiki governance, modernize assessment
- Small UI/UX polish that does not expand Alpha scope into Coming Soon features
- Ideas via Issues (label proposals clearly: `bug`, `enhancement`, `docs`)

## Development setup

```bash
# Backend
cd backend
python -m venv genv
source genv/bin/activate   # Windows: genv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # set SECRET_KEY and LLM keys
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm ci
cp .env.example .env.local # if present
npm run dev
```

Optional: `docker compose up -d postgres neo4j` for Intelligence / graph extras.

## Seed users (local only)

Default seed passwords are **development-only**. Change them before any shared environment.

```bash
cd backend && python -m app.scripts.create_default_users
```

See `backend/app/scripts/create_default_users.py`.

## Pull requests

- Keep changes focused; prefer small PRs.
- Add or update tests for behavior you change.
- Update docs when you change user-facing behavior (README / `docs/guides/`).
- Run the curated gate before opening a PR:

```bash
make check
# or manually:
cd backend
pytest tests/test_tenant_isolation.py \
  tests/test_analysis_storage.py \
  tests/test_blast_radius_service.py \
  tests/test_domain_graph.py \
  tests/test_application_graph_service.py \
  tests/test_wiki_governance.py -q

cd ../frontend
npm run build
```

### Do not commit

- `.env`, `.env.local`, API keys
- `*.db`, `backend/storage/` tenant artifacts
- `node_modules/`, `.next/`, `genv/`, `gpsenv/`
- Local junk (`gps-v1/`, `completed_tasks/`, etc.)

By submitting a PR, you agree that your contribution is licensed under **Apache-2.0**.

## Code of conduct

Be respectful. Harassment or abusive behavior is not tolerated. Maintainers may close issues/PRs that violate this baseline.

## Questions

Open a GitHub Issue. For security-sensitive reports, follow [SECURITY.md](SECURITY.md) — do not file public issues for vulnerabilities.
