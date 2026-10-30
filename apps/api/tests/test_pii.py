"""pre-LLM PII redaction.

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


# ---------------------------------------------------------------------------
# F-162: the mutation survivors were all boundary conditions of these three
# patterns. Each case below fails if its boundary moves.
# ---------------------------------------------------------------------------


def test_phone_needs_non_digit_boundaries_but_the_nid_rule_still_catches() -> None:
    """A digit on either side makes it a longer run, not a mobile number.

    Without the lookarounds the phone pattern would fire inside a 12-digit
    run and count a second redaction (and the remaining digits would be
    mangled differently).
    """
    trailing, count_trailing = redact_pii("ref 017123456789 end")
    assert count_trailing == {"phone": 0, "email": 0, "nid": 1}, trailing
    leading, count_leading = redact_pii("ref 1017123456789 end")
    assert count_leading == {"phone": 0, "email": 0, "nid": 1}, leading


def test_email_requires_a_two_character_tld() -> None:
    assert redact_pii("mail a@b.cö here")[1]["email"] == 0
    assert redact_pii("mail a@b.co here")[1]["email"] == 1
    long_tld = "".join(["user@example.", "c" * 63])
    assert redact_pii(long_tld)[1]["email"] == 1


def test_nid_run_length_bounds_are_exact() -> None:
    nine, nine_counts = redact_pii("id 123456789 ok")
    assert nine_counts["nid"] == 0, nine
    ten, ten_counts = redact_pii("id 1234567890 ok")
    assert ten_counts["nid"] == 1, ten
    seventeen, seventeen_counts = redact_pii("id " + "1" * 17 + " ok")
    assert seventeen_counts["nid"] == 1, seventeen
    eighteen, eighteen_counts = redact_pii("id " + "1" * 18 + " ok")
    assert eighteen_counts["nid"] == 0, eighteen


def test_pattern_order_keeps_an_adjacent_address_intact() -> None:
    """The phone pass runs before the email pass by design.

    A pasted "number@domain" is a phone glued to a domain, not an address:
    redacting the phone first leaves "[phone redacted]@example.com", which the
    email pattern cannot match. Swapping the order would label the pair an
    email and leave the phone digits in the text.
    """
    text, counts = redact_pii("যোগাযোগ 01712345678@example.com")
    assert counts == {"phone": 1, "email": 0, "nid": 0}, text
    assert "01712345678" not in text
