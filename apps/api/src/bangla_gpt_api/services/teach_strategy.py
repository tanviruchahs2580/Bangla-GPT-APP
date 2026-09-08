"""S1.5 — adaptive re-teach strategies for the 'আমি বুঝিনি' loop.

The conversation stores which explanation strategy was used last
(Conversation.last_strategy). When a student says they did not understand,
the NEXT strategy in the cycle is chosen and a teacher-level instruction is
injected into the tutor prompt so the same failed approach is never repeated.
"""

# (key, Bengali display name) — order defines the fallback cycle.
STRATEGIES: tuple[tuple[str, str], ...] = (
    ("simple", "সহজ ভাষা"),
    ("example", "বাস্তব উদাহরণ"),
    ("visual", "ভিজ্যুয়াল বর্ণনা"),
    ("story", "গল্প আকারে"),
    ("steps", "ধাপে ধাপে"),
)

_NAMES: dict[str, str] = dict(STRATEGIES)


def next_strategy(last: str | None) -> str:
    """Return the strategy key to try after `last` failed (cycles)."""
    if last is None or last not in _NAMES:
        return STRATEGIES[0][0]
    keys = [k for k, _ in STRATEGIES]
    return keys[(keys.index(last) + 1) % len(keys)]


def strategy_name(key: str) -> str:
    return _NAMES.get(key, key)


def reteach_instruction(last: str | None) -> tuple[str, str]:
    """Pick the next strategy and build the injected teacher instruction.

    Returns (strategy_key, instruction). The instruction explicitly names the
    failed approach so the model does not repeat it (spec 1.5 PASS-WHEN:
    same question twice ⇒ a different strategy is injected).
    """
    key = next_strategy(last)
    if last is not None and last in _NAMES:
        instruction = (
            f"শিক্ষক-নির্দেশ: আগের পদ্ধতি ({strategy_name(last)}) বুঝতে করোনি — "
            f"এবার অন্য পদ্ধতি ({strategy_name(key)}) ব্যবহার করে বোঝাও।"
        )
    else:
        instruction = f"শিক্ষক-নির্দেশ: পুরোপুরি সহজভাবে, {strategy_name(key)} পদ্ধতিতে বোঝাও।"
    return key, instruction
