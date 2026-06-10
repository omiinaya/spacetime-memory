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

setup: install-sdk build-module  ## Install SDK + build module (start SpacetimeDB separately)

clean:  ## Clean build artifacts
	cd sdk/python && rm -rf build/ dist/ *.egg-info
	cd server/spacetimedb && cargo clean
	@echo "Cleaned"
