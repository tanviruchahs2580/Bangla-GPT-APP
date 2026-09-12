"""Domain routers — ARCH-001 split of the main.py god-module.

Registration order defines OpenAPI/route precedence; paths are unchanged.
"""

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


def register_routers(app: FastAPI) -> None:
    for module in (
        system,
        auth,
        tutor,
        users,
        learn,
        teacher,
        school,
        teacher_content,
        workspace,
        assessment,
        admin,
        parent,
    ):
        app.include_router(module.router)
