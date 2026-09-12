"""PRIV-001: pre-LLM PII redaction.

Pasted phones/emails/NID-like digit runs must never reach an upstream model
provider. The redactor runs at the prompt-build boundary (services/tutor.py);
safety screening still sees the RAW question first, so abuse detection is
unaffected. Curriculum numerals (years, class levels, chapters) must survive.
"""

from bangla_gpt_api.metrics import PII_REDACTED_TOTAL
from bangla_gpt_api.services.pii import redact_pii, redacted_total
from bangla_gpt_api.services.tutor import build_evidence_prompt


def test_redacts_bd_mobile_email_and_nid() -> None:
    text, counts = redact_pii("আমার নম্বর 01712345678, মেইল karim@example.com, NID 19901234567890123")
    assert "01712345678" not in text
    assert "karim@example.com" not in text
    assert "19901234567890123" not in text
    assert counts == {"phone": 1, "email": 1, "nid": 1}
    assert redacted_total(counts) == 3
    assert "[phone redacted]" in text
    assert "[email redacted]" in text
    assert "[nid redacted]" in text


def test_leaves_curriculum_numerals_alone() -> None:
    for benign in [
        "৬ষ্ঠ শ্রেণির বিজ্ঞান ৩য় অধ্যায় কী?",
        "১৯৭১ সালে কী হয়েছিল?",
        "x + y = 10 হলে x কত?",
        "class 6 science chapter 3",
        "২০২৪ সালের পাঠ্যবই",
    ]:
        text, counts = redact_pii(benign)
        assert text == benign, benign
        assert redacted_total(counts) == 0


def test_redaction_is_idempotent() -> None:
    once, _ = redact_pii("call 01812345678 now 01812345678")
    twice, counts2 = redact_pii(once)
    assert twice == once
    assert redacted_total(counts2) == 0


def test_evidence_prompt_strips_pii_and_meters_it() -> None:
    before = PII_REDACTED_TOTAL.labels(kind="phone")._value.get()
    prompt = build_evidence_prompt(
        [],
        "আমার ফোন 01987654321, ভগ্নাংশ কী?",
        history=[{"role": "user", "content": "আগে 01611111111 দিয়েছিলাম"}],
    )
    assert "01987654321" not in prompt
    assert "01611111111" not in prompt
    assert "[phone redacted]" in prompt
    # question + one history turn = 2 removals metered
    after = PII_REDACTED_TOTAL.labels(kind="phone")._value.get()
    assert after - before == 2


def test_evidence_prompt_without_pii_is_unchanged() -> None:
    prompt = build_evidence_prompt([], "ভগ্নাংশ কী?", history=None)
    assert "ভগ্নাংশ কী?" in prompt
    assert "redacted" not in prompt
