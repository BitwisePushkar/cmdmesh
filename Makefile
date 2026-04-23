.PHONY: help install up up-prod down logs logs-backend logs-worker \
        backend backend-prod worker flower cli \
        test test-cov test-signup test-login test-refresh test-reset \
        test-chat test-search test-code \
        lint format check clean docker-clean gen-keys

PYTHON  := python
UV      := uv
COMPOSE := docker compose

help:
	@echo ""
	@echo "  cmdmesh — development commands"
	@echo ""
	@echo "  First-time setup"
	@echo "    make install      Install Python deps via uv"
	@echo "    make gen-keys     Print JWT_SECRET_KEY + TOKEN_ENCRYPTION_KEY"
	@echo "    make up           Start EVERYTHING (Docker)"
	@echo ""
	@echo "  Docker"
	@echo "    make up           Start all services (postgres, redis, mailhog,"
	@echo "                      backend, celery-worker, celery-flower)"
	@echo "    make down         Stop and remove all containers"
	@echo "    make logs         Tail logs from all containers"
	@echo "    make logs-backend Tail backend logs only"
	@echo "    make logs-worker  Tail celery-worker logs only"
	@echo ""
	@echo "  Local run (without Docker — needs Postgres + Redis running)"
	@echo "    make backend      uvicorn dev server on :8000 using .env"
	@echo "    make backend-prod uvicorn dev server on :8000 using .env.prod"
	@echo "    make worker       Celery email worker using .env"
	@echo "    make flower       Celery Flower on :5555"
	@echo ""
	@echo "  Tests  (no Docker needed)"
	@echo "    make test         Full suite"
	@echo "    make test-cov     Full suite + HTML coverage report"
	@echo "    make test-signup  Signup + OTP tests"
	@echo "    make test-login   Login + /me + logout tests"
	@echo "    make test-refresh Token rotation + encryption tests"
	@echo "    make test-reset   Password reset tests"
	@echo "    make test-chat    AI Chat session tests"
	@echo "    make test-search  Web search + AI summary tests"
	@echo "    make test-code    AI Code Assistant tests"
	@echo ""
	@echo "  CLI"
	@echo "    make cli          Run the cmdmesh CLI locally"
	@echo ""
	@echo "  Code quality"
	@echo "    make lint         ruff check"
	@echo "    make format       ruff format"
	@echo "    make check        lint + format check (CI gate)"
	@echo ""
	@echo "  Cleanup"
	@echo "    make clean        Remove local caches and coverage data"
	@echo "    make docker-clean Stop and remove ALL containers, volumes, and local images"
	@echo ""

install:
	$(UV) pip install -e ".[dev]"

gen-keys:
	@echo ""
	@echo "Paste these into your .env  (replace the CHANGE_ME placeholders):"
	@echo ""
	@printf "JWT_SECRET_KEY="
	@$(PYTHON) -c "import secrets; print(secrets.token_hex(64))"
	@printf "TOKEN_ENCRYPTION_KEY="
	@$(PYTHON) -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
	@echo ""

up:
	$(COMPOSE) up --build -d
	@$(MAKE) print-urls

up-prod:
	$(COMPOSE) --env-file .env.prod up --build -d
	@$(MAKE) print-urls

print-urls:
	@echo ""
	@echo "  All services started:"
	@echo "    Backend API   → http://localhost:8000"
	@echo "    Swagger UI    → http://localhost:8000/docs"
	@echo "    Mailhog UI    → http://localhost:8025   (view emails)"
	@echo "    Flower        → http://localhost:5555   (login: admin / admin)"
	@echo "    Postgres      → localhost:5432"
	@echo "    Redis         → localhost:6379"
	@echo ""
	@echo "  Tip: run 'make logs' to watch all output"
	@echo ""

down:
	$(COMPOSE) down

docker-clean:
	$(COMPOSE) down -v --rmi local --remove-orphans

logs:
	$(COMPOSE) logs -f

logs-backend:
	$(COMPOSE) logs -f backend

logs-worker:
	$(COMPOSE) logs -f celery-worker

backend:
	$(UV) run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

backend-prod:
	ENV_FILE=.env.prod $(UV) run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

worker:
	$(UV) run celery -A backend.worker worker \
	  --loglevel=info \
	  --concurrency=4 \
	  --queues=email,default \
	  --hostname=worker@%h

flower:
	$(UV) run celery -A backend.worker flower \
	  --port=5555 \
	  --basic_auth=admin:admin

cli:
	$(UV) run cmdmesh

test:
	$(UV) run pytest tests/ -v --tb=short

test-cov:
	$(UV) run pytest tests/ -v --tb=short \
	  --cov=backend --cov=cli \
	  --cov-report=term-missing \
	  --cov-report=html
	@echo ""
	@echo "  Coverage report → htmlcov/index.html"
	@echo ""

test-signup:
	$(UV) run pytest tests/test_signup.py -v --tb=short

test-login:
	$(UV) run pytest tests/test_login.py -v --tb=short

test-refresh:
	$(UV) run pytest tests/test_refresh.py -v --tb=short

test-reset:
	$(UV) run pytest tests/test_reset_password.py -v --tb=short

test-chat:
	$(UV) run pytest tests/test_chat.py -v --tb=short

test-search:
	$(UV) run pytest tests/test_search.py -v --tb=short

test-code:
	$(UV) run pytest tests/test_code.py -v --tb=short

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .

check:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov .pytest_cache
	@echo "Cleaned."