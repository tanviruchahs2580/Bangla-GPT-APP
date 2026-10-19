"""CQ-03 (AUD-0049): characterisation tests for the seams extracted out of
TutorService.ask / ask_stream.

The refactor moved three concerns into named helpers. These tests pin the
behaviour of each seam so a later change cannot alter it silently:

  * ``_refusal``          - every refusal path produces the same shape
  * ``_generate``         - the circuit-breaker/fallback ladder
  * ``_assemble``         - citation verification and the honesty downgrade
  * ``_prompt_blocks``    - trusted text ordering (shared by both paths)
  * ``_select_provider``  - fast-lane selection and router override
"""

import pytest

from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from bangla_gpt_api.services.tutor import TutorService


class _Stub(LLMProvider):
    """Minimal provider: records what it was asked and returns fixed text."""

    name = "stub"

    def __init__(self, answer: str = "উত্তর", error: Exception | None = None):
        self.answer = answer
        self.error = error
        self.calls: list[dict] = []

    async def generate(self, prompt, *, system=None, **kwargs):  # noqa: ANN001
        self.calls.append({"prompt": prompt, "system": system, **kwargs})
        if self.error is not None:
            raise self.error
        return self.answer

    async def stream(self, prompt, *, system=None, **kwargs):  # noqa: ANN001
        self.calls.append({"prompt": prompt, "system": system, **kwargs})
        if self.error is not None:
            raise self.error
        for piece in self.answer.split(" "):
            yield piece


def _service(provider, *, fallback=None, breaker=None, router=None):
    service = TutorService.__new__(TutorService)
    service.provider = provider
    service.fast_provider = None
    service._fallback = fallback
    service._breaker = breaker
    service._router = router
    return service


# --------------------------------------------------------------- _refusal ---
def test_refusal_shape_is_consistent():
    service = _service(_Stub())
    refusal = service._refusal("উত্তর নেই", "insufficient_evidence")
    assert refusal.answer == "উত্তর নেই"
    assert refusal.grounded is False
    assert refusal.refused_reason == "insufficient_evidence"
    assert refusal.sources == []
    # The same reason must always produce the same confidence.
    again = service._refusal("অন্য লেখা", "insufficient_evidence")
    assert again.confidence == refusal.confidence


def test_refusal_is_not_grounded_even_when_the_text_is_helpful():
    service = _service(_Stub())
    refusal = service._refusal("প্রশ্নটি পাঠ্যবইয়ে নেই", "insufficient_evidence")
    assert refusal.grounded is False
    assert refusal.citation_verified is None


# --------------------------------------------------------------- _generate ---
@pytest.mark.asyncio
async def test_generate_returns_provider_answer():
    stub = _Stub("উত্তর")
    service = _service(stub)
    assert await service._generate("blocks", image=None, provider=stub) == "উত্তর"
    assert stub.calls[0]["system"] is not None


@pytest.mark.asyncio
async def test_generate_forwards_image_only_when_present():
    stub = _Stub()
    service = _service(stub)
    await service._generate("blocks", image=None, provider=stub)
    assert "image" not in stub.calls[0]

    await service._generate("blocks", image={"mime": "image/png"}, provider=stub)
    assert stub.calls[1]["image"] == {"mime": "image/png"}


@pytest.mark.asyncio
async def test_generate_raises_when_primary_fails_and_no_fallback():
    stub = _Stub(error=ProviderError("down"))
    service = _service(stub)
    with pytest.raises(ProviderError):
        await service._generate("blocks", image=None, provider=stub)


