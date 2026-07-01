from app.adapters.embedding_client import (
    EmbeddingClientError,
    OpenAICompatibleEmbeddingClient,
    configured_embedding_client,
)
from app.config import settings


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.posts: list[dict] = []

    def post(self, url, *, headers, json, timeout):
        self.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self.response


def test_configured_embedding_client_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "embedding_api_key", None)

    assert configured_embedding_client() is None


def test_embedding_client_posts_embeddings_request_and_returns_vectors():
    session = FakeSession(
        FakeResponse(
            status_code=200,
            payload={
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                ]
            },
        )
    )
    client = OpenAICompatibleEmbeddingClient(
        api_key="secret",
        base_url="https://api.example.com/v1",
        model="text-embedding-3-small",
        timeout_seconds=15,
        session=session,
    )

    vectors = client.embed_texts(["one", "two"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert session.posts[0]["url"] == "https://api.example.com/v1/embeddings"
    assert session.posts[0]["headers"]["Authorization"] == "Bearer secret"
    assert session.posts[0]["json"] == {"model": "text-embedding-3-small", "input": ["one", "two"]}
    assert session.posts[0]["timeout"] == 15


def test_embedding_client_raises_clear_error_for_invalid_response():
    client = OpenAICompatibleEmbeddingClient(
        api_key="secret",
        base_url="https://api.example.com/v1",
        model="text-embedding-3-small",
        session=FakeSession(FakeResponse(status_code=500, text="server error")),
    )

    try:
        client.embed_texts(["one"])
    except EmbeddingClientError as exc:
        assert "HTTP 500" in str(exc)
    else:
        raise AssertionError("EmbeddingClientError was not raised")
