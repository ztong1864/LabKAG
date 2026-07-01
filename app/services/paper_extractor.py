import json
import re
from pathlib import Path
from typing import Any, Protocol

import requests

from app.config import settings
from app.schemas.document import DocumentChunk, ParsedDocument
from app.schemas.evidence import Evidence
from app.schemas.extraction import (
    ExtractedConclusion,
    ExtractedCondition,
    ExtractedMaterial,
    ExtractedMethod,
    ExtractedMetric,
    ExtractedResult,
    PaperExtractionResult,
    PaperMetadata,
)
from app.utils.ids import new_id
from app.utils.time import utc_now_iso


class ExtractionError(RuntimeError):
    pass


class ChatJSONClient(Protocol):
    def extract_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        pass


class OpenAICompatibleChatClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def extract_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise ExtractionError(f"LLM request failed with HTTP {response.status_code}.")

        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExtractionError("LLM response did not contain message content.") from exc
        return _loads_json_content(content)


def configured_chat_client() -> OpenAICompatibleChatClient | None:
    if not settings.llm_api_key:
        return None
    return OpenAICompatibleChatClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _loads_json_content(content: str) -> dict:
    stripped = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ExtractionError("LLM response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ExtractionError("LLM response JSON must be an object.")
    return payload


def _first_evidence(chunks: list[DocumentChunk]) -> Evidence | None:
    for chunk in chunks:
        if chunk.text.strip():
            source_text = chunk.text.strip()
            return Evidence(
                evidence_id=new_id("ev"),
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                page=chunk.page,
                section_title=chunk.section_title,
                source_text=source_text[:500],
            )
    return None


def _chunk_evidence_map(chunks: list[DocumentChunk]) -> dict[str, Evidence]:
    evidence_by_chunk = {}
    for chunk in chunks:
        evidence_by_chunk[chunk.chunk_id] = Evidence(
            evidence_id=new_id("ev"),
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            page=chunk.page,
            section_title=chunk.section_title,
            source_text=chunk.text[:500],
        )
    return evidence_by_chunk


def _evidence_from_payload(
    raw_evidence: Any,
    evidence_by_chunk: dict[str, Evidence],
) -> list[Evidence]:
    evidence: list[Evidence] = []
    for item in _as_list(raw_evidence):
        if isinstance(item, str):
            if item in evidence_by_chunk:
                evidence.append(evidence_by_chunk[item])
            continue
        if not isinstance(item, dict):
            continue
        chunk_id = item.get("chunk_id")
        if chunk_id and chunk_id in evidence_by_chunk:
            evidence.append(evidence_by_chunk[chunk_id])
            continue
        if item.get("document_id") and item.get("source_text"):
            evidence.append(Evidence.model_validate(item))
    return evidence


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_item_dict(value: Any, text_field: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {text_field: value}
    return {text_field: str(value)}


def _load_prompt(extract_level: str) -> str:
    prompt_name = (
        "paper_extraction_detailed.md"
        if extract_level == "detailed"
        else "paper_extraction_basic.md"
    )
    prompt_path = Path("app/prompts") / prompt_name
    if prompt_path.exists() and prompt_path.read_text(encoding="utf-8").strip():
        return prompt_path.read_text(encoding="utf-8")
    return (
        "Extract literature knowledge as strict JSON with keys: paper, methods, materials, "
        "conditions, metrics, results, conclusions. Every result and conclusion must cite "
        "evidence as objects containing chunk_id."
    )


def _document_prompt(document: ParsedDocument) -> str:
    chunks = []
    for chunk in document.chunks:
        chunks.append(
            "\n".join(
                [
                    f"chunk_id: {chunk.chunk_id}",
                    f"page: {chunk.page}",
                    f"section_title: {chunk.section_title or ''}",
                    "text:",
                    chunk.text[:2500],
                ]
            )
        )
    return "\n\n---\n\n".join(chunks)


class LLMPaperExtractor:
    def __init__(self, chat_client: ChatJSONClient) -> None:
        self.chat_client = chat_client

    def extract(
        self,
        document: ParsedDocument,
        extract_level: str = "basic",
    ) -> PaperExtractionResult:
        payload = self.chat_client.extract_json(
            system_prompt=_load_prompt(extract_level),
            user_prompt=_document_prompt(document),
        )
        return self._to_extraction(document, payload)

    def _to_extraction(self, document: ParsedDocument, payload: dict) -> PaperExtractionResult:
        evidence_by_chunk = _chunk_evidence_map(document.chunks)
        all_evidence: dict[str, Evidence] = {}

        def bind(raw_item: dict) -> list[Evidence]:
            evidence = _evidence_from_payload(raw_item.get("evidence", []), evidence_by_chunk)
            for item in evidence:
                all_evidence[item.evidence_id] = item
            return evidence

        paper_payload = payload.get("paper") or {}
        paper = PaperMetadata.model_validate(
            {
                **paper_payload,
                "paper_id": paper_payload.get("paper_id") or new_id("paper"),
                "document_id": document.document_id,
            }
        )
        methods = [
            ExtractedMethod.model_validate(
                {
                    **item,
                    "method_id": item.get("method_id") or new_id("method"),
                    "evidence": bind(item),
                }
            )
            for item in (
                _as_item_dict(raw_item, "name") for raw_item in _as_list(payload.get("methods"))
            )
        ]
        materials = [
            ExtractedMaterial.model_validate(
                {
                    **item,
                    "material_id": item.get("material_id") or new_id("material"),
                    "evidence": bind(item),
                }
            )
            for item in (
                _as_item_dict(raw_item, "name") for raw_item in _as_list(payload.get("materials"))
            )
        ]
        conditions = [
            ExtractedCondition.model_validate(
                {
                    **item,
                    "condition_id": item.get("condition_id") or new_id("condition"),
                    "evidence": bind(item),
                }
            )
            for item in (
                _as_item_dict(raw_item, "name")
                for raw_item in _as_list(payload.get("conditions"))
            )
        ]
        metrics = [
            ExtractedMetric.model_validate(
                {
                    **item,
                    "metric_id": item.get("metric_id") or new_id("metric"),
                    "evidence": bind(item),
                }
            )
            for item in (
                _as_item_dict(raw_item, "name") for raw_item in _as_list(payload.get("metrics"))
            )
        ]
        results = [
            ExtractedResult.model_validate(
                {
                    **item,
                    "result_id": item.get("result_id") or new_id("res"),
                    "evidence": bind(item),
                }
            )
            for item in (
                _as_item_dict(raw_item, "description")
                for raw_item in _as_list(payload.get("results"))
            )
        ]
        conclusions = [
            ExtractedConclusion.model_validate(
                {
                    **item,
                    "conclusion_id": item.get("conclusion_id") or new_id("con"),
                    "evidence": bind(item),
                }
            )
            for item in (
                _as_item_dict(raw_item, "description")
                for raw_item in _as_list(payload.get("conclusions"))
            )
        ]
        return PaperExtractionResult(
            document_id=document.document_id,
            paper=paper,
            methods=methods,
            materials=materials,
            conditions=conditions,
            metrics=metrics,
            results=results,
            conclusions=conclusions,
            evidence=list(all_evidence.values()),
            created_at=utc_now_iso(),
        )


def extract_paper_mock(document: ParsedDocument) -> PaperExtractionResult:
    evidence = _first_evidence(document.chunks)
    first_text = evidence.source_text if evidence else ""
    title = document.title or first_text.splitlines()[0][:120] if first_text else ""

    evidence_list = [evidence] if evidence else []
    return PaperExtractionResult(
        document_id=document.document_id,
        paper=PaperMetadata(
            paper_id=new_id("paper"),
            title=title,
            document_id=document.document_id,
        ),
        methods=[
            ExtractedMethod(
                method_id=new_id("method"),
                name="mock_method",
                description="Mock method extracted from parsed document text.",
                evidence=evidence_list,
                inferred=True,
            )
        ]
        if evidence
        else [],
        results=[
            ExtractedResult(
                result_id=new_id("res"),
                description="Mock result extracted from parsed document text.",
                evidence=evidence_list,
                inferred=True,
            )
        ]
        if evidence
        else [],
        conclusions=[
            ExtractedConclusion(
                conclusion_id=new_id("con"),
                description="Mock conclusion extracted from parsed document text.",
                evidence=evidence_list,
                inferred=True,
            )
        ]
        if evidence
        else [],
        evidence=evidence_list,
        created_at=utc_now_iso(),
    )