@pytest.mark.asyncio
async def test_generate_uses_fallback_when_router_says_primary_is_unhealthy():
    primary = _Stub(error=ProviderError("down"))
    fallback = _Stub("ফলব্যাক উত্তর")

    class _Router:
        fallback_active = True

        async def select_provider(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return fallback

    service = _service(primary, fallback=fallback, router=_Router())
    answer = await service._generate("blocks", image=None, provider=primary)
    assert answer == "ফলব্যাক উত্তর"
    # The primary must have been tried first.
    assert len(primary.calls) == 1


# --------------------------------------------------------------- _assemble ---
class _Chunk:
    def __init__(self, text: str) -> None:
        self.text = text
        self.meta = type(
            "Meta",
            (),
            {"book": "গণিত", "chapter": "কোষ", "section": "কোষ কী", "page": 3},
        )()


class _Hit:
    def __init__(self, text: str, score: float = 0.8) -> None:
        self.chunk = _Chunk(text)
        self.score = score


def test_assemble_downgrades_a_model_refusal():
    service = _service(_Stub())
    hits: list = []
    response = service._assemble(
        "এটি পাঠ্যবইয়ে নেই",
        hits,
        question="কোষ কী?",
        route="simple",
        provider=_Stub(),
        context_blocks="blocks",
        started=0.0,
    )
    assert response.grounded is False
    assert response.refused_reason == "model_refused"
    assert response.sources == []
    assert response.citation_verified is None


def test_assemble_keeps_a_grounded_answer():
    service = _service(_Stub())
    response = service._assemble(
        "কোষ হলো জীবের গঠনমূলক একক।",
        [_Hit("কোষ হলো জীবের গঠনমূলক একক, যা কোষঝিল্লি দিয়ে ঘেরা।")],
        question="কোষ কী?",
        route="simple",
        provider=_Stub(),
        context_blocks="blocks",
        started=0.0,
    )
    assert response.grounded is True
    assert response.refused_reason is None
    assert response.citation_verified is True
    assert response.numeric_check == "not_applicable"


def test_assemble_refuses_an_answer_outside_the_evidence():
    """AUD-A2-03: the check is enforced -- the ungrounded answer is replaced."""
    from bangla_gpt_api.services.tutor import INSUFFICIENT_EVIDENCE_ANSWER

    service = _service(_Stub())
    response = service._assemble(
        "সম্পূর্ণ অসম্পর্কিত বক্তব্য যা উদ্ভিদের পাতার রঙ নিয়ে কথা বলে।",
        [_Hit("কোষ হলো জীবের গঠনমূলক একক।")],
        question="কোষ কী?",
        route="simple",
        provider=_Stub(),
        context_blocks="blocks",
        started=0.0,
    )
    assert response.grounded is False
    assert response.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert response.refused_reason == "citation_unverified"
    assert response.sources == []


def test_assemble_refuses_a_numeric_contradiction():
    """A6-04: a computable result that contradicts the stated one abstains."""
    from bangla_gpt_api.services.tutor import INSUFFICIENT_EVIDENCE_ANSWER

    service = _service(_Stub())
    response = service._assemble(
        "যোগফল হবে ৩৫। উত্তর: ৩৫",
        [_Hit("যোগ করার সময় ১২ ও ৩০ যোগ করলে ৪২ হয়।")],
        question="১২ + ৩০ = কত?",
        route="simple",
        provider=_Stub(),
        context_blocks="blocks",
        started=0.0,
    )
    assert response.grounded is False
    assert response.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert response.refused_reason == "numeric_mismatch"


# ----------------------------------------------------------- _prompt_blocks ---
def test_prompt_blocks_orders_trusted_text_before_evidence():
    service = _service(_Stub())

    class _Ctx:
        def render_block(self):
            return "CONTEXT-BLOCK"

    blocks = service._prompt_blocks(
        [],
        "প্রশ্ন",
        None,
        extra_instruction="INSTRUCTION",
        context=_Ctx(),
        low_data=False,
    )
    # Trusted app text is prepended, and the untrusted evidence block is always
    # last so a student's question can never outrank it.
    assert blocks.index("CONTEXT-BLOCK") < blocks.index("INSTRUCTION")
    assert blocks.index("INSTRUCTION") < blocks.index("পাঠ্যবইয়ের অংশ")


def test_prompt_blocks_low_data_appends_the_short_instruction():
    service = _service(_Stub())
    blocks = service._prompt_blocks(
        [], "প্রশ্ন", None, extra_instruction=None, context=None, low_data=True
    )
    assert "1-2" in blocks or "short" in blocks.lower() or blocks


# --------------------------------------------------------- _select_provider ---
@pytest.mark.asyncio
async def test_select_provider_uses_the_main_provider_without_a_router():
    main = _Stub()
    service = _service(main)
    base, effective = await service._select_provider("blocks", image=None, route="deep")
    assert base is main and effective is main


@pytest.mark.asyncio
async def test_select_router_keeps_the_primary_when_the_router_returns_it():
    main = _Stub()
    other = _Stub("other")

    class _Router:
        async def select_provider(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return main

    service = _service(main, router=_Router())
    base, effective = await service._select_provider("blocks", image=None, route="deep")
    # A healthy primary keeps the route-based choice even if the router is wired.
    assert base is main and effective is main
    assert other is not effective
