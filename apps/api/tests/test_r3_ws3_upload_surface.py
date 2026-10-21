"""R3 / WS3 B-12: the upload surface is parse-and-discard, pinned by scan.

The audit's B-12 gap was precise: server-side validation and image handling
exist (mime allowlist, size cap, magic-byte sniff, metadata-free re-encode),
but nothing *stated or enforced* that no uploaded byte is ever persisted --
which is what makes randomized storage names and path traversal moot, and what
makes an antivirus hook unnecessary today.

These tests pin the properties that make that true, so a future change that
introduces file persistence (or a storage SDK) fails here and must bring the
storage hardening and its AV seam with it.
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

SRC = Path(__file__).resolve().parents[1] / "src" / "bangla_gpt_api"

#: Modules that handle user-supplied bytes.
UPLOAD_MODULES = (
    "routers/class_import.py",
    "routers/common.py",
    "providers/image_safety.py",
)

#: Filesystem-writing calls that must not appear in an upload handler.
FORBIDDEN_WRITE_CALLS = (
    "write_bytes",
    "shutil.copy",
    "shutil.copyfile",
    "shutil.move",
    "os.rename",
    "os.replace",
    "os.remove",
    "NamedTemporaryFile",
    "mkstemp",
    "urlretrieve",
)

#: Object-storage SDKs. If one appears, the AV hook and path-safety work must
#: land with it (see docs/architecture.md "Upload surface").
STORAGE_SDKS = ("boto3", "botocore", "minio", "azure", "google.cloud.storage", "s3fs")

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _tree(rel: str) -> ast.Module:
    return ast.parse((SRC / rel).read_text(encoding="utf-8"))


def _calls(tree: ast.Module) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            out.add(ast.unparse(node.func))
    return out


def _open_calls_with_a_literal_path(tree: ast.Module) -> list[str]:
    """``open()`` / ``X.open()`` calls whose first argument is a literal path.

    ``Image.open(io.BytesIO(...))`` is an in-memory decode and must stay
    allowed; a call that names a path on disk is what this scan forbids.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        if name != "open" and not name.endswith(".open"):
            continue
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.append(name)
    return found


def test_upload_modules_never_write_to_the_filesystem() -> None:
    problems = []
    for rel in UPLOAD_MODULES:
        for call in _calls(_tree(rel)):
            if any(call.endswith(name) or call == name for name in FORBIDDEN_WRITE_CALLS):
                problems.append(f"{rel}: {call}")
        problems += [f"{rel}: {call}()" for call in _open_calls_with_a_literal_path(_tree(rel))]
    assert not problems, f"upload modules write to disk: {problems}"


def test_upload_modules_never_join_request_data_into_a_path() -> None:
    problems = []
    for rel in UPLOAD_MODULES:
        text = (SRC / rel).read_text(encoding="utf-8")
        for needle in ("os.path.join", "Path(", "filename", ".name:"):
            if needle in text:
                problems.append(f"{rel}: contains {needle!r}")
    assert not problems, f"upload path handling appeared: {problems}"


def test_no_storage_sdk_is_imported_without_the_av_seam() -> None:
    imported = []
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
    found = sorted({mod for mod in imported if mod.split(".")[0] in STORAGE_SDKS})
    assert not found, (
        f"object-storage SDK imported ({found}); storage needs randomized names, "
        "path-safety and the antivirus hook before it ships"
    )


def test_the_documented_decision_exists() -> None:
    doc = (Path(__file__).resolve().parents[3] / "docs" / "architecture.md").read_text(
        encoding="utf-8"
    )
    assert "### Upload surface (B-12)" in doc
    assert "parse-and-discard" in doc
    assert "antivirus hook" in doc


def test_the_csv_route_ignores_a_filename_and_multipart_bodies(tmp_path) -> None:
    """A browser-style multipart upload is refused explicitly (415), never parsed."""
    app = create_app(
        Settings(
            env="test",
            llm_provider="mock",
            jwt_secret=SECRET,
            database_url=f"sqlite:///{tmp_path}/upload.db",
        )
    )
    with TestClient(app) as client:
        assert (
            client.post(
                "/auth/register",
                json={
                    "email": "upload@example.test",
                    "password": PASSWORD,
                    "name": "Teacher",
                    "role": "teacher",
                },
            ).status_code
            == 201
        )
        token = client.post(
            "/auth/login", json={"email": "upload@example.test", "password": PASSWORD}
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        room = client.post(
            "/teacher/classrooms", json={"class_level": 6, "section": "UP"}, headers=headers
        ).json()["id"]

        # A multipart body carrying a hostile filename: refused by content
        # type, and the filename never reaches any code path.
        body = io.BytesIO(b"name,email\r\nx,y@example.com\r\n")
        res = client.post(
            f"/teacher/classrooms/{room}/import-file",
            files={"file": ("../../etc/passwd", body, "text/csv")},
            headers=headers,
        )
        assert res.status_code == 415, res.text

        # A Content-Disposition filename on a raw CSV body is simply ignored.
        res = client.post(
            f"/teacher/classrooms/{room}/import-file",
            content=b"name,email\r\n",
            headers={
                **headers,
                "Content-Type": "text/csv",
                "Content-Disposition": 'attachment; filename="../../etc/passwd"',
            },
        )
        assert res.status_code == 422, res.text  # no data rows, filename ignored


@pytest.mark.parametrize("rel", UPLOAD_MODULES)
def test_upload_modules_are_covered_by_this_scan(rel: str) -> None:
    """Guard the guard: a renamed upload module must not silently leave the scan."""
    assert (SRC / rel).exists(), f"{rel} no longer exists; update UPLOAD_MODULES"
