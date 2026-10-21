from pydantic import BaseModel, Field


class CurriculumMeta(BaseModel):
    curriculum_year: int = Field(ge=2000, le=2100)
    class_level: int = Field(ge=1, le=12)
    subject: str
    book: str
    source: str
    chapter: str = ""
    section: str | None = None
    page: int | None = None
    #: A2-04c: last physical page the chunk's text was extracted from. A chunk
    #: whose text stays inside one page has ``page_end == page``; a chunk that
    #: continues a passage across a page break carries the whole range, so a
    #: citation can point at the pages the evidence actually came from.
    page_end: int | None = None
    language: str = "bn"
    version: str = "sample-v1"
    content_type: str = "text"


class Chunk(BaseModel):
    id: str
    text: str
    meta: CurriculumMeta
