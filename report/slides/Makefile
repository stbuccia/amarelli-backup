PANDOC ?= $(HOME)/.local/bin/pandoc
# Il LibreOffice di sistema non include Impress: si usa il flatpak
SOFFICE ?= flatpak run --command=libreoffice org.libreoffice.LibreOffice

MD = slides.md
PPTX = slides.pptx
ODP = slides.odp
PDF = slides.pdf
IMG = $(wildcard img/*)

.PHONY: all odp pptx pdf images clean

all: odp

odp: $(ODP)

pptx: $(PPTX)

pdf: $(PDF)

$(PPTX): $(MD) $(IMG)
	$(PANDOC) $(MD) --to pptx --slide-level=1 -o $(PPTX)

# Impress importa il pptx e lo risalva come odp nativo
$(ODP): $(PPTX)
	$(SOFFICE) --headless --convert-to odp --outdir . $(PPTX)

$(PDF): $(ODP)
	$(SOFFICE) --headless --convert-to pdf --outdir . $(ODP)

clean:
	rm -f $(PPTX) $(ODP) $(PDF) .~lock.*#
