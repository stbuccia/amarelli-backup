PANDOC ?= $(HOME)/.local/bin/pandoc
WEASYPRINT ?= $(HOME)/.local/bin/weasyprint
MD = report.md
HTML_TMP = /tmp/relazione.html
PDF = report.pdf
CSS = assets/style.css

.PHONY: pdf html clean

pdf: $(PDF)

html: $(HTML_TMP)

$(HTML_TMP): $(MD) $(CSS)
	$(PANDOC) $(MD) \
		--from gfm+raw_html+bracketed_spans \
		--to html5 \
		--standalone \
		--embed-resources \
		--css=$(CSS) \
		-o $(HTML_TMP)
	@sed -i -e 's/overflow-x:[[:space:]]*auto/overflow: auto/g' \
	       -e 's/[-a-z]*user-select[^;]*;//g' \
	       -e 's/[-a-z]*touch-callout[^;]*;//g' \
	       -e 's/  */ /g' $(HTML_TMP)

$(PDF): $(HTML_TMP)
	@$(WEASYPRINT) $(HTML_TMP) $(PDF) 2>&1 | grep -v "WARNING: Ignored" || true

clean:
	rm -f $(PDF) $(HTML_TMP)
