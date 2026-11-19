"""Domain routers — split of the main.py god-module.

Registration order defines OpenAPI/route precedence; paths are unchanged.

Every module also carries one OpenAPI tag (API-01): the served document used
to be a single flat list of 137 untagged operations, which is unnavigable in
/docs and in generated clients. Tags are applied here, at include time, so
they cover every router without restating them per route.
"""

from types import ModuleType

from fastapi import FastAPI

from . import (
    admin,
    assessment,
    auth,
    learn,
    parent,
    school,
    system,
    teacher,
    teacher_content,
    tutor,
    users,
    workspace,
)

#: (module, tag) in registration order — one tag per module.
_ROUTER_TAGS: tuple[tuple[ModuleType, str], ...] = (
    (system, "system"),
    (auth, "auth"),
    (tutor, "tutor"),
    (users, "users"),
    (learn, "learn"),
    (teacher, "teacher"),
    (school, "school"),
    (teacher_content, "teacher-content"),
    (workspace, "workspace"),
    (assessment, "assessment"),
    (admin, "admin"),
    (parent, "parent"),
)


def register_routers(app: FastAPI, *, versioned: bool = True) -> None:
    """Mount every domain router at its legacy root path, and (BC-4/T-25)
    additionally under ``/v1``.

    The ``/v1`` alias is an API-CONTRACT version (unrelated to the app
    version, §2.5): store-distributed mobile clients pin a baked base URL and
    cannot be force-updated, so a versioned prefix is the seam a future
    breaking change mounts behind. Legacy paths keep working unchanged; the
    alias mirrors the identical operations, so it is mounted with
    ``include_in_schema=False`` — duplicating 140 operations into the
    document would double the client surface without adding information and
    would break operation-ID uniqueness (ADR-0013).
    """
    for module, tag in _ROUTER_TAGS:
        app.include_router(module.router, tags=[tag])
        if versioned:
            app.include_router(module.router, prefix="/v1", include_in_schema=False, tags=[tag])
