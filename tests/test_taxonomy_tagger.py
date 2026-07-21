import pytest

from app.schemas.extraction import ExtractedMaterial, ExtractedResult, PaperExtractionResult
from app.schemas.taxonomy import ProjectTaxonomy, TaxonomyCategory
from app.services.paper_extractor import ExtractionError
from app.services.taxonomy_tagger import tag_extraction


class FakeChatClient:
    def __init__(self, payload: dict | str) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def extract_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if isinstance(self.payload, str):
            raise ExtractionError(self.payload)
        return self.payload


def _taxonomy() -> ProjectTaxonomy:
    return ProjectTaxonomy(
        project_id="proj_1",
        version=3,
        categories=[
            TaxonomyCategory(
                key="catalyst_type",
                allowed_values=["iron", "copper"],
                aliases={"iron": ["Fe(NO3)3", "iron nitrate"]},
            )
        ],
    )


def _extraction() -> PaperExtractionResult:
    return PaperExtractionResult(
        document_id="doc_001",
        materials=[
            ExtractedMaterial(material_id="material_001", name="Fe(NO3)3"),
        ],
        results=[
            ExtractedResult(result_id="res_001", description="95% conversion observed."),
        ],
    )


def test_tag_extraction_applies_valid_tags_and_sets_taxonomy_version():
    extraction = _extraction()
    chat_client = FakeChatClient({"tags": {"material_001": {"catalyst_type": "iron"}}})

    warnings = tag_extraction(extraction, _taxonomy(), chat_client)

    assert warnings == []
    assert extraction.materials[0].tags == {"catalyst_type": "iron"}
    assert extraction.taxonomy_version == 3


def test_tag_extraction_resolves_alias_to_canonical_value():
    extraction = _extraction()
    chat_client = FakeChatClient({"tags": {"material_001": {"catalyst_type": "Fe(NO3)3"}}})

    tag_extraction(extraction, _taxonomy(), chat_client)

    assert extraction.materials[0].tags == {"catalyst_type": "iron"}


def test_tag_extraction_drops_unknown_category_with_warning():
    extraction = _extraction()
    chat_client = FakeChatClient({"tags": {"material_001": {"substrate_class": "alcohol"}}})

    warnings = tag_extraction(extraction, _taxonomy(), chat_client)

    assert extraction.materials[0].tags == {}
    assert len(warnings) == 1
    assert "unknown category 'substrate_class'" in warnings[0]


def test_tag_extraction_drops_value_not_in_taxonomy_with_warning():
    extraction = _extraction()
    chat_client = FakeChatClient({"tags": {"material_001": {"catalyst_type": "mercury"}}})

    warnings = tag_extraction(extraction, _taxonomy(), chat_client)

    assert extraction.materials[0].tags == {}
    assert len(warnings) == 1
    assert "not in the taxonomy" in warnings[0]


def test_tag_extraction_ignores_tags_for_unknown_entity_id():
    extraction = _extraction()
    chat_client = FakeChatClient({"tags": {"does_not_exist": {"catalyst_type": "iron"}}})

    warnings = tag_extraction(extraction, _taxonomy(), chat_client)

    assert warnings == []
    assert extraction.materials[0].tags == {}
    assert extraction.results[0].tags == {}


def test_tag_extraction_skips_llm_call_when_no_taggable_entities():
    extraction = PaperExtractionResult(document_id="doc_001")
    chat_client = FakeChatClient({"tags": {}})

    warnings = tag_extraction(extraction, _taxonomy(), chat_client)

    assert warnings == []
    assert chat_client.calls == []
    assert extraction.taxonomy_version == 3


def test_tag_extraction_skips_llm_call_when_taxonomy_has_no_categories():
    extraction = _extraction()
    empty_taxonomy = ProjectTaxonomy(project_id="proj_1", version=1, categories=[])
    chat_client = FakeChatClient({"tags": {}})

    warnings = tag_extraction(extraction, empty_taxonomy, chat_client)

    assert warnings == []
    assert chat_client.calls == []
    assert extraction.taxonomy_version == 1


def test_tag_extraction_propagates_llm_failure_as_extraction_error():
    extraction = _extraction()
    chat_client = FakeChatClient("LLM request failed with HTTP 500.")

    with pytest.raises(ExtractionError, match="500"):
        tag_extraction(extraction, _taxonomy(), chat_client)
