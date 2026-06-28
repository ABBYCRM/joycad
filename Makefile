# JoyCAD Makefile
.PHONY: install dev test test-mvp example run demo serve smoke clean

PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip

install:
	$(PY) -m venv $(VENV)
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev,fcl]"

test:
	$(BIN)/python -m pytest tests/ -q --no-header -p no:cacheprovider

test-mvp:
	$(BIN)/python -m pytest tests/test_mvp.py -q --no-header -p no:cacheprovider

example:
	$(BIN)/python examples/bracket/run_example.py

run:
	$(BIN)/python -m orchestrator.cli run --intent "$(INTENT)" --out $(OUT)

demo:
	$(BIN)/python -m orchestrator.cli demo

serve:
	$(BIN)/python -m orchestrator.cli serve --port 8765

smoke:
	$(BIN)/python scripts/smoke_test_streamlit.py

clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
