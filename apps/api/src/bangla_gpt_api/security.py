"""security -- S5.6 helpers.

Two small primitives that the hardening step needs:

* Fernet encryption for PII at rest (guardian phone), keyed by
  ``PII_ENC_KEY``. No key configured -> the plaintext value is passed
  through unchanged, so dev/test deployments without a key still work
  (and the test suite asserts the ciphertext round-trip when a key IS set).
  The key value never appears in a log or an API response (R7).
* an append-only audit row writer for the five privileged event types
  (role_change, data_export, purge, qp_finalize, impersonation).
  Rows store ids and outcome metadata only -- never message content (R11).
"""

import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AuditLog
from bangla_gpt_api.logging_config import json_log

logger = logging.getLogger(__name__)

_FERNET_PREFIX = "fernet:"


def encrypt_pii(value: str | None, key: str | None) -> str | None:
    """Encrypt for storage. None in, None out; empty key -> passthrough."""
    if value is None:
        return None
    if not key:
        return value
    return _FERNET_PREFIX + Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt_pii(stored: str | None, key: str | None) -> str | None:
    """Inverse of :func:`encrypt_pii`. A stored value that was written with a
    different key (rotation) decrypts to None rather than crashing -- callers
    treat that as "unavailable" and the admin re-enters it.
    """
    if stored is None:
        return None
    if not stored.startswith(_FERNET_PREFIX):
        return stored  # written before a key existed (passthrough era)
    if not key:
        return None
    try:
        return Fernet(key.encode()).decrypt(stored[len(_FERNET_PREFIX) :].encode()).decode()
    except InvalidToken:
        json_log(logger, logging.WARNING, "pii_decrypt_failed")
        return None


def write_audit(
    db: Session,
    *,
    action: str,
    actor_user_id: int | None,
    actor_role: str | None,
    target: str | None,
    detail: dict | None,
) -> None:
    """Append one audit row. The caller commits -- audit rows land in the
    same transaction as the action they describe, so a rolled-back action
    leaves no trail and a committed one always has one.
    """
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            actor_role=actor_role or "anonymous",
            action=action,
            target=target,
            detail=detail or {},
        )
    )
