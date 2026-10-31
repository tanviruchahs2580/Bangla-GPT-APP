"""Session-bound impersonation (F-146, SEC-07).

An impersonation token is a bearer session as far as ``get_current_user``
is concerned; the only thing that ends it early is a revocation write into
the ``imp_revoke:`` namespace. Before this module the ONLY writer was
``POST /auth/impersonate/exit`` and the admin-side stop endpoint, so an
admin who simply signed out -- or whose own session was revoked -- left the
impersonation token authenticating for the rest of its 15 minutes. The
support session outlived the session that authorised it, which is exactly
backwards: the impersonated window must be a subset of the admin's.

The binding is an index in the shared cache: every impersonation token's
``jti`` is recorded under the ``jti`` of the admin token that minted it.
Ending the admin session (logout, or the account-wide revoke) reads that
index and parks each listed ``jti`` in the revocation namespace with the
impersonation TTL, so the impersonated access dies with the authorising
session.

Both helpers are strict (``CacheUnavailable`` propagates): minting a
session that can never be revoked, or answering "signed out" while an
impersonated token keeps working, would be a lie (the F-08 discipline the
impersonation path already applies).
"""

from __future__ import annotations

from typing import Any

#: Lifetime of one impersonation session, in seconds. The minted token and
#: the revocation entries all derive from this single number.
IMPERSONATION_TTL_SECONDS = 15 * 60

#: Index key: impersonation jtis started from one admin session token.
_SESSION_KEY = "imp_session:{jti}"

#: Revocation key namespace read by ``get_current_user`` for ``imp`` tokens.
_REVOKE_KEY = "imp_revoke:{jti}"


def _index_key(admin_jti: str) -> str:
    return _SESSION_KEY.format(jti=admin_jti)


def remember_session(cache: Any, *, admin_jti: str, imp_jti: str) -> None:
    """Record that ``imp_jti`` was minted from the ``admin_jti`` session."""
    key = _index_key(admin_jti)
    existing = cache.get_json_strict(key) or []
    if not isinstance(existing, list):
        existing = []
    # Bound the list: a session that opens dozens of support sessions is
    # already abnormal, and only the live ones (15 min) can matter.
    existing.append(imp_jti)
    cache.set_json_strict(key, existing[-10:], IMPERSONATION_TTL_SECONDS)


def revoke_session(cache: Any, *, admin_jti: str) -> int:
    """Revoke every impersonation token minted from this admin session.

    Returns how many were revoked so the caller can audit the implicit end
    (0 when the session never impersonated -- the common case). The index
    is cleared afterwards; a later impersonation needs a new admin session,
    which means a new login.
    """
    key = _index_key(admin_jti)
    active = cache.get_json_strict(key) or []
    if not isinstance(active, list):
        active = []
    revoked = 0
    for jti in active:
        if isinstance(jti, str) and jti:
            cache.set_json_strict(_REVOKE_KEY.format(jti=jti), True, IMPERSONATION_TTL_SECONDS)
            revoked += 1
    cache.set_json_strict(key, [], 1)
    return revoked
