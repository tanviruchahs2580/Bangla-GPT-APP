"""JWT issuer/audience binding (AUD-0028).

Access tokens carried no ``iss`` or ``aud`` claim, so a token was only bound
to the signing key. Anything else signed with the same key -- a future
service, a differently-scoped token -- would be accepted verbatim. Tokens now
carry both claims and ``decode_token`` verifies them, which also refuses every
token minted before this change (a one-time forced re-login).
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from bangla_gpt_api.auth.security import create_access_token, decode_token
from bangla_gpt_api.config import Settings

SECRET = "unit-secret-0123456789abcdef0123456789"


class FakeUser:
    id = 7
    role = "teacher"


def _settings(**overrides) -> Settings:
    return Settings(jwt_secret=SECRET, **overrides)


def test_token_carries_issuer_and_audience() -> None:
    settings = _settings()
    token = create_access_token(FakeUser(), settings=settings)
    # Decoding with the strict verifier proves the claims are present and valid.
    payload = decode_token(token, settings=settings)
    assert payload["iss"] == settings.jwt_issuer
    assert payload["aud"] == settings.jwt_audience


def test_token_signed_with_wrong_issuer_is_rejected() -> None:
    settings = _settings()
    forged = pyjwt.encode(
        {
            "sub": "7",
            "role": "teacher",
            "iss": "some-other-service",
            "aud": settings.jwt_audience,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(pyjwt.InvalidIssuerError):
        decode_token(forged, settings=settings)


def test_token_signed_for_wrong_audience_is_rejected() -> None:
    settings = _settings()
    forged = pyjwt.encode(
        {
            "sub": "7",
            "role": "teacher",
            "iss": settings.jwt_issuer,
            "aud": "some-other-client",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(pyjwt.InvalidAudienceError):
        decode_token(forged, settings=settings)


def test_token_without_issuer_or_audience_is_rejected() -> None:
    """A pre-SEC-03 token (no iss/aud) must be refused, forcing a re-login."""
    settings = _settings()
    legacy = pyjwt.encode(
        {
            "sub": "7",
            "role": "teacher",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(pyjwt.MissingRequiredClaimError):
        decode_token(legacy, settings=settings)
