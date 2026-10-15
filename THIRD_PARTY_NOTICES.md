# Third-party notices

This project is MIT licensed (see `LICENSE`). It redistributes the third-party
material below and depends on further packages listed at the end. The full
licence text of every redistributed item lives next to that item; this file is
the index.

## Bundled material

### Noto Sans Bengali (Regular)

- File: `apps/api/src/bangla_gpt_api/data/fonts/NotoSansBengali-Regular.ttf`
- Used by: Bengali PDF generation in the API (embedded into the output file).
- Copyright: The Noto Project Authors (<https://github.com/notofonts/bengali>)
- Licence: SIL Open Font License 1.1 — full text at
  `apps/api/src/bangla_gpt_api/data/fonts/OFL.txt`, shipped in the wheel next
  to the font because OFL-1.1 section 2 requires every copy to carry the
  licence.

## Web fonts (installed, not vendored)

| Package | Copyright | Licence |
| --- | --- | --- |
| `@fontsource/noto-sans-bengali` | The Noto Project Authors | SIL OFL 1.1 |
| `@fontsource/hind-siliguri` | Indian Type Foundry | SIL OFL 1.1 |

These are npm dependencies, not committed files; the licence text is installed
with each package at `node_modules/<package>/LICENSE`.

## Runtime dependencies

Taken from each project's PyPI metadata on 2026-10-10. Regenerate with
`python -c "import importlib.metadata, json; ..."` or read the project's own
`pyproject.toml`; do not edit by hand.

| Package | Licence | Note |
| --- | --- | --- |
| `cryptography` | Apache-2.0 OR BSD-3-Clause | Fernet encryption of PII at rest |
| `argon2-cffi` | MIT | Argon2id password hashing |
| `PyJWT` | MIT | Access-token signing/verification |
| `SQLAlchemy` | MIT | ORM |
| `alembic` | MIT | schema migrations |
| `fastapi` | MIT | HTTP framework |
| `starlette` | BSD-3-Clause | ASGI layer |
| `pydantic` / `pydantic-settings` | MIT | validation and settings |
| `uvicorn` | BSD-3-Clause | ASGI server |
| `gunicorn` | MIT | process manager |
| `redis` / `arq` | MIT | cache and job queue |
| `httpx` | BSD-3-Clause | outbound HTTP |
| `psycopg` | **LGPL-3.0-only** | Postgres driver (dynamic linking keeps this compatible) |
| `sentry-sdk` | MIT | error reporting |
| `prometheus-client` | Apache-2.0 AND BSD-2-Clause | metrics |
| `pypdf` | BSD-3-Clause | PDF reading |
| `bijoy2unicode` | MIT | legacy Bijoy encoding conversion |
| `fpdf2` | **LGPL-3.0-only** | PDF generation |
| `python-multipart` | Apache-2.0 | form parsing |
| `email-validator` | Unlicense | email syntax validation |

`uharfbuzz` was previously listed here as being used for "Bengali text
shaping". It was never imported anywhere in the codebase: `qp_pdf.py` imports
only `pathlib` and `fpdf`, and Bengali is embedded through the bundled Noto
Sans Bengali TTF. It was a declared runtime dependency, installed into the
production image and shipped in the wheel, for a function it does not
perform. It has been removed from `pyproject.toml` and `constraints.txt`
(F-042); `fpdf2` does the glyph work.

The two LGPL-3.0-only dependencies (`fpdf2`, `psycopg`) are used as ordinary
libraries from a MIT-licensed application; distributing a container image that
includes them requires shipping this notice so recipients can relink.

## Reporting

If material here is missing or mis-attributed, open an issue. Do not remove an
attribution in order to satisfy a licence requirement of the material itself.