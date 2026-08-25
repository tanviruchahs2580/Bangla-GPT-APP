from pathlib import Path

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.ingestion.text_ingester import TextIngester

SAMPLE_DIR = Path(__file__).parent / "sample_nctb"

SAMPLE_MANIFEST: dict[str, dict] = {
    "class6_science.md": {
        "curriculum_year": 2023,
        "class_level": 6,
        "subject": "science",
        "book": "বিজ্ঞান",
    },
    "class7_math.md": {
        "curriculum_year": 2023,
        "class_level": 7,
        "subject": "mathematics",
        "book": "গণিত",
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
    return chunks
