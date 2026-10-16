from __future__ import annotations

from app.core.config import settings


def create_gemini_embeddings():
    provider = settings.embedding_provider.strip().lower()
    if provider != "gemini":
        raise RuntimeError(
            f"Unsupported EMBEDDING_PROVIDER '{settings.embedding_provider}'. "
            "Set EMBEDDING_PROVIDER=gemini; mock embeddings are disabled."
        )
    api_key = settings.embedding_api_key
    if not api_key or not api_key.strip():
        raise RuntimeError(
            "GOOGLE_API_KEY (or legacy GEMINI_API_KEY) is required for Gemini embeddings. "
            "Set it in the project-root .env file and restart the backend."
        )
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except ImportError as error:
        raise RuntimeError(
            "Gemini embedding support is not installed. Install backend requirements."
        ) from error

    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=api_key.strip(),
    )
