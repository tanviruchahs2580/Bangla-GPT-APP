"""A11-03/A11-04: scripted dialogue tests for the pedagogy guardrails.

Live-model A/B is impossible inside CI (no key), so the dialogues are scripted
at the provider seam: a provider whose REPLIES are fixed while its RECORDED
REQUESTS are asserted, which is exactly what the app controls. The route-level
test drives the real chat endpoints with strategy chips and proves the stored
answers differ per chip (the closest thing to an A/B a hermetic suite can
honestly run; the live A/B evidence is .audit/evidence/R3-ws1-a11-live-ab.txt).

Pinned here:

* a three-turn homework dialogue -- the hint-first instruction is on every
  turn, the first answer is a hint (no full solution), and after the student's
  attempt the follow-up request still carries the instruction plus history;
* a study-mode dialogue -- the step-by-step instruction reaches the request
  and the answer keeps the step structure;
* tone -- no shaming words in any pedagogy or refusal copy;
* strategy chips -- two chips through the real routes store different answers.
"""

from __future__ import annotations

from typing import ClassVar

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services import teach_strategy
from bangla_gpt_api.services.context import RequestContext
from bangla_gpt_api.services.safety import SAFETY_ANSWER, SELF_HARM_ANSWER
from bangla_gpt_api.services.tutor import (
    GOAL_STUDY,
    HINT_FIRST_INSTRUCTION,
    STUDY_STEPS_INSTRUCTION,
    TutorService,
)

CHUNK_TEXT = "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক। কোষেই সকল জৈবনিক কাজ ঘটে।"
HINT_REPLY = "ইঙ্গিত: কোষ হলো জীবদেহের গঠনগত একক — ক্রিয়াগত অংশটি নিজে খুঁজে বের করো, তারপর বলো।"
HOMEWORK_QUESTION = "আমার হোমওয়ার্ক: কোষ কী? উত্তর দাও"
STUDENT_ATTEMPT = "আমি চেষ্টা করেছি: কোষ হলো জীবদেহের গঠনগত একক।"
STEPS_REPLY = CHUNK_TEXT + " ধাপ ১: অন্তর্ভুক্তি। ধাপ ২: কাজ।"
QUESTION = "কোষ কী?"
PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="book",
        source="sample",
        chapter="ch1",
        section="s1",
        page=1,
    )


class _Index:
    chunks: ClassVar[list[Chunk]] = [Chunk(id="c1", meta=_meta(), text=CHUNK_TEXT)]

    def search(self, _query, **_kwargs) -> list[Hit]:
        return [Hit(chunk=self.chunks[0], score=1.0)]


class _ScriptedProvider:
    """Fixed replies, recorded requests (deterministic dialogue)."""

    name = "scripted"
    supports_vision = False
    supports_sampling = False

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def generate(self, prompt, *, system=None, **_kwargs):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else CHUNK_TEXT

    async def stream(self, prompt, *, system=None, **_kwargs):
        self.prompts.append(prompt)
        yield self.replies.pop(0) if self.replies else CHUNK_TEXT


def _service(provider, **kwargs) -> TutorService:
    return TutorService(
        index=_Index(), provider=provider, min_coverage=0.0, min_score=0.0, **kwargs
    )


async def test_homework_dialogue_hint_then_attempt_then_full_solution() -> None:
    provider = _ScriptedProvider([HINT_REPLY, STEPS_REPLY])
    service = _service(provider)
    first = await service.ask(HOMEWORK_QUESTION, 6, "science")
    assert HINT_FIRST_INSTRUCTION in provider.prompts[0]
    assert provider.prompts[0].index(HINT_FIRST_INSTRUCTION) < provider.prompts[0].index(
        "<evidence>"
    )
    assert first.answer == HINT_REPLY, "turn 1 must be the hint, not a full solution"
    assert CHUNK_TEXT not in first.answer

    # Prior turns only -- exactly what the route's _chat_history hands over.
    # The student's immediate attempt carries no homework cue of its own; the
    # PREVIOUS user turn does, and that keeps the guardrail alive (A11-03).
    history = [
        {"role": "user", "content": HOMEWORK_QUESTION},
        {"role": "assistant", "content": HINT_REPLY},
    ]
    second = await service.ask(STUDENT_ATTEMPT, 6, "science", history=history)
    second_request = provider.prompts[-1]
    assert HINT_FIRST_INSTRUCTION in second_request, "guardrail survives the dialogue"
    assert "পূর্ববর্তী কথোপকথন" in second_request  # history block rendered
    assert second.answer == STEPS_REPLY


async def test_study_mode_dialogue_keeps_step_structure() -> None:
    provider = _ScriptedProvider([STEPS_REPLY])
    service = _service(provider)
    context = RequestContext(role="student", class_level=6, subject="science", goal=GOAL_STUDY)
    answer = await service.ask(QUESTION, 6, "science", context=context)
    assert STUDY_STEPS_INSTRUCTION in provider.prompts[0]
    assert "goal=study" in provider.prompts[0]
    assert "ধাপ" in answer.answer  # step marker from the scripted reply


