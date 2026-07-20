# Savi GPS

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-Alpha-orange.svg)](README.md#project-status)
[![Python](https://img.shields.io/badge/backend-FastAPI%20%7C%20Python%203.12-3776AB.svg)](backend/)
[![Next.js](https://img.shields.io/badge/frontend-Next.js%2014-black.svg)](frontend/)

**Savi GPS** helps teams **understand legacy and multi-repo systems**, generate grounded **wikis**, chat with citation-backed answers, and surface **modernization readiness signals** — then turn those insights into plans and Build workflows.

> **If this project helps you, please ⭐ star the repository.** Stars make it easier for others to discover the work and motivate continued open-source development.

Licensed under the [Apache License 2.0](LICENSE).

---

## Why Savi GPS?

Many enterprises do not ship from a single repository. A product is often an **application** — backend, UI, workers, shared libraries — that must be understood **together**.

Savi GPS is built around that reality:

| Capability | What you get |
|------------|----------------|
| **Wiki for one repo** | Index a GitHub repository → structured wiki (overview, architecture, business logic, API surface, build/deploy), grounded chat & search |
| **Wiki for an application** | Group multiple repos under an Application → composed wiki, **cross-repo service map**, federated chat/search |
| **Analysis** | Blast-radius (“what breaks if I change this?”), domain/ERD-style views, call-graph substrate |
| **Modernization signals** | On-demand readiness assessment (index freshness, documentation, runtime risk, test heuristics, drift) → modernization **plans** and optional handoff to Build |
| **Build (idea → tests)** | Agentic SDLC path with policies/SOPs for greenfield or modernization follow-through |

**Alpha maturity:** great for demos, learning, and early self-hosting. Expect rough edges — see [Known limitations](#known-limitations).

---

## Author & ownership

| Role | Name |
|------|------|
| **Owner & primary contributor** | **Raghuram Madiraju** |
| Project | Savi GPS (Savi AI) |

Community contributions are welcome under Apache-2.0. See [Contributing](#contributing) and [CONTRIBUTING.md](CONTRIBUTING.md).

---

## What’s in this monorepo

```text
savi-gps/
├── backend/          # FastAPI API, indexing, wiki, chat, modernize, policies
├── frontend/         # Next.js 14 App Router UI
├── docs/             # Guides, ADRs, release notes
├── requirements/     # Product / implementation plans
├── LICENSE, NOTICE, CONTRIBUTING.md, SECURITY.md, CHANGELOG.md
└── Makefile          # make check, make help, …
```

One version tag covers **backend + frontend** together.

---

## Backend (`backend/`)

| Item | Detail |
|------|--------|
| Stack | **Python 3.12+**, **FastAPI**, SQLAlchemy, Alembic |
| Default DB | SQLite locally (`gps.db`, gitignored); Postgres (+ optional pgvector) for shared/prod |
| Optional | Neo4j for richer call-graph queries |
| Auth | JWT + multi-tenant RBAC (`tenant_id` kept throughout) |
| Core areas | Intelligence (repos, apps, index, wiki, chat, search, analysis), Modernize (assessments/plans), Build agents, Policies/SOPs |
| Storage | Tenant-scoped artifacts under `backend/storage/tenants/...` (gitignored) |
| Health | `GET /health/live`, `GET /health/ready` |
| API docs | `http://localhost:8000/docs` when the server is running |

```bash
cd backend
python -m venv genv && source genv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY, ANTHROPIC_API_KEY / OPENAI_API_KEY, etc.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Seed **dev-only** users:

```bash
python -m app.scripts.create_default_users
# e.g. admin / admin123  (change before any shared environment)
```

---

## Frontend (`frontend/`)

| Item | Detail |
|------|--------|
| Stack | **Next.js 14**, React, TypeScript, Tailwind |
| App areas | Dashboard, Intelligence (Applications, Repositories, Chat, Search), Modernize (Assessments, Plans), Portfolio Health, Admin (Policies, Wiki Review, Tenant settings) |
| Config | `frontend/.env.local` from `.env.example` (API base URL) |

```bash
cd frontend
npm ci
cp .env.example .env.local   # if needed
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Quick start (full stack)

**Prerequisites:** Python 3.12+, Node.js 20+, optional Docker (Postgres/Neo4j).

```bash
# Terminal 1 — API
cd backend && source genv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2 — UI
cd frontend && npm run dev
```

Optional:

```bash
docker compose up -d postgres neo4j
```

Point `INTELLIGENCE_DATABASE_URL` / `NEO4J_*` in `backend/.env` (see `.env.example`).

**Verify curated CI gate locally:**

```bash
make check    # curated backend tests + frontend production build
make help     # list monorepo commands
```

---

## Suggested first journey

1. Log in (seeded admin on tenant **tenant1** if you used the seed script).  
2. **Connect & index** a repository (Intelligence → Repositories).  
3. Open the repo **wiki** and **Analysis** (blast-radius / domain graph when data exists).  
4. Create an **Application**, attach one or more repos → **Dependencies** (service map) and application wiki/chat.  
5. **Modernize → Assessments** → **Run assessment** (manual by default; optional auto-run in Tenant settings).  
6. Create a modernization **plan** when ready.

Deeper guides:

- [Repo analysis & Applications](docs/guides/repo-analysis-and-applications.md)  
- [Assessments, policies & wiki](docs/guides/assessments-policies-and-wiki.md)  
- [Workflow guide](docs/guides/workflow-guide.md)

---

## Project status & roadmap

| Area | Maturity (Alpha) |
|------|------------------|
| Repo & application wiki / chat / search | Usable |
| Analysis Phases 0–3 (storage, blast-radius, domain graph, service map) | Usable |
| Modernize assessments & plans | Usable (manual Run assessment by default) |
| Build idea → tests | Functional; more hardening planned |
| Auth + tenant isolation | Present; further enterprise hardening planned |
| Portfolio Health | Early |
| Real Jira / Confluence / Harness | Stubs only |

### Release ladder

| Version | Intent |
|---------|--------|
| **`v0.1.0-alpha`** (current) | Public preview monorepo |
| **`v0.2.x-beta`** | Partner-ready hardening of the v1 surface |
| **`v1.0.0`** | Enterprise gate: repos, apps, chat, wiki review, policies/SOPs, Portfolio Health, modernize readiness/plans, Build wizard, analysis 0–3 |
| **Later (v1.1 / v2)** | Portfolio Risk/Cost/Trends, Fleet/Playbooks UI, Analysis Phase 4–5 (sequences, vuln overlays, …), real ALM connectors, durable job queue, chat persistence |

Details: [docs/releases/RELEASE_PLAN.md](docs/releases/RELEASE_PLAN.md) · [CHANGELOG.md](CHANGELOG.md) · [Alpha release notes](docs/releases/v0.1.0-alpha.md) · [Execution plan](requirements/plan/oss-enterprise-release-execution-plan.md)

---

## Known limitations

- **Alpha, not enterprise-ready** — use for demos and careful self-hosting first.  
- Full `pytest` suite is **not** fully green; CI runs a **curated** subset (`make check`).  
- Frontend automated tests are limited (build/typecheck in CI).  
- Indexing uses **in-process** workers (not durable across API restart).  
- Assessment quality depends on a **successful index**; empty/scaffold repos yield thin chat answers.  
- Assessments are **manual by default** (optional auto-run after analysis via Tenant settings).  
- Assessments do **not** yet evaluate against the Policy engine (planned).  
- Wiki section set is largely **fixed** today (tenant “wiki generation policies” planned).  
- SQLite is common locally; prefer **Postgres** for shared environments.  
- Never commit `.env`, `*.db`, or `backend/storage/` tenant data (see `.gitignore`).

Architecture decisions: [docs/architecture/decisions/](docs/architecture/decisions/).  
Security reports: [SECURITY.md](SECURITY.md).

---

## Contributing

Thank you for considering a contribution. Please:

1. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).  
2. Open an **issue** for larger changes before a big PR.  
3. Keep **tenancy** intact (`tenant_id` / isolation) unless an ADR supersedes that.  
4. Prefer small, focused PRs with tests for behavior you change.  
5. Run `make check` before opening a PR.  
6. Do **not** commit secrets, databases, or analysis storage.  
7. By submitting a PR, you license your contribution under **Apache-2.0**.

### Local contribution loop

```bash
# Backend curated tests (also covered by make check)
cd backend && pytest tests/test_tenant_isolation.py \
  tests/test_analysis_storage.py tests/test_blast_radius_service.py \
  tests/test_domain_graph.py tests/test_application_graph_service.py \
  tests/test_wiki_governance.py -q

# Frontend
cd frontend && npm run build
```

**Code of conduct:** Be respectful. Harassment is not tolerated; maintainers may close violating issues/PRs.

Questions and ideas: open a GitHub Discussion or Issue. Feature proposals that touch product scope should reference the [release plan](docs/releases/RELEASE_PLAN.md).

---

## Support the project

If Savi GPS is useful for understanding multi-repo systems, generating wikis, or spotting modernization signals:

- **⭐ Star the repo** — it helps others find the project  
- Open issues for bugs and ideas  
- Submit PRs following [CONTRIBUTING.md](CONTRIBUTING.md)  
- Share feedback with the owner: **Raghuram Madiraju**

---

## License

Copyright 2025–2026 Savi AI, **Raghuram Madiraju**, and contributors.  
Licensed under the Apache License, Version 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
