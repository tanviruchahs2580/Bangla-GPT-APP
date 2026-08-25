"""NCTB acquisition, processing and corpus construction subsystem.

All artifacts acquired here carry full provenance: official source URL,
retrieval timestamp, SHA-256 hash and recorded edition/year exactly as
published by NCTB. Nothing is invented; unknown fields stay UNKNOWN.
"""

from bangla_gpt_api.nctb.sources import (
    ALL_ARTIFACTS,
    HSC_ARTIFACTS,
    SECONDARY_ARTIFACTS,
    SOURCE_PAGES,
)

__all__ = ["SOURCE_PAGES", "SECONDARY_ARTIFACTS", "HSC_ARTIFACTS", "ALL_ARTIFACTS"]
