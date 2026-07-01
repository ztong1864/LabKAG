from app.schemas.evidence import Evidence
from app.schemas.extraction import PaperExtractionResult
from app.services.embedding_service import attach_evidence_embeddings


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 2.0], [3.0, 4.0]]


def test_attach_evidence_embeddings_populates_vectors_and_metadata():
    extraction = PaperExtractionResult(
        document_id="doc_001",
        evidence=[
            Evidence(
                evidence_id="ev_001",
                document_id="doc_001",
                chunk_id="chunk_001",
                page=1,
                source_text="First evidence text.",
            ),
            Evidence(
                evidence_id="ev_002",
                document_id="doc_001",
                chunk_id="chunk_002",
                page=2,
                source_text="Second evidence text.",
            ),
        ],
    )
    embedder = FakeEmbeddingClient()

    result = attach_evidence_embeddings(extraction, embedder, model="text-embedding-3-small")

    assert embedder.calls == [["First evidence text.", "Second evidence text."]]
    assert result.evidence[0].embedding == [1.0, 2.0]
    assert result.evidence[1].embedding == [3.0, 4.0]
    assert result.evidence[0].embedding_model == "text-embedding-3-small"
    assert result.evidence[0].embedding_dim == 2
