from app.adapters.embedding_client import OpenAICompatibleEmbeddingClient
from app.schemas.extraction import PaperExtractionResult


def attach_evidence_embeddings(
    extraction: PaperExtractionResult,
    embedding_client: OpenAICompatibleEmbeddingClient,
    model: str,
) -> PaperExtractionResult:
    evidence_list = [evidence for evidence in extraction.evidence if evidence.source_text.strip()]
    if not evidence_list:
        return extraction

    vectors = embedding_client.embed_texts([evidence.source_text for evidence in evidence_list])
    for evidence, vector in zip(evidence_list, vectors, strict=True):
        evidence.embedding = vector
        evidence.embedding_model = model
        evidence.embedding_dim = len(vector)
    return extraction
