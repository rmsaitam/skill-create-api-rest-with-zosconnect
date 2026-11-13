PYTEST := pytest==9.2.0
PYTEST_COV := pytest-cov==7.1.0
PYYAML := PyYAML==6.0.2
BANDIT := bandit==1.9.4

.PHONY: setup test coverage validate security check

setup:
	uv venv
	uv pip install $(PYTEST) $(PYTEST_COV) $(PYYAML)

test:
	uv run --with $(PYTEST) --with $(PYTEST_COV) --with $(PYYAML) pytest -q

coverage:
	uv run --with $(PYTEST) --with $(PYTEST_COV) --with $(PYYAML) pytest --cov-branch --cov=scripts --cov=skills/cobol-openapi-generator/scripts --cov-report=term-missing --cov-fail-under=80

validate:
	python3 scripts/validate_plugin.py .

security:
	uvx $(BANDIT) -r skills/cobol-openapi-generator/scripts scripts -ll

check: coverage validate security
