"""F-121/F-188: the request id survives the round trip, on both sides.

Two halves of the same contract:

* server side - a client-supplied ``X-Request-ID`` in the id alphabet the web
  client generates is echoed back verbatim, so the id in a user's error report
  resolves to the server log line;
* client side - a source-level guard that ``apps/web/src/api.ts`` actually
  sends the header and reads the echo. The web unit suite is owned by the
  frontend stream, so this repository-level check is the executable guard on
  this side of the boundary.

F-188 is also pinned here: the redaction filter used to mask hex identifiers
whose digit run matched the phone pattern, which lost the id in the very sink
used for correlation.
"""

import logging
import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.logging_config import REDACTED, RedactionFilter, redact_value
from bangla_gpt_api.main import create_app
from conftest import engine_url

REPO_ROOT = Path(__file__).resolve().parents[3]
API_TS = REPO_ROOT / "apps" / "web" / "src" / "api.ts"

SECRET = "w2-obs-secret-0123456789abcdef"


def _settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2obs"),
        jwt_secret=SECRET,
    )


def test_server_echoes_a_web_client_style_request_id(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    # The shape the web client generates: the uuid4 hex, hyphens stripped.
    sent = uuid.uuid4().hex.replace("-", "")
    res = client.get("/health", headers={"X-Request-ID": sent})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == sent


def test_server_replaces_a_malformed_request_id(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    res = client.get("/health", headers={"X-Request-ID": "not a valid id!"})
    assert res.status_code == 200
    echoed = res.headers["X-Request-ID"]
    assert echoed != "not a valid id!"
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", echoed)


# ---------------------------------------------------------------------------
# F-188 - identifier-shaped log values survive redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_id",
    [
        # The value measured in the audit: an 11-digit run matched the phone
        # pattern and the id was logged as "[redacted]".
        "9c12968924894e25",
        # A run of exactly 15 digits, the phone pattern's upper bound.
        "123456789012345",
        # All digits: the worst case for the phone pattern.
        "0123456789012345",
    ],
)
def test_identifier_values_are_not_masked_by_the_phone_pattern(request_id: str) -> None:
    assert redact_value({"request_id": request_id}) == {"request_id": request_id}


def test_a_mixed_batch_of_generated_ids_survives_redaction() -> None:
    for _ in range(200):
        request_id = uuid.uuid4().hex[:16]
        assert redact_value({"request_id": request_id}) == {"request_id": request_id}


def test_a_phone_number_under_a_generic_key_is_still_redacted() -> None:
    assert redact_value({"detail": "call +8801712345678"}) == {"detail": REDACTED}


def test_a_credential_under_an_identifier_key_is_still_redacted() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"
    assert redact_value({"request_id": jwt}) == {"request_id": REDACTED}


def test_the_redaction_filter_keeps_a_generated_id_in_the_json_line() -> None:
    """End of the chain: the filter preserves the id the middleware set."""
    request_id = uuid.uuid4().hex[:16]
    filt = RedactionFilter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg={"event": "request_complete", "request_id": request_id},
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert record.msg == {"event": "request_complete", "request_id": request_id}


# ---------------------------------------------------------------------------
# F-121 - the web client sends and reflects the header
# ---------------------------------------------------------------------------


def test_the_web_client_sends_and_reflects_the_request_id_header() -> None:
    source = API_TS.read_text(encoding="utf-8")
    assert 'const REQUEST_ID_HEADER = "X-Request-ID";' in source
    # Sent on each of the fetch paths the file owns.
    assert source.count("headers.set(REQUEST_ID_HEADER, requestId)") >= 3
    assert "[REQUEST_ID_HEADER]: requestId," in source  # the renewal call
    # Reflected from the response (the server's echoed value is the logged one).
    assert "res?.headers.get(REQUEST_ID_HEADER)" in source
    # Surfaced to callers so a bug report can quote it.
    assert re.search(r"requestId\?: string;", source)
    assert source.count("correlationId") >= 3
