"""Teacher content routes, split by resource (C-03): chapter content,
question papers, and the generated documents.

Split of the 29-name module ``routers/teacher_content.py`` along its seams (C-03).
The sub-routers are included in the original declaration order, so the
served route table -- which `docs/route_baseline.md` records and the
OpenAPI document pins -- is unchanged: verified with
`.audit/tmp/r5/routes_dump.py` and `scripts/gen_api_docs.py --check`.
"""

from fastapi import APIRouter

from . import _content, _documents, _qpapers, _qpapers_review

#: Inclusion order mirrors the pre-split file (route precedence).
router = APIRouter()
for _sub in (_content, _qpapers, _qpapers_review, _documents):
    router.include_router(_sub.router)

__all__ = ["router"]
