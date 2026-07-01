import pytest

from app.schemas.document import DocumentChunk, ParsedDocument
from app.services.paper_extractor import ExtractionError, LLMPaperExtractor


class FakeChatClient:
    def __init__(self, payload: dict | str) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def extract_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if isinstance(self.payload, str):
            raise ExtractionError(self.payload)
        return self.payload


def _document() -> ParsedDocument:
    return ParsedDocument(
        document_id="doc_001",
        file_name="paper.pdf",
        chunks=[
            DocumentChunk(
                document_id="doc_001",
                chunk_id="chunk_001",
                page=1,
                section_title="Results",
                text="The catalyst reached 95% conversion after 2 h.",
            )
        ],
    )


def test_llm_paper_extractor_converts_json_payload_to_schema():
    payload = {
        "paper": {"title": "Catalyst Study", "authors": ["A. Researcher"], "year": "2026"},
        "methods": [{"name": "Batch catalysis", "description": "Batch reaction test."}],
        "materials": [{"name": "Catalyst A", "type": "catalyst"}],
        "conditions": [{"name": "time", "value": "2", "unit": "h"}],
        "metrics": [{"name": "conversion", "value": "95", "unit": "%"}],
        "results": [
            {
                "description": "The catalyst reached 95% conversion after 2 h.",
                "value": "95",
                "unit": "%",
                "evidence": [{"chunk_id": "chunk_001"}],
            }
        ],
        "conclusions": [
            {
                "description": "Catalyst A is active under the tested condition.",
                "evidence": [{"chunk_id": "chunk_001"}],
            }
        ],
    }

    extractor = LLMPaperExtractor(chat_client=FakeChatClient(payload))
    extraction = extractor.extract(_document(), extract_level="basic")

    assert extraction.document_id == "doc_001"
    assert extraction.paper.title == "Catalyst Study"
    assert extraction.results[0].evidence[0].chunk_id == "chunk_001"
    assert extraction.conclusions[0].evidence[0].source_text.startswith("The catalyst")
    assert extraction.materials[0].name == "Catalyst A"


def test_llm_paper_extractor_raises_clear_error_for_client_failure():
    extractor = LLMPaperExtractor(chat_client=FakeChatClient("model returned invalid JSON"))

    with pytest.raises(ExtractionError, match="model returned invalid JSON"):
        extractor.extract(_document(), extract_level="basic")


def test_llm_paper_extractor_normalizes_string_items_from_model_payload():
    payload = {
        "paper": {"title": "Catalyst Study"},
        "methods": ["Batch catalysis"],
        "materials": ["Catalyst A"],
        "results": [
            {
                "description": "The catalyst reached 95% conversion after 2 h.",
                "evidence": [{"chunk_id": "chunk_001"}],
            }
        ],
        "conclusions": ["Catalyst A is active."],
    }

    extractor = LLMPaperExtractor(chat_client=FakeChatClient(payload))
    extraction = extractor.extract(_document(), extract_level="basic")

    assert extraction.methods[0].name == "Batch catalysis"
    assert extraction.materials[0].name == "Catalyst A"
    assert extraction.conclusions[0].description == "Catalyst A is active."


def test_llm_paper_extractor_normalizes_string_evidence_from_model_payload():
    payload = {
        "paper": {"title": "Catalyst Study"},
        "results": [
            {
                "description": "The catalyst reached 95% conversion after 2 h.",
                "evidence": ["chunk_001"],
            }
        ],
    }

    extractor = LLMPaperExtractor(chat_client=FakeChatClient(payload))
    extraction = extractor.extract(_document(), extract_level="basic")

    assert extraction.results[0].evidence[0].chunk_id == "chunk_001"
