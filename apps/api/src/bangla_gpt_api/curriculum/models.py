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
    language: str = "bn"
    version: str = "sample-v1"
    content_type: str = "text"


class Chunk(BaseModel):
    id: str
    text: str
    meta: CurriculumMeta
