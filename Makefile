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

bench:  ## Run performance benchmark (needs live STDB + embedder)
	@if [ -z "$$SPACETIMEDB_DB" ]; then \
		echo "Set SPACETIMEDB_DB=<identity> first"; \
		exit 1; \
	fi
	PYTHONPATH=sdk/python python3 sdk/python/scripts/quick-bench.py

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
