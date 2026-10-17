# Build the technical report.
#   make            texgen + PDF from the claims and figures already in build/ (no data access)
#   make claims     run every scripts/claims/*.py against the data (checks free disk first), then texgen
#   make test       the report's test suite
TEXBIN ?= /Library/TeX/texbin
export PATH := $(TEXBIN):$(PATH)
BUILD := build
OUT := $(BUILD)/tex
UV := uv run

.PHONY: pdf texgen claims figures preflight test clean atlas

pdf: texgen ## Compile tex/main.tex into build/report.pdf (latexmk + biber)
	mkdir -p $(OUT) $(BUILD)/figures
	cd tex && latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=../$(OUT) main.tex
	cp $(OUT)/main.pdf $(BUILD)/report.pdf

texgen: ## Generate \est, \proto and tables; fails on any unresolved reference
	$(UV) python -m report_lib.texgen

preflight: ## Refuse to run data scripts unless the disk budget (conf/protocol.toml) plus headroom is free
	@$(UV) python -c "import shutil; from report_lib import protocol; d = protocol.load()['disk']; \
	need = sum(v for v in d.values()); free = shutil.disk_usage('.').free / 2**30; \
	print(f'free {free:.1f} GiB, budget plus headroom {need:.1f} GiB'); \
	raise SystemExit(0 if free >= need else 'not enough free disk for a data run')"

claims: preflight ## Run every chapter's claims script, then the figures and texgen
	@for s in $$(ls scripts/claims/*.py | sort); do echo "== $$s"; $(UV) python $$s || exit 1; done
	$(MAKE) figures texgen

figures: ## Redraw every figure from its (hashed) sources
	@for s in $$(ls scripts/figures/*.py | sort); do echo "== $$s"; $(UV) python $$s || exit 1; done

atlas: pdf ## The Grain Atlas with this report as a book: build/atlas/grain_atlas.html
	$(UV) python scripts/atlas_ebook.py

test: ## Run the report test suite
	$(UV) pytest -q

clean: ## Remove LaTeX build products (keeps claims, figures and sources)
	rm -rf $(OUT) $(BUILD)/report.pdf
