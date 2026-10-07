# Build the technical report. `make` builds the PDF from whatever claims and figures exist in build/.
TEXBIN ?= /Library/TeX/texbin
export PATH := $(TEXBIN):$(PATH)
BUILD := build
OUT := $(BUILD)/tex

.PHONY: pdf clean

pdf: ## Compile tex/main.tex into build/report.pdf (latexmk + biber)
	mkdir -p $(OUT) $(BUILD)/generated $(BUILD)/figures
	cd tex && latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=../$(OUT) main.tex
	cp $(OUT)/main.pdf $(BUILD)/report.pdf

clean: ## Remove LaTeX build products (keeps generated claims and figures)
	rm -rf $(OUT) $(BUILD)/report.pdf
