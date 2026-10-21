.PHONY: help sync test lint typecheck check run build release wheel clean

PYTHON ?= uv run

# GOOS-style target OS: override with GOOS=windows for cross artifact naming.
# Falls back to the host OS (mingw/msys/cygwin shells are treated as windows).
GOOS ?= $(shell uname -s | tr '[:upper:]' '[:lower:]' | sed 's/^mingw.*/windows/;s/^msys.*/windows/;s/^cygwin.*/windows/')
ifeq ($(GOOS),windows)
EXE := .exe
else
EXE :=
endif

PYINSTALLER_FLAGS ?= --onefile --name tether$(EXE) --paths src
VERSION ?= $(shell grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')
PLATFORM ?= $(GOOS)-$(shell uname -m)

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

sync:  ## Sync all dependencies (incl. extras and dev tools)
	uv sync --all-extras

test:  ## Run tests
	$(PYTHON) pytest

lint:  ## Ruff check
	$(PYTHON) ruff check .

typecheck:  ## Mypy type check
	$(PYTHON) mypy src

check: lint typecheck test  ## Run all checks (lint + typecheck + test)

run:  ## Run tether locally (Python entry point)
	$(PYTHON) tether --config config.yaml

run-bin:  ## Run the built binary from dist/tether$(EXE)
	./dist/tether$(EXE) --config config.yaml

build:  ## Build standalone binary into dist/tether$(EXE)
	$(PYTHON) pyinstaller $(PYINSTALLER_FLAGS) entry.py

release: check build  ## Run checks, build binary and bundle versioned release tarball
	@mkdir -p dist
	cp config.example.yaml dist/
	tar -czf dist/tether-$(VERSION)-$(PLATFORM).tar.gz -C dist tether$(EXE) config.example.yaml
	rm dist/config.example.yaml
	@echo "==> dist/tether-$(VERSION)-$(PLATFORM).tar.gz"

wheel:  ## Build Python wheel + sdist into dist/
	uv build

clean:  ## Remove build artifacts
	rm -rf build dist tether.spec
