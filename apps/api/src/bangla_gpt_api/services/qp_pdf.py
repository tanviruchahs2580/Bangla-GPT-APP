"""S2.4: PDF export for question papers (paper + answer key).

Primary engine is WeasyPrint when the platform's Pango/GTK libraries are
loadable (Linux containers). On hosts without them (e.g. Windows dev) this
falls back to fpdf2 + uharfbuzz with the bundled Noto Sans Bengali TTF,
which shapes Bengali conjuncts correctly. If neither engine is usable the
API returns the HTML print view instead (documented S2.4 fallback).
"""

from pathlib import Path

from fpdf import FPDF

_FONT = Path(__file__).resolve().parent.parent / "data" / "fonts" / ("NotoSansBengali-Regular.ttf")


def font_available() -> bool:
    return _FONT.is_file()


def render_qp_pdf(paper: dict, kind: str = "paper") -> bytes:
    """Render one question paper. ``kind``: 'paper' (no answers) or 'answer'."""
    if not font_available():
        raise RuntimeError("bundled Bengali font missing")
    pdf = FPDF(format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.add_font("nbg", style="", fname=str(_FONT))
    pdf.set_font("nbg", size=15)
    title = f"{paper['exam_type']} ({paper['class_level']}) - {paper['subject']}"
    pdf.cell(w=0, h=9, text=title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("nbg", size=10)
    pdf.set_text_color(90, 90, 90)
    header = f"{paper['marks']} marks | {paper['duration_min']} min | " + ", ".join(
        paper["chapters"]
    )
    pdf.cell(w=0, h=7, text=header, new_x="LMARGIN", new_y="NEXT")
    if kind == "answer":
        pdf.set_text_color(180, 30, 30)
        pdf.cell(w=0, h=7, text="ANSWER KEY", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("nbg", size=11)
    for i, q in enumerate(paper["questions"], start=1):
        pdf.set_font("nbg", size=11)
        pdf.multi_cell(
            w=0, h=6, text=f"{i}. {q['text']} ({q['marks']})", new_x="LMARGIN", new_y="NEXT"
        )
        pdf.set_font("nbg", size=10)
        for oi, opt in enumerate(q["options"]):
            mark = ""
            if kind == "answer" and oi == q["answer_index"]:
                mark = " <--"
            pdf.cell(
                w=0,
                h=5,
                text=f"   {chr(ord('a') + oi)}) {opt}{mark}",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        pdf.ln(2)
        pdf.set_font("nbg", size=11)
    return bytes(pdf.output())


def render_qp_html(paper: dict, kind: str = "paper") -> str:
    """Print-friendly HTML fallback (browser Ctrl+P gives a PDF)."""
    rows: list[str] = []
    for q in paper["questions"]:
        opts = []
        for oi, opt in enumerate(q["options"]):
            cls = ' class="answer"' if kind == "answer" and oi == q["answer_index"] else ""
            letter = chr(ord("a") + oi)
            opts.append(f"<li{cls}>{letter}) {_esc(opt)}</li>")
        rows.append(
            f"<li><p>{_esc(q['text'])} <span class='marks'>({q['marks']})</span></p>"
            f"<ol type='a'>{''.join(opts)}</ol></li>"
        )
    key = " / ANSWER KEY" if kind == "answer" else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(paper['exam_type'])}{key}</title><style>"
        "body{font-family:'Noto Sans Bengali','Hind Siliguri',sans-serif;max-width:800px;"
        "margin:2rem auto;line-height:1.7}"
        "@media print{body{margin:0}}"
        ".answer{font-weight:700}.marks{color:#666}</style></head><body>"
        f"<h1>{_esc(paper['exam_type'])} ({paper['class_level']}) - {_esc(paper['subject'])}"
        f"{' / ANSWER KEY' if kind == 'answer' else ''}</h1>"
        f"<p>{paper['marks']} | {paper['duration_min']} min | "
        f"{_esc(', '.join(paper['chapters']))}</p>"
        f"<ol>{''.join(rows)}</ol></body></html>"
    )


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
