from fastapi import HTTPException

from app.adapters.openspg_client import OpenSPGClientError, openspg_client
from app.adapters.openspg_mapper import map_extraction_to_graph
from app.config import settings
from app.schemas.common import SkillMetadata
from app.schemas.errors import ErrorCode, SkillError
from app.schemas.paper import ExtractPaperRequest, IngestPaperRequest
from app.schemas.response import SkillResponse
from app.services.chunker import chunk_pages
from app.services.evidence_binder import bind_required_evidence
from app.services.paper_extractor import (
    ExtractionError,
    LLMPaperExtractor,
    configured_chat_client,
    extract_paper_mock,
)
from app.services.pdf_parser import parse_pdf
from app.storage.file_store import file_store
from app.storage.metadata_store import metadata_store
from app.utils.ids import new_id
from app.utils.time import utc_now_iso


def metadata(project_id: str | None = None) -> SkillMetadata:
    return SkillMetadata(
        request_id=new_id("req"),
        project_id=project_id,
        created_at=utc_now_iso(),
    )


def success_response(
    data: dict,
    project_id: str | None = None,
    evidence: list | None = None,
    warnings: list[str] | None = None,
) -> SkillResponse:
    return SkillResponse(
        status="success",
        data=data,
        evidence=evidence or [],
        warnings=warnings or [],
        errors=[],
        metadata=metadata(project_id),
    )


def error_response(status_code: int, code: ErrorCode, message: str) -> HTTPException:
    response = SkillResponse(
        status="failed",
        data={},
        evidence=[],
        warnings=[],
        errors=[SkillError(code=code, message=message)],
        metadata=metadata(),
    )
    return HTTPException(status_code=status_code, detail=response.model_dump(mode="json"))


def extract_paper(request: ExtractPaperRequest) -> SkillResponse:
    try:
        pdf_path = file_store.resolve(request.file_id)
    except FileNotFoundError as exc:
        raise error_response(404, ErrorCode.FILE_NOT_FOUND, str(exc)) from exc

    document_id = new_id("doc")
    document = parse_pdf(pdf_path, document_id=document_id)
    document.chunks = chunk_pages(document.document_id, document.pages)
    warnings: list[str] = []
    chat_client = configured_chat_client()
    use_mock = chat_client is None or request.extract_level == "mock"
    if use_mock and not settings.allow_mock_extractor:
        raise error_response(
            503,
            ErrorCode.EXTRACTION_FAILED,
            "LLM extractor is not configured and mock extractor is disabled.",
        )

    if use_mock:
        extraction = extract_paper_mock(document)
        if request.extract_level == "mock":
            warnings.append("Mock extractor requested; used mock extractor.")
        else:
            warnings.append("LLM extractor is not configured; used mock extractor.")
    else:
        try:
            extraction = LLMPaperExtractor(chat_client).extract(
                document,
                extract_level=request.extract_level,
            )
        except ExtractionError as exc:
            raise error_response(502, ErrorCode.EXTRACTION_FAILED, str(exc)) from exc
    warnings.extend(bind_required_evidence(extraction))
    metadata_store.save_extraction(document_id, extraction.model_dump(mode="json"))

    data = {"paper_extraction": extraction.model_dump(mode="json")}
    if request.return_chunks:
        data["chunks"] = [chunk.model_dump(mode="json") for chunk in document.chunks]
    return success_response(
        data=data,
        project_id=request.project_id,
        evidence=extraction.evidence,
        warnings=warnings,
    )


def ingest_paper(request: IngestPaperRequest) -> SkillResponse:
    graph_payload = map_extraction_to_graph(request.paper_extraction)
    try:
        result = openspg_client.write_graph(graph_payload, confirm=request.confirm)
    except OpenSPGClientError as exc:
        raise error_response(502, ErrorCode.OPENSPG_WRITE_FAILED, str(exc)) from exc
    return success_response(data=result, project_id=request.project_id)
