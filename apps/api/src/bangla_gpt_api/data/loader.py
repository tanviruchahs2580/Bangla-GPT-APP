import logging
from pathlib import Path

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.ingestion.text_ingester import TextIngester
from bangla_gpt_api.logging_config import json_log

logger = logging.getLogger(__name__)

SAMPLE_DIR = Path(__file__).parent / "sample_nctb"

SAMPLE_MANIFEST: dict[str, dict] = {
    "class6_science.md": {
        "curriculum_year": 2023,
        "class_level": 6,
        "subject": "science",
        "book": "বিজ্ঞান",
    },
    "class6_math.md": {
        "curriculum_year": 2023,
        "class_level": 6,
        "subject": "mathematics",
        "book": "গণিত",
    },
    "class6_bangla.md": {
        "curriculum_year": 2023,
        "class_level": 6,
        "subject": "bangla",
        "book": "বাংলা ব্যাকরণ",
    },
    "class7_math.md": {
        "curriculum_year": 2023,
        "class_level": 7,
        "subject": "mathematics",
        "book": "গণিত",
    },
    "class7_science.md": {
        "curriculum_year": 2023,
        "class_level": 7,
        "subject": "science",
        "book": "বিজ্ঞান",
    },
    "class8_science.md": {
        "curriculum_year": 2023,
        "class_level": 8,
        "subject": "science",
        "book": "বিজ্ঞান",
    },
    "class8_math.md": {
        "curriculum_year": 2023,
        "class_level": 8,
        "subject": "mathematics",
        "book": "নতুন গণিত",
    },
    "class9_science.md": {
        "curriculum_year": 2023,
        "class_level": 9,
        "subject": "science",
        "book": "বিজ্ঞান",
    },
    "class9_math.md": {
        "curriculum_year": 2023,
        "class_level": 9,
        "subject": "mathematics",
        "book": "সাধারণ গণিত",
    },
    "class10_science.md": {
        "curriculum_year": 2023,
        "class_level": 10,
        "subject": "science",
        "book": "বিজ্ঞান",
    },
    "class10_math.md": {
        "curriculum_year": 2023,
        "class_level": 10,
        "subject": "mathematics",
        "book": "সাধারণ গণিত",
    },
}


def load_sample_corpus() -> list[Chunk]:
    """Load the synthetic sample curriculum used for pipeline verification.

    These files are ORIGINAL synthetic text written for testing the ingestion
    and retrieval pipeline. They are NOT real NCTB textbook content.
    """
    ingester = TextIngester()
    chunks: list[Chunk] = []
    for filename, fields in SAMPLE_MANIFEST.items():
        meta = CurriculumMeta(source=filename, **fields)
        text = (SAMPLE_DIR / filename).read_text(encoding="utf-8")
        chunks.extend(ingester.ingest(text, meta))
    if ingester.dropped_injections:
        # R11: counts only -- never the dropped text.
        json_log(
            logger,
            logging.WARNING,
            "corpus_injection_sentences_dropped",
            count=ingester.dropped_injections,
        )
    return chunks
