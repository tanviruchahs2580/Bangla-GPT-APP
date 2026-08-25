from fastapi import FastAPI, HTTPException

from bangla_gpt_api.config import Settings, get_settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers import ProviderNotConfigured, get_provider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.schemas import AskRequest, AskResponse
from bangla_gpt_api.services.tutor import TutorService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version)

    try:
        provider = get_provider(settings)
    except ProviderNotConfigured:
        provider = None

    index: BM25Index | None = None
    tutor: TutorService | None = None
    if provider is not None:
        index = BM25Index(load_sample_corpus())
        tutor = TutorService(index=index, provider=provider)

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.version,
            "env": settings.env,
        }

    @app.get("/live")
    async def live() -> dict:
        return {"status": "alive"}

    @app.get("/ready")
    async def ready() -> dict:
        if provider is None:
            detail = (
                f"LLM_PROVIDER={settings.llm_provider!r} is not implemented yet. "
                "Set LLM_PROVIDER=mock or configure a supported provider."
            )
            raise HTTPException(status_code=503, detail=detail)
        return {"status": "ready", "provider": provider.name}

    @app.post("/tutor/ask", response_model=AskResponse)
    async def ask(payload: AskRequest) -> AskResponse:
        if tutor is None:
            raise HTTPException(status_code=503, detail="Tutor service unavailable")
        return await tutor.ask(payload.question, payload.class_level, payload.subject)

    return app


app = create_app()
