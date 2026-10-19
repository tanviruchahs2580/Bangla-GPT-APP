"""C-10: one pagination convention for collection endpoints.

Every collection GET declares its window through this module instead of a raw
``Query(...)`` literal in the router, so the convention is reviewable in one
place and the served OpenAPI is uniform:

* ``limit`` is always ``ge=1`` and carries a maximum (the audit found caps
  ranging 50..1000 declared ad hoc);
* ``offset`` is always present, ``ge=0``, defaulting to 0, so a client can walk
  a collection instead of guessing a bigger limit;
* the ordering is always explicit and stable (``ORDER BY created_at DESC,
  id DESC`` or an equivalent unique tiebreak) -- an offset without a stable
  sort silently skips or repeats rows.

Three presets exist, each with its reason (recorded in
``docs/adr/ADR-0012-api-design-conventions.md``):

* :data:`ArchivePage` -- default 50, cap 200. The default for archives and
  search-style lists (``/notes``).
* :data:`TaskListPage` -- default 100, cap 200. Task lists the SPA renders in
  one call without a pager (``/shorttests/mine``); the larger default is a
  UI decision, the cap is not.
* :data:`WindowPage` -- default 200, cap 200. Endpoints that scan a recent
  window before filtering in Python (``/assignments/mine``); ``offset``
  applies to the candidate window, which the docstring states.

A "top-N queue" (``/revision/due``) has no ``offset`` on purpose: it answers
"what is due now", the total is reported separately, and paging a due queue is
meaningless. ``tests/test_r3_ws3_pagination_convention.py`` pins both the
convention and the exception list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

#: Default window for an archive-style list.
DEFAULT_LIMIT = 50
#: The cap every collection endpoint must respect.
MAX_LIMIT = 200
#: Default window for the SPA's one-call task lists.
TASK_LIST_LIMIT = 100
#: Default (and cap) for endpoints that scan a recent window first.
WINDOW_LIMIT = 200


@dataclass(frozen=True)
class Page:
    """A resolved page: how many rows, skipping how many."""

    limit: int
    offset: int


def page_params(
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Maximum rows to return")
    ] = DEFAULT_LIMIT,
    offset: Annotated[
        int, Query(ge=0, description="Rows to skip, after the endpoint's stable sort")
    ] = 0,
) -> Page:
    return Page(limit=limit, offset=offset)


def task_list_params(
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_LIMIT,
            description="Maximum rows to return (the SPA renders this list in one call)",
        ),
    ] = TASK_LIST_LIMIT,
    offset: Annotated[
        int, Query(ge=0, description="Rows to skip, after the endpoint's stable sort")
    ] = 0,
) -> Page:
    return Page(limit=limit, offset=offset)


def window_params(
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_LIMIT,
            description="Size of the recent-row candidate window to scan",
        ),
    ] = WINDOW_LIMIT,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Rows to skip inside the candidate window (filtering happens after it)",
        ),
    ] = 0,
) -> Page:
    return Page(limit=limit, offset=offset)


ArchivePage = Annotated[Page, Depends(page_params)]
TaskListPage = Annotated[Page, Depends(task_list_params)]
WindowPage = Annotated[Page, Depends(window_params)]
