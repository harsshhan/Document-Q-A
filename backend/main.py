"""FastAPI application entrypoint.

Run locally with:
    uvicorn main:app --reload
"""

from fastapi import FastAPI

from api.routes.ask import router as ask_router
from api.routes.auth import router as auth_router
from api.routes.documents import router as documents_router
from core.config import validate_startup_settings


def create_app() -> FastAPI:
    # Refuse to start with an unsafe/missing signing key instead of falling back
    # to a weak default.
    validate_startup_settings()

    app = FastAPI(
        title="Document Q&A API",
        version="1.0.0",
        description=(
            "Authenticated RAG backend: PDF ingestion, Gemini embeddings and "
            "PostgreSQL/pgvector retrieval."
        ),
    )

    @app.get("/", tags=["health"])
    def home() -> dict[str, str]:
        return {"message": "Backend running"}

    app.include_router(auth_router)
    app.include_router(documents_router)
    app.include_router(ask_router)

    return app


app = create_app()
