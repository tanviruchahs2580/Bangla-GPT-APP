"""A7-05: per-role in-flight caps narrow the base for privileged accounts.

The rule is exercised through the router's own
:func:`effective_inflight_limit`, not a copy, so a change to the rule breaks
this test instead of silently bypassing it.
"""

from types import SimpleNamespace

from bangla_gpt_api.routers.tutor import effective_inflight_limit


def _settings(**over):
    base = {"teacher_inflight_cap": 0, "admin_inflight_cap": 0}
    base.update(over)
    return SimpleNamespace(**base)


def test_teacher_cap_narrows_the_base() -> None:
    assert effective_inflight_limit(_settings(teacher_inflight_cap=1), "teacher", default=2) == 1


def test_admin_cap_narrows_the_base() -> None:
    assert effective_inflight_limit(_settings(admin_inflight_cap=1), "admin", default=2) == 1


def test_student_inherits_the_base_cap() -> None:
    assert effective_inflight_limit(_settings(), "student", default=2) == 2


def test_zero_caps_inherit_the_base() -> None:
    s = _settings(teacher_inflight_cap=0, admin_inflight_cap=0)
    assert effective_inflight_limit(s, "teacher", default=2) == 2
    assert effective_inflight_limit(s, "admin", default=2) == 2


def test_role_cap_cannot_raise_above_the_base() -> None:
    s = _settings(teacher_inflight_cap=5)
    assert effective_inflight_limit(s, "teacher", default=2) == 2
