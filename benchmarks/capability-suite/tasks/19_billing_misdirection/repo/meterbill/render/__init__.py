"""Invoice renderers: text (the PDF source), CSV (the ERP import), JSON
(the customer portal) and HTML (e-mail).  Renderers only format; they never compute or round
amounts (docs/INVOICES.md, "Rendering")."""

from .csv_out import render_csv
from .html_out import render_html
from .json_out import render_json
from .text import render_text

RENDERERS = {"text": render_text, "csv": render_csv, "json": render_json, "html": render_html}


def render(invoice, fmt="text"):
    try:
        fn = RENDERERS[fmt]
    except KeyError:
        raise ValueError(f"unknown format {fmt!r}; expected one of {', '.join(sorted(RENDERERS))}") from None
    return fn(invoice)
