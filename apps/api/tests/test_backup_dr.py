"""S5.7 backup/DR guards.

Two honest slices:
* scripts/s3_corpus_sync.sync_corpus is exercised against a stubbed S3
  client (boto3 is intentionally NOT an API dependency, so the real import
  path is never needed here) -- including the path-escape guard.
* the pgBackRest wiring (compose service + stanza conf) cannot drift: the
  archive_command stanza must match the conf, and the compose services must
  exist. The destructive drill itself is scripts/pgbackrest_drill.sh (run
  weekly on staging; verified locally 2026-09-07).
"""

import importlib.util
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
ROOT = API_ROOT.parents[1]


def _load_sync():
    spec = importlib.util.spec_from_file_location(
        "bgpt_s3_corpus_sync", ROOT / "scripts" / "s3_corpus_sync.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3 kwarg names
        return self._pages


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.pages = [
            {"Contents": [{"Key": k} for k in objects]},
        ]

    def get_paginator(self, name: str) -> _FakePaginator:
        assert name == "list_objects_v2"
        return _FakePaginator(self.pages)

    def download_fileobj(self, bucket: str, key: str, fh) -> None:
        fh.write(self.objects[key])


def test_sync_writes_prefix_relative_files(tmp_path) -> None:
    mod = _load_sync()
    objects = {
        "nctb/": b"",  # directory marker, must be skipped
        "nctb/class6/science.md": "\u0995\u09cb\u09b7".encode(),
        "nctb/class10/math.md": b"algebra",
    }
    n = mod.sync_corpus(
        bucket="bgpt-corpus", prefix="nctb/", dest=tmp_path, client=_FakeS3(objects)
    )
    assert n == 2
    assert (tmp_path / "class6" / "science.md").read_bytes() == "\u0995\u09cb\u09b7".encode()
    assert (tmp_path / "class10" / "math.md").read_bytes() == b"algebra"


def test_sync_refuses_keys_escaping_dest(tmp_path) -> None:
    mod = _load_sync()
    objects = {
        "nctb/ok.md": b"fine",
        "nctb/../evil.md": b"nope",
        "nctb/deep/../../evil2.md": b"nope",
    }
    n = mod.sync_corpus(
        bucket="bgpt-corpus", prefix="nctb/", dest=tmp_path / "corpus", client=_FakeS3(objects)
    )
    assert n == 1
    assert (tmp_path / "corpus" / "ok.md").exists()
    assert not (tmp_path / "evil.md").exists()
    assert not (tmp_path / "corpus" / "evil2.md").exists()
    assert not (tmp_path.parent / "evil.md").exists()


def test_pgbackrest_wiring_cannot_drift() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    conf = (ROOT / "deploy" / "postgres" / "pgbackrest.conf").read_text(encoding="utf-8")
    dockerfile = (ROOT / "deploy" / "postgres" / "Dockerfile").read_text(encoding="utf-8")
    # conf is a complete stanza with repo + cluster coordinates
    for token in ("[bgpt]", "[global]", "repo1-path=", "pg1-path=", "pg1-user="):
        assert token in conf, f"missing in pgbackrest.conf: {token}"
    # image ships the binary + baked config (no host bind mounts)
    assert "pgbackrest" in dockerfile and "COPY pgbackrest.conf" in dockerfile
    # compose: WAL archiving on the DB + the stanza the sidecar uses must match
    assert "archive_mode=on" in compose
    assert "wal_level=replica" in compose
    assert "pgbackrest --stanza=bgpt archive-push" in compose
    assert "pgbackrest:" in compose and "pgbackrest_nightly.sh" in compose
    assert "[bgpt]" in conf  # the archive-push stanza exists in the conf


def test_drill_script_is_self_contained() -> None:
    drill = (ROOT / "scripts" / "pgbackrest_drill.sh").read_text(encoding="utf-8")
    # no host bind mounts (Windows-fragile): everything comes from the image/volumes
    assert "pgbackrest.conf:ro" not in drill
    assert "stanza-create" in drill and "backup --type=full" in drill
    assert "pgbackrest --stanza=bgpt --delta" in drill
    # and it actually asserts the WAL-replay markers, not just exit codes
    assert "pre-backup,post-backup" in drill
