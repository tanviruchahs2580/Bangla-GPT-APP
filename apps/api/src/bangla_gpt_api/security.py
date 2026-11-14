"""security -- helpers.

Two small primitives that the hardening step needs:

* Fernet encryption for PII at rest (guardian phone), keyed by
  ``PII_ENC_KEY``. No key configured -> the plaintext value is passed
  through unchanged, so dev/test deployments without a key still work
  (and the test suite asserts the ciphertext round-trip when a key IS set).
  The key value never appears in a log or an API response.
* an append-only audit row writer for the five privileged event types
  (role_change, data_export, purge, qp_finalize, impersonation).
  Rows store ids and outcome metadata only -- never message content.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AuditLog
from bangla_gpt_api.logging_config import json_log

logger = logging.getLogger(__name__)

_FERNET_PREFIX = "fernet:"

#: BGPT-SEC-001 — TOTP seeds are ciphertext at rest. The domain is separated
#: from the PII key by derivation, never by reuse: the same PII_ENC_KEY
#: material is fed through HKDF with a distinct label, so a compromise of
#: one ciphertext domain does not open the other. ``totp1:`` is the key/
#: format version tag; rotation introduces ``totp2:`` with a new label and
#: a dual-read window.
_TOTP_PREFIX = "totp1:"
_TOTP_HKDF_INFO = b"bangla-gpt:totp-seed:v1"


def _derive_totp_fernet_key(pii_key: str) -> bytes:
    """HKDF-SHA256(PII_ENC_KEY, info=…) → urlsafe Fernet key for TOTP."""
    digest = hashlib.sha256(pii_key.encode()).digest()
    # RFC 5869 HKDF extract+expand with a fixed salt (the domain label
    # carries the separation, the salt binds it into the PRK).
    prk = hashlib.sha256(b"bangla-gpt:totp-domain-salt" + digest).digest()
    block = hashlib.sha256(prk + _TOTP_HKDF_INFO + b"\x01").digest()
    return base64.urlsafe_b64encode(block)


class PiiKeyUnconfigured(RuntimeError):
    """A PII write path was reached with no PII_ENC_KEY and no explicit
    plaintext consent (``PII_ALLOW_PLAINTEXT``)."""


def encrypt_pii_strict(
    value: str | None, key: str | None, *, allow_plaintext: bool = True
) -> str | None:
    """``encrypt_pii`` with an explicit consent gate on the plaintext
    fallback.

    The passthrough era stored guardian phones unencrypted whenever the
    key was absent -- silently, everywhere (audit B-04). Writes now opt
    in explicitly via this call; ``main.py::_validate_pii`` refuses to
    boot production with the consent flag on, so a mis-configured pilot
    fails this one request with a coded 503 instead of quietly writing
    children's guardian PII in the clear.
    """
    if value is not None and not key and not allow_plaintext:
        raise PiiKeyUnconfigured(
            "PII_ENC_KEY is not configured and PII_ALLOW_PLAINTEXT is "
            "not enabled; refusing to store PII unencrypted"
        )
    return encrypt_pii(value, key)


def encrypt_pii(value: str | None, key: str | None) -> str | None:
    """Encrypt for storage. None in, None out; empty key -> passthrough."""
    if value is None:
        return None
    if not key:
        return value
    return _FERNET_PREFIX + Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt_pii(stored: str | None, key: str | None) -> str | None:
    """Inverse of:func:`encrypt_pii`. A stored value that was written with a
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


def encrypt_totp_secret(seed: str | None, pii_key: str | None) -> str | None:
    """Encrypt a TOTP seed for storage (BGPT-SEC-001).

    Keyless (dev) deployments fall back to plaintext with a loud structured
    warning — the same documented passthrough era ``encrypt_pii`` has, while
    the production boot guard makes the fallback unreachable there.
    """
    if seed is None:
        return None
    if not pii_key:
        json_log(
            logger,
            logging.WARNING,
            "totp_encrypt_keyless",
            detail="storing MFA seed as plaintext: PII_ENC_KEY not configured",
        )
        return seed
    fernet = Fernet(_derive_totp_fernet_key(pii_key))
    return _TOTP_PREFIX + fernet.encrypt(seed.encode()).decode()


def decrypt_totp_secret(stored: str | None, pii_key: str | None) -> str | None:
    """Inverse of :func:`encrypt_totp_secret`.

    ``totp1:`` ciphertext decrypts with the derived key; a value without the
    prefix is a legacy plaintext row (pre-fix or keyless era) and passes
    through so existing MFA accounts keep working until the sweep upgrades
    them. A ciphertext that will not decrypt returns ``None`` — the caller
    must fail closed (the challenge simply fails) and never log the stored
    value.
    """
    if stored is None:
        return None
    if not stored.startswith(_TOTP_PREFIX):
        return stored
    if not pii_key:
        json_log(logger, logging.WARNING, "totp_decrypt_keyless")
        return None
    try:
        fernet = Fernet(_derive_totp_fernet_key(pii_key))
        return fernet.decrypt(stored[len(_TOTP_PREFIX) :].encode()).decode()
    except InvalidToken:
        json_log(logger, logging.WARNING, "totp_decrypt_failed")
        return None


def is_encrypted_totp_secret(stored: str | None) -> bool:
    """True when the stored value is the versioned ciphertext form."""
    return stored is not None and stored.startswith(_TOTP_PREFIX)


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

    SEC-002: when the request is a support (impersonation) session, the
    actor stays the impersonated account -- the trail must keep naming
    whose data was touched -- and the fact that an admin was driving is
    merged in as ``impersonated: true`` / ``imp_by``. The marker is put on
    the request's Session by ``routers/deps.py::get_current_user``
    (``Session.info``), which is the same object every request-scoped
    caller passes here; a ContextVar would not survive the sync-handler
    threadpool boundary. Non-impersonated requests never carry the key, so
    their rows are exactly what they were. Ids and outcome metadata only --
    never message content, never PII.
    """
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            actor_role=actor_role or "anonymous",
            action=action,
            target=target,
            detail={**(detail or {}), **db.info.get("_impersonation", {})},
        )
    )
