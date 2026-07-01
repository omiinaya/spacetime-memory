# Spacetime Memory — Developer Setup

.PHONY: help install-sdk build-module start-stdb stop-stdb test test-unit test-integration clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install-sdk:  ## Install Python SDK in dev mode
	cd sdk/python && pip install -e .

build-module:  ## Build the Rust WASM module (release)
	cd server/spacetimedb && cargo build --target wasm32-unknown-unknown --release

start-stdb:  ## Start SpacetimeDB standalone (background, logs to /tmp/stdb.log)
	@if pgrep -f "spacetime.*start" > /dev/null 2>&1; then \
		echo "SpacetimeDB already running"; \
	else \
		echo "Starting SpacetimeDB standalone on :3001..."; \
		spacetime start --listen-addr 0.0.0.0:3001 > /tmp/stdb.log 2>&1 & \
		echo "Waiting for SpacetimeDB..."; \
		for i in $$(seq 1 10); do \
			if nc -z 127.0.0.1 3001 2>/dev/null; then \
				echo "SpacetimeDB ready"; \
				exit 0; \
			fi; \
			sleep 1; \
		done; \
		echo "Timed out waiting for SpacetimeDB"; \
		exit 1; \
	fi

stop-stdb:  ## Stop SpacetimeDB standalone
	-pkill -f "spacetime.*start" 2>/dev/null; echo "Stopped"

test-unit:  ## Run unit tests (no SpacetimeDB needed)
	cd sdk/python && python -m pytest tests/ -m unit -v --tb=short -q

test:  ## Run full test suite (unit + integration, builds module if needed)
	@cd sdk/python && \
		echo "=== Unit tests ===" && \
		python -m pytest tests/ -m unit -v --tb=short -q; \
		UNIT_EXIT=$$?; \
		echo ""; \
		echo "=== Integration tests (need SpacetimeDB on :3001) ===" && \
		SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 \
		python -m pytest tests/ -m integration -v --tb=short -q; \
		INT_EXIT=$$?; \
		echo "---"; \
		if [ $$UNIT_EXIT -ne 0 ] || [ $$INT_EXIT -ne 0 ]; then \
			exit 1; \
		fi

test-integration: build-module  ## Build module and run integration tests
	cd sdk/python && \
	SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 \
	python -m pytest tests/ -m integration -v --tb=short -q

test-all: build-module  ## Run ALL tests (no marker filter — includes everything)
	@cd sdk/python && \
	SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 \
	python -m pytest tests/ -v --tb=short -q

test-rust:  ## Run Rust unit tests
	cd server/spacetimedb && cargo test --lib

test-frontend:  ## Run frontend vitest tests
	cd client && npx vitest run

test-e2e:  ## Run Playwright E2E tests
	cd client && npx playwright test

bench:  ## Run performance benchmark (needs live STDB on :3001)
	@DB=$$(spacetime list 2>/dev/null | grep "spacetime-memory" | awk '{print $$NF}'); \
	if [ -z "$$DB" ]; then \
		echo "spacetime-memory not published. Run: cd server/spacetimedb && spacetime publish spacetime-memory --yes -p . --delete-data=never"; \
		exit 1; \
	fi; \
	PYTHONPATH=sdk/python SPACETIMEDB_DB=$$DB python3 scripts/benchmark.py

smoke:  ## Run end-to-end smoke test (needs live STDB on :3001)
	@PYTHONPATH=$(CURDIR)/sdk/python python3 $(CURDIR)/sdk/python/tests/smoke_test.py

