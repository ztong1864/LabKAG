from collections.abc import Sequence
from typing import Any

import requests

from app.config import settings


class EmbeddingClientError(RuntimeError):
    pass


class OpenAICompatibleEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int = 60,
        session: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        response = self.session.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "input": list(texts)},
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise EmbeddingClientError(
                f"Embedding request failed with HTTP {response.status_code}."
            )

        payload = response.json()
        try:
            data = payload["data"]
        except (KeyError, TypeError) as exc:
            raise EmbeddingClientError("Embedding response did not contain data.") from exc

        vectors: list[list[float]] = []
        for item in data:
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list):
                raise EmbeddingClientError("Embedding response item did not contain a vector.")
            vectors.append(vector)
        return vectors


def configured_embedding_client() -> OpenAICompatibleEmbeddingClient | None:
    if not settings.embedding_api_key:
        return None
    return OpenAICompatibleEmbeddingClient(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
