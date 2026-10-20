"""Token and word sizing for the NCTB chunker (A3-01).

Extracted from ``chunking.py`` for cohesion. Sizes are measured with the
configured ``services.context.TokenCounter`` (calibrated heuristic upper bound
by default, the vendor counter when one is registered). The token defaults are
derived from the historical word defaults via the measured tokens-per-word
ratio, so the unit change is not a silent size change; word sizing remains
selectable as the documented fallback.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bangla_gpt_api.services.context import TokenCounter, token_counter

MIN_WORDS = 60
MAX_WORDS = 400
TARGET_TOKENS = 612
MIN_TOKENS = 167
MAX_TOKENS = 1112

TARGET_WORDS = 220


#: ``services.context.TokenCounter`` — the heuristic upper bound by default,
#: the vendor counter when one is registered (A5-01). The token defaults are
#: DERIVED from the word defaults so the unit change is not a silent size
#: change: the served 797-chunk artifact measures 2.7812 tokens/word
#: (2026-10-20, heuristic-2.5cpt counter), giving 220 -> 612, 60 -> 167 and
#: 400 -> 1112. Word sizing stays available and documented as the fallback:
#: passing ``target_words`` selects it (the ablation's historical configs).
TOKENS_PER_WORD_MEASURED = 2.7812


#: measured in the chunk-size ablation (scripts/ablate_nctb_chunking.py).
DEFAULT_OVERLAP_WORDS = 0


#: target (the historical "target_words + 120" slack, expressed as a ratio so
#: it works in both units).
FLUSH_AHEAD_RATIO = 1.545


def _word_window(text: str, size: int) -> list[str]:
    """Hard word-boundary windowing, used only where no sentence fits."""
    words = text.split(" ")
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def _token_window(text: str, max_tokens: int, counter: TokenCounter) -> list[str]:
    """Hard token-bounded windowing, used only where no sentence fits.

    Words are added while the measured piece stays within ``max_tokens``; a
    single word over the budget still gets its own piece (never dropped).
    """
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split(" "):
        if current and counter.count(" ".join([*current, word])) > max_tokens:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


@dataclass(frozen=True)
class _Sizing:
    """How one chunking call measures size (A3-01).

    ``unit`` is ``"tokens"`` (default: the configured TokenCounter) or
    ``"words"`` (the documented fallback, selected by passing ``target_words``
    — the ablation's historical configurations). ``measure`` counts a piece;
    ``window`` is the no-punctuation splitter for over-long sentences.
    """

    unit: str
    target: int
    minimum: int
    maximum: int
    measure: Callable[[str], int]
    window: Callable[[str, int], list[str]]
    counter_name: str = ""
    #: the TokenCounter the measurement came from (None in word mode)
    counter: TokenCounter | None = None

    @property
    def flush_ahead(self) -> int:
        """Projected size past which the page loop flushes early."""
        return self.target + round(self.target * (FLUSH_AHEAD_RATIO - 1.0))

    def meets_minimum(self, measured: int, words: int) -> bool:
        """True when a block may stand alone.

        Token mode also honours the historical WORD floor (``MIN_WORDS``): a
        page of short words reaches 60 words long before it reaches
        ``MIN_TOKENS``, and the word-based minimum must keep behaving exactly
        as it did — the unit change is not a silent behaviour change (A3-01).
        Word mode is the historical test, unchanged.
        """
        if measured >= self.minimum:
            return True
        return self.unit == "tokens" and words >= MIN_WORDS

    def below_minimum(self, text: str) -> bool:
        return not self.meets_minimum(self.measure(text), len(text.split(" ")))


def _resolve_sizing(
    *,
    target_tokens: int | None = None,
    min_tokens: int | None = None,
    max_tokens: int | None = None,
    target_words: int | None = None,
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
    counter: TokenCounter | None = None,
) -> _Sizing:
    if target_words is not None:
        return _Sizing(
            unit="words",
            target=target_words,
            minimum=min_words,
            maximum=max_words,
            measure=lambda piece: len(piece.split(" ")),
            window=_word_window,
        )
    resolved = counter or token_counter()
    return _Sizing(
        unit="tokens",
        target=TARGET_TOKENS if target_tokens is None else target_tokens,
        minimum=MIN_TOKENS if min_tokens is None else min_tokens,
        maximum=MAX_TOKENS if max_tokens is None else max_tokens,
        measure=resolved.count,
        window=lambda piece, size: _token_window(piece, size, resolved),
        counter_name=resolved.name,
        counter=resolved,
    )
