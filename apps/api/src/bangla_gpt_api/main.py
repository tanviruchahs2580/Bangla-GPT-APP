from fastapi import FastAPI, HTTPException

from bangla_gpt_api.config import Settings, get_settings
from bangla_gpt_api.providers import ProviderNotConfigured, get_provider


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version)

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
        try:
            provider = get_provider(settings)
        except ProviderNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ready", "provider": provider.name}

    return app


app = create_app()
