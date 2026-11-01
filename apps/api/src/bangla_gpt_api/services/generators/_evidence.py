"""The one place the evidence-block wire format is written (F-072).

Every document generator embeds retrieved textbook chunks inside the delimiters
the prompt promises, and each prompt-builder had its own copy of the join. One
copy is the contract: change the delimiter or the sanitisation here and every
generator changes with it.

The mock provider and the tutor read the same two constants from
``services.tutor``, so the character strings themselves still live there.
"""

from collections.abc import Iterable
from typing import Any

from bangla_gpt_api.services.tutor import EVIDENCE_CLOSE, EVIDENCE_OPEN, sanitize_evidence


def evidence_block(text: str) -> str:
    """Wrap one chunk of evidence text in the prompt's delimiters."""
    return f"{EVIDENCE_OPEN}\n{sanitize_evidence(text)}\n{EVIDENCE_CLOSE}"


def evidence_blocks(hits: Iterable[Any]) -> str:
    """Join retrieved hits into the ``<evidence>...</evidence>`` prompt block."""
    return "\n".join(evidence_block(hit.chunk.text) for hit in hits)
