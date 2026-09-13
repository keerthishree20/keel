# Keel. `make install && make test`

PY      ?= .venv/bin/python
VENV_PY ?= python3.12          # NOT python3: that is 3.6 on some machines

.PHONY: help install test bench example dis clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

install: ## create .venv with the test tools (Keel itself has no dependencies)
	$(VENV_PY) -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-dev.txt

test: ## conformance in both engines, the collector, the compiler, the syntax
	$(PY) -m pytest -q

bench: ## the VM against the tree-walker
	$(PY) -m bench.compare --repeat 5

example: ## run the example on both engines
	$(PY) -m keel.cli run examples/closures.keel
	$(PY) -m keel.cli run examples/closures.keel --tree

dis: ## disassemble the example
	$(PY) -m keel.cli dis examples/closures.keel

clean:
	rm -rf .venv .pytest_cache **/__pycache__
