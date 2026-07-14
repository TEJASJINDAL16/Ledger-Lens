PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest

.PHONY: help data profile bronze pipeline test dashboard all clean

help: ## Show all available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

data: ## Generate synthetic data (clean + corrupt)
	@echo "Generating Phase 1 data..."
	$(PYTHON) -m src.generate.make_clean
	$(PYTHON) -m src.generate.corrupt

profile: ## Generate Phase 2 data profile
	@echo "Generating Phase 2 data profile..."
	$(PYTHON) -m src.profile_data

bronze: ## Run Phase 2 Bronze gate
	@echo "Running Phase 2 Bronze gate..."
	$(PYTHON) -m src.run_bronze

silver: ## Run Phase 3-5 Silver cleaning and resolution
	@echo "Running Phase 3-5 Silver cleaning..."
	$(PYTHON) -m src.run_silver

gold: ## Run Phase 6 Warehouse load
	@echo "Running Phase 6 Gold warehouse load..."
	$(PYTHON) -m src.load_warehouse

scorecard: ## Generate Phase 7 Scorecard
	@echo "Generating Phase 7 Scorecard..."
	$(PYTHON) -m src.scorecard

benchmark: ## Run Phase 7 Polars benchmark
	@echo "Running Phase 7 Polars benchmark..."
	$(PYTHON) -m src.benchmark_polars

pipeline: ## Run the full pipeline (Bronze -> Silver -> Gold)
	$(PYTHON) -m src.run_pipeline

test: ## Run the test suite
	$(PYTEST) tests/ -v

dashboard: ## Launch the Streamlit dashboard
	$(PYTHON) -m streamlit run app/dashboard.py

clean: ## Remove all generated artifacts
	@echo "Cleaning data and reports..."
	rm -rf data/truth/* data/raw/* data/quarantine/* data/interim/* data/warehouse/*
	rm -rf reports/*.html reports/*.md reports/*.json reports/*.png
	rm -rf logs/*.log logs/*.csv
	@echo "Cleaned all generated artifacts."

all: clean data profile bronze silver gold scorecard benchmark ## Run everything
	@echo "Pipeline complete up to Phase 7."
