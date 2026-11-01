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


def register_routers(app: FastAPI) -> None:
    for module, tag in _ROUTER_TAGS:
        app.include_router(module.router, tags=[tag])
