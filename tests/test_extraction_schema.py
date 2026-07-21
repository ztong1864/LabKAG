from app.schemas.evidence import Evidence
from app.schemas.extraction import (
    ExtractedConclusion,
    ExtractedResult,
    PaperExtractionResult,
    PaperMetadata,
)


def test_paper_extraction_result_accepts_minimal_evidence_bound_payload():
    evidence = Evidence(
        evidence_id="ev_001",
        document_id="doc_001",
        chunk_id="chunk_001",
        page=1,
        section_title="Results",
        source_text="The material showed stable catalytic activity.",
    )

    extraction = PaperExtractionResult(
        paper=PaperMetadata(title="A Test Paper", authors=["Ada Lovelace"], year="2026"),
        results=[
            ExtractedResult(
                result_id="res_001",
                description="The material showed stable catalytic activity.",
                evidence=[evidence],
            )
        ],
        conclusions=[
            ExtractedConclusion(
                conclusion_id="con_001",
                description="The material is promising for catalysis.",
                evidence=[evidence],
            )
        ],
        evidence=[evidence],
        document_id="doc_001",
    )

    assert extraction.paper.title == "A Test Paper"
    assert extraction.results[0].evidence[0].chunk_id == "chunk_001"
    assert extraction.conclusions[0].evidence[0].page == 1
    assert extraction.results[0].tags == {}
    assert extraction.paper_embedding is None
    assert extraction.taxonomy_version is None


def test_evidence_bound_item_accepts_tags():
    result = ExtractedResult(
        result_id="res_001",
        description="Iron catalyzed the reaction.",
        tags={"catalyst_type": "iron"},
    )

    assert result.tags == {"catalyst_type": "iron"}


def test_paper_extraction_result_accepts_paper_embedding_and_taxonomy_version():
    extraction = PaperExtractionResult(
        document_id="doc_001",
        paper=PaperMetadata(title="A Test Paper"),
        paper_embedding=[0.1, 0.2, 0.3],
        taxonomy_version=2,
    )

    assert extraction.paper_embedding == [0.1, 0.2, 0.3]
    assert extraction.taxonomy_version == 2
