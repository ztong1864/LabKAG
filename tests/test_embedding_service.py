from app.schemas.evidence import Evidence
from app.schemas.extraction import (
    ExtractedMaterial,
    ExtractedResult,
    PaperExtractionResult,
    PaperMetadata,
)
from app.services.embedding_service import attach_evidence_embeddings, attach_paper_embedding


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


def test_attach_paper_embedding_composes_text_from_title_abstract_and_entities():
    extraction = PaperExtractionResult(
        document_id="doc_001",
        paper=PaperMetadata(title="Iron Catalysis", abstract="A study of iron catalysts."),
        materials=[ExtractedMaterial(material_id="m_001", name="Fe(NO3)3")],
        results=[ExtractedResult(result_id="r_001", description="95% conversion.")],
    )
    embedder = FakeEmbeddingClient()

    result = attach_paper_embedding(extraction, embedder, model="text-embedding-3-small")

    assert len(embedder.calls) == 1
    composed_text = embedder.calls[0][0]
    assert "Iron Catalysis" in composed_text
    assert "A study of iron catalysts." in composed_text
    assert "Fe(NO3)3" in composed_text
    assert "95% conversion." in composed_text
    assert result.paper_embedding == [1.0, 2.0]


def test_attach_paper_embedding_skips_when_no_text_available():
    extraction = PaperExtractionResult(document_id="doc_001")
    embedder = FakeEmbeddingClient()

    result = attach_paper_embedding(extraction, embedder, model="text-embedding-3-small")

    assert embedder.calls == []
    assert result.paper_embedding is None
