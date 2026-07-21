from app.adapters.embedding_client import OpenAICompatibleEmbeddingClient
from app.schemas.extraction import PaperExtractionResult

PAPER_EMBEDDING_MAX_CHARS = 4000


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


def _paper_embedding_text(extraction: PaperExtractionResult) -> str:
    """title + abstract + a bounded join of method/material/result/conclusion
    names/descriptions. Deliberately excludes tag values -- paper_embedding
    is a semantic signal independent of the deterministic taxonomy match, not
    an echo of it (see topic_matcher's corroboration design)."""
    parts = [extraction.paper.title, extraction.paper.abstract]
    groups = (extraction.methods, extraction.materials, extraction.results, extraction.conclusions)
    for group in groups:
        for item in group:
            text = getattr(item, "name", "") or getattr(item, "description", "") or ""
            if text:
                parts.append(text)
    return " ".join(part for part in parts if part)[:PAPER_EMBEDDING_MAX_CHARS]


def attach_paper_embedding(
    extraction: PaperExtractionResult,
    embedding_client: OpenAICompatibleEmbeddingClient,
    model: str,
) -> PaperExtractionResult:
    text = _paper_embedding_text(extraction)
    if not text.strip():
        return extraction

    extraction.paper_embedding = embedding_client.embed_texts([text])[0]
    return extraction
