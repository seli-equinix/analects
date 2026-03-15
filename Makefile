# CCA Test Runner
#
# Interactive dashboard for running, monitoring, and tracking CCA tests.
# Each test runs in its own GitLab pipeline with isolated Phoenix tracing.
#
# Usage:
#   make dashboard                     Interactive test dashboard (recommended)
#   make test NAME=eva-code-trace      Run one test (with live output)
#   make test NAME=all-coder           Run all coder tests
#   make test NAME=all                 Run everything
#   make status                        Show recent results
#   make history NAME=eva-code-trace   Show run history for one test
#   make logs NAME=eva-code-trace      Show logs from last run
#   make list                          Available test names
#   make health                        Check CCA/vLLM/Phoenix health
#   make push                          Push to GitLab
#   make build                         Rebuild test Docker image
#   make local NAME=eva-code-trace     Run test locally (no CI)
#   make phoenix                       Open Phoenix UI

.PHONY: test status logs list health push build local phoenix retry cancel dashboard history

CI := python3 scripts/ci.py
DASH := python3 scripts/dashboard.py

# GitLab remote for the cca-tests project
GITLAB_REMOTE := http://root:Loveme-sex64@192.168.4.204:8929/root/cca-tests.git

# ── Dashboard (primary interface) ──

dashboard:
	@$(DASH)

history:
	@test -n "$(NAME)" || { echo "Usage: make history NAME=<test-name>"; exit 1; }
	@$(DASH) history $(NAME)

# ── Test execution ──

test:
	@test -n "$(NAME)" || { echo "Usage: make test NAME=<test-name>"; echo ""; $(CI) list; exit 1; }
	@$(CI) run $(NAME)

status:
	@$(CI) status

logs:
	@test -n "$(NAME)" || { echo "Usage: make logs NAME=<test-name>"; exit 1; }
	@$(CI) logs $(NAME)

list:
	@$(CI) list

retry:
	@test -n "$(ID)" || { echo "Usage: make retry ID=<pipeline-id>"; exit 1; }
	@$(CI) retry $(ID)

cancel:
	@test -n "$(ID)" || { echo "Usage: make cancel ID=<pipeline-id>"; exit 1; }
	@$(CI) cancel $(ID)

# ── Infrastructure ──

health:
	@echo "=== CCA Server (Spark1:8500) ==="
	@curl -sf --max-time 10 http://192.168.4.205:8500/health | python3 -m json.tool || echo "UNREACHABLE"
	@echo ""
	@echo "=== vLLM Server (Spark2:8000) ==="
	@curl -sf --max-time 10 http://192.168.4.208:8000/health && echo "OK" || echo "UNREACHABLE"
	@echo ""
	@echo "=== Phoenix (node5:6006) ==="
	@curl -sf --max-time 5 http://192.168.4.204:6006/ > /dev/null && echo "OK" || echo "UNREACHABLE"

phoenix:
	@echo "Opening Phoenix: http://192.168.4.204:6006"
	@xdg-open http://192.168.4.204:6006 2>/dev/null || echo "Open in browser: http://192.168.4.204:6006"

build:
	@$(CI) run build

# ── Git operations ──

push:
	@echo "Pushing to GitLab..."
	@git push $(GITLAB_REMOTE) HEAD:main 2>&1 | tail -3
	@echo ""
	@echo "Done. Run 'make dashboard' to see tests."

# ── Local execution (bypass CI, run directly on node5) ──

local:
	@test -n "$(NAME)" || { echo "Usage: make local NAME=<test-name>"; exit 1; }
	@echo "Running locally (no CI): $(NAME)"
	@python -m pytest tests/ -k "$(NAME)" -v --tb=short --with-judge
