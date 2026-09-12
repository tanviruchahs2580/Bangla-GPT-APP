"""AUTH-001: TOTP multi-factor authentication (RFC 6238, stdlib only).

No new dependencies: HMAC-SHA1 + base32 + struct are all stdlib. Secrets are
20 random bytes (160-bit, base32-encoded); verification accepts a ±1 step
window (30s steps) for clock skew. Test vectors: RFC 6238 SHA-1,
secret ``12345678901234567890`` (ASCII), T=59 → 94287082 (8-digit).

Flow (backward compatible — users without MFA see zero change):
1. ``POST /auth/mfa/enroll`` (authed) returns ``{secret, otpauth_uri}`` for
   the authenticator app. NOTHING is stored yet.
2. ``POST /auth/mfa/verify`` (authed, ``{secret, code}``) proves possession
   and stores the secret (= enabled).
3. ``POST /auth/login`` with MFA enabled returns HTTP 202 + TokenResponse
   with ``token_type="mfa"`` carrying a purpose-bound 5-minute JWT. That
   token is rejected by every normal route (see ``is_mfa_token``).
4. ``POST /auth/mfa/challenge`` (``{mfa_token, code}``) returns the real
   bearer TokenResponse.
5. ``POST /auth/mfa/disable`` (authed + password) clears the secret.
"""

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
import time

_STEP_SECONDS = 30
_DIGITS = 6
_WINDOW_STEPS = 1


def new_secret() -> str:
    """Fresh 160-bit base32 secret (no padding, authenticator-friendly)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def otpauth_uri(secret: str, email: str, issuer: str = "Bangla GPT") -> str:
    label = f"{issuer}:{email.strip().lower()}"
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}&issuer={issuer}&algorithm=SHA1&digits={_DIGITS}&period={_STEP_SECONDS}"
    )


def _hotp(secret: str, counter: int) -> str:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**_DIGITS)).zfill(_DIGITS)


def verify_code(secret: str, code: str, *, now: float | None = None) -> bool:
    """Accept a 6-digit ``code`` for ``secret`` within ±1 time step."""
    candidate = (code or "").strip()
    if len(candidate) != _DIGITS or not candidate.isdigit():
        return False
    try:
        step = int((time.time() if now is None else now) // _STEP_SECONDS)
    except (TypeError, ValueError):
        return False
    try:
        for delta in range(-_WINDOW_STEPS, _WINDOW_STEPS + 1):
            if hmac.compare_digest(_hotp(secret, step + delta), candidate):
                return True
    except (ValueError, TypeError, binascii.Error):
        return False
    return False
