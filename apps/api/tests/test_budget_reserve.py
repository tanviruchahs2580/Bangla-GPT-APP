"""BE-01: the AI ledger reserve — in-flight spend is visible and final.

The old shape inserted the ledger row only AFTER the provider answered,
which broke accounting twice: parallel generations all passed the budget
gate off a not-yet-grown ledger (check-then-commit), and a generation that
failed or a stream the student disconnected mid-way left NO row — tokens
the platform paid for vanished from the books. The reserve pattern keeps
one row per generation from before the provider call:

* success: the reserve is finalized in place (one row, real counts);
* provider failure: the row stays at prompt-side spend, zero completion;
* stream disconnect: whatever text reached the student is the final row.

Bengali literals are Unicode escapes only (house rule for API tests).
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiUsage
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, **over) -> Settings:
    base = dict(env="test", database_url=engine_url(tmp_path, "reserve"), jwt_secret=SECRET)
    base.update(over)
    return Settings(**base)


def _student_headers(client: TestClient) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": "s@example.com",
            "password": PASSWORD,
            "name": "Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "s@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ledger(tmp_path) -> list[AiUsage]:
    engine = make_engine(_settings(tmp_path))
    with make_session_factory(engine)() as db:
        return list(db.execute(select(AiUsage).order_by(AiUsage.id)).scalars())


def _exploding_tutor(monkeypatch):
    import bangla_gpt_api.main as main_module
    from bangla_gpt_api.providers.base import LLMProvider as _Base
    from bangla_gpt_api.providers.base import ProviderError as _ProviderError

    class ExplodingProvider(_Base):
        name = "exploding"

        async def generate(self, prompt: str, *, system: str | None = None) -> str:
            raise _ProviderError("upstream down")

    original = main_module.TutorService.__init__

    def inject(self, *args, **kwargs):
        kwargs["provider"] = ExplodingProvider()
        kwargs["fast_provider"] = ExplodingProvider()
        original(self, *args, **kwargs)

    monkeypatch.setattr(main_module.TutorService, "__init__", inject)


def test_ask_provider_failure_still_ledgers_the_prompt_spend(tmp_path, monkeypatch) -> None:
    _exploding_tutor(monkeypatch)
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _student_headers(client)
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 502, res.text

    rows = _ledger(tmp_path)
    assert len(rows) == 1, "a failed generation must still own its ledger line"
    assert rows[0].prompt_tokens > 0
    assert rows[0].completion_tokens == 0


def test_chat_provider_failure_keeps_one_row_not_two(tmp_path, monkeypatch) -> None:
    _exploding_tutor(monkeypatch)
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _student_headers(client)
    client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
        headers=headers,
    )
    rows = _ledger(tmp_path)
    assert len(rows) == 1, "finalize must update the reserve in place, not append"


def test_successful_generation_is_one_finalized_row(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _student_headers(client)
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    rows = _ledger(tmp_path)
    assert len(rows) == 1
    assert rows[0].prompt_tokens > 0 and rows[0].completion_tokens > 0