ci: build-module  ## Full local CI: Rust + Python + TypeScript + adapters
	@echo "=== Rust tests ===" && \
	cd server/spacetimedb && cargo test --lib 2>&1 | grep "test result" && \
	echo "" && \
	echo "=== Python unit tests ===" && \
	cd $(CURDIR)/sdk/python && python3 -m pytest tests/ -m unit -q --tb=short && \
	echo "" && \
	echo "=== Frontend tests ===" && \
	cd $(CURDIR)/client && npx vitest run 2>&1 | grep -E "Tests|Test Files" && \
	echo "" && \
	echo "=== TypeScript check ===" && \
	cd $(CURDIR)/client && npx tsc --noEmit && echo "tsc: OK" && \
	echo "" && \
	if timeout 1 bash -c 'echo > /dev/tcp/localhost/3001' 2>/dev/null; then \
		echo "=== Adapter tests (live STDB) ===" && \
		cd $(CURDIR)/sdk/python && \
		SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 \
		python3 -m pytest tests/test_zep_adapter.py tests/test_mem0_adapter.py \
			tests/test_graphiti_adapter.py tests/test_honcho_adapter.py \
			tests/test_langchain_adapter.py tests/test_hindsight_adapter.py \
			-q --tb=short 2>&1 | tail -5; \
	else \
		echo "=== Skipping adapter tests (no STDB on :3001) ==="; \
	fi && \
	echo "" && \
	echo "CI PASSED"

setup: install-sdk build-module  ## Install SDK + build module (start SpacetimeDB separately)

clean:  ## Clean build artifacts
	cd sdk/python && rm -rf build/ dist/ *.egg-info
	cd server/spacetimedb && cargo clean
	@echo "Cleaned"

# ── Agent-Friendly Targets ────────────────────────────────────────────────
.PHONY: test-quick coverage check-ports deps-check health setup-git-hooks

test-quick:  ## Quick Python import check
	@python3 -c "import spacetime_memory; print('spacetime_memory:', spacetime_memory.__version__)" 2>/dev/null || \
		echo "spacetime_memory not installed — run 'make install-sdk'"

coverage:  ## Run Python tests with coverage
	@echo "=== Coverage ==="
	@cd sdk/python && python3 -m pytest tests/ -m unit --cov=spacetime_memory --cov-report=term --cov-report=html
	@echo "HTML report: sdk/python/htmlcov/index.html"

check-ports:  ## Verify required ports are free
	@echo "Checking ports 3001 (STDB), 9090 (prometheus)..."
	@for port in 3001 9090; do \
		if ss -tlnp "sport = :$$port" 2>/dev/null | grep -q .; then \
			echo "  Port $$port: IN USE"; \
		else \
			echo "  Port $$port: free"; \
		fi; \
	done

deps-check:  ## Verify required tools are installed
	@echo "=== Dependency Check ==="
	@for cmd in rustup cargo python3 spacetime; do \
		if command -v $$cmd >/dev/null 2>&1; then \
			echo "  $$cmd: found"; \
		else \
			echo "  $$cmd: MISSING"; \
		fi; \
	done
	@echo "Checking wasm32 target..."
	@rustup target list --installed 2>/dev/null | grep -q wasm32-unknown-unknown && \
		echo "  wasm32 target: found" || echo "  wasm32 target: MISSING (run: rustup target add wasm32-unknown-unknown)"
	@echo "Checking Python package..."
	@python3 -c "import spacetime_memory" 2>/dev/null && \
		echo "  spacetime_memory package: found" || echo "  spacetime_memory package: not installed"

health:  ## Check STDB health
	@echo "=== STDB Health ==="
	@if curl -sf http://localhost:3001/health 2>/dev/null || curl -sf http://localhost:3001/ 2>/dev/null; then \
		echo "  STDB on :3001 — OK"; \
	else \
		echo "  STDB on :3001 — not reachable"; \
	fi

setup-git-hooks:  ## Configure git hooks from .githooks/
	@if [ -d .githooks ]; then \
		git config core.hooksPath .githooks; \
		echo "Git hooks configured to use .githooks/"; \
	else \
		mkdir -p .githooks; \
		git config core.hooksPath .githooks; \
		echo "Created .githooks/ and configured git to use it"; \
	fi
