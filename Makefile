# Savi GPS monorepo helpers
# Usage: make help

.PHONY: help install backend-install frontend-install backend-dev frontend-dev \
	test-backend test-frontend test-curated build-frontend compose-up compose-down \
	seed check

help:
	@echo "Savi GPS monorepo"
	@echo "  make install          Install backend + frontend deps"
	@echo "  make backend-dev      Run API on :8000"
	@echo "  make frontend-dev     Run UI on :3000"
	@echo "  make test-curated     Alpha CI backend suite"
	@echo "  make build-frontend   Production Next.js build"
	@echo "  make compose-up       Optional Postgres + Neo4j"
	@echo "  make seed             Create default local users"
	@echo "  make check            Curated tests + frontend build"

install: backend-install frontend-install

backend-install:
	cd backend && python -m venv genv && . genv/bin/activate && pip install -r requirements.txt

frontend-install:
	cd frontend && npm ci

backend-dev:
	cd backend && . genv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend-dev:
	cd frontend && npm run dev

test-curated:
	cd backend && . genv/bin/activate && pytest -q \
		tests/test_tenant_isolation.py \
		tests/test_analysis_storage.py \
		tests/test_blast_radius_service.py \
		tests/test_domain_graph.py \
		tests/test_application_graph_service.py \
		tests/test_wiki_governance.py

test-backend:
	cd backend && . genv/bin/activate && pytest -q

test-frontend:
	cd frontend && npm run build

build-frontend: test-frontend

compose-up:
	docker compose up -d postgres neo4j

compose-down:
	docker compose down

seed:
	cd backend && . genv/bin/activate && python -m app.scripts.create_default_users

check: test-curated build-frontend
	@echo "OK — curated gate passed"