def test_pedagogy_and_refusal_copy_contain_no_shaming_words() -> None:
    shame = [
        "বোকা",
        "অলস",
        "লজ্জা",
        "তুমি পারবে না",
        "stupid",
        "lazy",
        "shame",
        "you failed",
    ]
    copies = [HINT_FIRST_INSTRUCTION, STUDY_STEPS_INSTRUCTION, SAFETY_ANSWER, SELF_HARM_ANSWER]
    for copy in copies:
        for word in shame:
            assert word not in copy, f"shaming word {word!r} in a pedagogy/refusal copy"


# ---------------------------------------------------- route-level A/B -------


class _StrategyEchoProvider:
    """Answers CHANGE with the strategy instruction in the prompt.

    A real model would paraphrase the instruction; for a hermetic test the
    observable behaviour is the contract the app owns: the chip's instruction
    reaches the provider, and the answer that comes back (and is persisted) is
    bound to that chip.
    """

    name = "strategy-echo"
    supports_vision = False
    supports_sampling = False

    def __init__(self) -> None:
        self.inner = MockLLMProvider()
        self.prompts: list[str] = []

    def _reply(self, prompt: str) -> str:
        # Quote the retrieved evidence (so the answer can pass the grounding
        # check, like the mock provider does) and append the chip's
        # instruction slice, which is the observable per-chip difference.
        import re

        blocks = re.findall(r"<evidence>(.*?)</evidence>", prompt, re.DOTALL)
        body = blocks[0].strip() if blocks else CHUNK_TEXT
        for line in prompt.splitlines():
            if line.startswith("শিক্ষক-নির্দেশ"):
                return f"{body} [strategy] {line[:40]}"
        return body

    async def generate(self, prompt, *, system=None, **kwargs):
        self.prompts.append(prompt)
        return self._reply(prompt)

    async def stream(self, prompt, *, system=None, **kwargs):
        self.prompts.append(prompt)
        yield self._reply(prompt)


def _app(monkeypatch, tmp_path, provider) -> TestClient:
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    monkeypatch.setattr("bangla_gpt_api.main.get_fast_provider", lambda s: provider)
    settings = Settings(env="test", database_url=f"sqlite:///{tmp_path}/ab.db", jwt_secret=SECRET)
    return TestClient(create_app(settings))


def _register_login(client: TestClient, email: str) -> dict[str, str]:
    body = {
        "email": email,
        "password": PASSWORD,
        "name": "শিক্ষার্থী",
        "role": "student",
        "class_level": 6,
        "guardian_consent": True,
    }
    assert client.post("/auth/register", json=body).status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_strategy_chips_change_the_stored_answer_through_the_route(monkeypatch, tmp_path) -> None:
    provider = _StrategyEchoProvider()
    client = _app(monkeypatch, tmp_path, provider)
    headers = _register_login(client, "ab@test.local")
    conv = client.post("/tutor/conversations", json={}, headers=headers).json()["id"]
    for key in ("steps", "example"):
        res = client.post(
            f"/tutor/conversations/{conv}/messages",
            json={"message": QUESTION, "strategy": key},
            headers=headers,
        )
        assert res.status_code == 200, res.text
    messages = client.get(f"/tutor/conversations/{conv}/messages", headers=headers).json()
    answers = [m["content"] for m in messages if m["role"] == "assistant"]
    assert len(answers) == 2 and answers[0] != answers[1], "each chip must change the answer"
    instruction_steps = teach_strategy.explicit_strategy_instruction("steps")[:40]
    instruction_example = teach_strategy.explicit_strategy_instruction("example")[:40]
    assert instruction_steps in answers[0]
    assert instruction_example in answers[1]
    # A11-04 regression: if the first answer had to be regenerated, the chip's
    # instruction must survive the retry prompt (it used to be replaced).
    assert all(answer.startswith("কোষ") for answer in answers)
    retry_prompts = [p for p in provider.prompts if "পূর্বের উত্তরটি" in p]
    assert all(instruction_steps in p or instruction_example in p for p in retry_prompts)


# --------------------------------------------- live A/B (needs a key) -------


def test_live_strategy_ab_evidence_is_recorded_for_the_audit() -> None:
    """The live A/B ran out-of-band (no CI key); its numbers must be committed.

    The raw capture lives in the audit scratch directory (`.audit/evidence/`),
    which a clean checkout does not carry -- asserting on it made this test
    fail on every CI run. The durable record is the tracked doc, so that is
    what is pinned here: CI verifies the record exists and carries the measured
    numbers, and the numbers themselves stay reviewable in git history.
    """
    from pathlib import Path

    doc = Path(__file__).resolve().parents[3] / "docs" / "evaluation" / "pedagogy-ab.md"
    assert doc.is_file(), "the pedagogy A/B record must be committed"
    text = doc.read_text(encoding="utf-8")
    assert "3/3 distinct answers" in text, "chip A/B result missing from the record"
    assert "**0.00**" in text, "hint-first ON leak rate missing from the record"
    assert "0.20" in text, "hint-first OFF leak rate missing from the record"
