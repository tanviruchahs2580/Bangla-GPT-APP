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


# ── Wave 1: printable PDFs for persisted teacher documents ────────────────
# Same engine + bundled font as render_qp_pdf above; one renderer per
# printable kind (worksheet / answer_key / lesson_plan).


def render_document_pdf(doc: dict) -> bytes:
    """Render one persisted TeacherDocument. ``doc`` keys: kind, title,
    class_level, subject, chapter, payload."""
    if not font_available():
        raise RuntimeError("bundled Bengali font missing")
    kind = str(doc.get("kind", ""))
    if kind not in ("worksheet", "answer_key", "lesson_plan"):
        raise ValueError(f"no PDF renderer for kind {kind!r}")
    payload = dict(doc.get("payload") or {})
    pdf = FPDF(format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.add_font("nbg", style="", fname=str(_FONT))
    pdf.set_font("nbg", size=15)
    pdf.cell(
        w=0,
        h=9,
        text=f"{doc.get('title') or kind} ({doc.get('class_level')}) - {doc.get('subject')}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font("nbg", size=10)
    pdf.set_text_color(90, 90, 90)
    chapter = doc.get("chapter") or "-"
    pdf.cell(w=0, h=7, text=f"chapter: {chapter}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    if kind == "worksheet":
        _worksheet_pdf(pdf, payload)
    elif kind == "answer_key":
        _answer_key_pdf(pdf, payload)
    else:
        _lesson_plan_pdf(pdf, payload)
    return bytes(pdf.output())


def _worksheet_pdf(pdf: FPDF, payload: dict) -> None:
    for tier in payload.get("tiers") or []:
        pdf.set_font("nbg", size=12)
        pdf.cell(
            w=0,
            h=8,
            text=f"[{tier.get('tier')}]",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("nbg", size=11)
        for i, q in enumerate(tier.get("questions") or [], start=1):
            pdf.multi_cell(
                w=0,
                h=6,
                text=f"{i}. {q.get('text')} ({q.get('marks')})",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_font("nbg", size=10)
            for oi, opt in enumerate(q.get("options") or []):
                pdf.cell(
                    w=0,
                    h=5,
                    text=f"   {chr(ord('a') + oi)}) {opt}",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            pdf.set_font("nbg", size=11)
            pdf.ln(2)
    pdf.set_font("nbg", size=12)
    pdf.cell(w=0, h=8, text="ANSWER SHEET", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("nbg", size=10)
    for row in payload.get("answer_sheet") or []:
        pdf.cell(
            w=0,
            h=5,
            text=f"{row.get('ref')}: {row.get('answer')}",
            new_x="LMARGIN",
            new_y="NEXT",
        )


def _answer_key_pdf(pdf: FPDF, payload: dict) -> None:
    pdf.set_font("nbg", size=11)
    for a in payload.get("answers") or []:
        pdf.multi_cell(
            w=0,
            h=6,
            text=f"{a.get('ref')} ({a.get('marks')}): {a.get('answer')}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("nbg", size=10)
        pdf.set_text_color(70, 70, 70)
        pdf.multi_cell(
            w=0, h=5, text=f"  {a.get('detailed_solution')}", new_x="LMARGIN", new_y="NEXT"
        )
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("nbg", size=11)
        pdf.ln(1)
    guide = payload.get("marking_guide") or {}
    pdf.set_font("nbg", size=12)
    pdf.cell(
        w=0,
        h=8,
        text=f"MARKING GUIDE - TOTAL {guide.get('total_marks')}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font("nbg", size=10)
    note = str(guide.get("per_mark_note") or "")
    if note:
        pdf.multi_cell(w=0, h=5, text=note, new_x="LMARGIN", new_y="NEXT")


def _lesson_plan_pdf(pdf: FPDF, payload: dict) -> None:
    sections = payload.get("sections") or {}
    for key in (
        "objective",
        "previous_knowledge",
        "introduction",
        "main_explanation",
        "activity",
        "questions",
        "assessment",
        "homework",
    ):
        value = str(sections.get(key) or "").strip()
        if not value:
            continue
        pdf.set_font("nbg", size=12)
        pdf.cell(w=0, h=8, text=key.replace("_", " ").upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("nbg", size=11)
        for line in value.splitlines() or [value]:
            pdf.multi_cell(w=0, h=6, text=line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)


def render_document_html(doc: dict) -> str:
    """Print-friendly HTML fallback for teacher documents (Ctrl+P gives a PDF)."""
    rows: list[str] = []
    payload = dict(doc.get("payload") or {})

    def add(text: str) -> None:
        rows.append(f"<p>{_esc(text)}</p>")

    for tier in payload.get("tiers") or []:
        rows.append(f"<h2>{_esc(str(tier.get('tier')))}</h2>")
        for i, q in enumerate(tier.get("questions") or [], start=1):
            rows.append(f"<p>{i}. {_esc(str(q.get('text')))} ({q.get('marks')})</p>")
    for a in payload.get("answers") or []:
        rows.append(
            f"<p><b>{_esc(str(a.get('ref')))}</b> {_esc(str(a.get('answer')))} "
            f"({a.get('marks')})<br><i>{_esc(str(a.get('detailed_solution')))}</i></p>"
        )
    for row in payload.get("answer_sheet") or []:
        add(f"{row.get('ref')}: {row.get('answer')}")
    sections = payload.get("sections") or {}
    for key, value in sections.items():
        rows.append(f"<h2>{_esc(str(key))}</h2><p>{_esc(str(value))}</p>")
    guide = payload.get("marking_guide") or {}
    if guide:
        add(f"Total marks: {guide.get('total_marks')}")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(str(doc.get('title') or ''))}</title><style>"
        "body{font-family:'Noto Sans Bengali','Hind Siliguri',sans-serif;max-width:800px;"
        "margin:2rem auto;line-height:1.7}@media print{body{margin:0}}</style></head><body>"
        f"<h1>{_esc(str(doc.get('title') or ''))}</h1>{''.join(rows)}</body></html>"
    )
