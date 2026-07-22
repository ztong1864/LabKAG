from fastapi import HTTPException

from app.adapters.embedding_client import configured_embedding_client
from app.adapters.graph_client import GraphWriteError, graph_client
from app.adapters.graph_mapper import map_extraction_to_graph
from app.config import settings
from app.schemas.common import SkillMetadata
from app.schemas.errors import ErrorCode, SkillError
from app.schemas.paper import ExtractPaperRequest, IngestPaperRequest
from app.schemas.response import SkillResponse, SkillStatus
from app.schemas.taxonomy import ProjectTaxonomy
from app.services.chunker import chunk_pages
from app.services.embedding_service import attach_evidence_embeddings, attach_paper_embedding
from app.services.evidence_binder import bind_required_evidence
from app.services.paper_extractor import (
    ExtractionError,
    LLMPaperExtractor,
    configured_chat_client,
)
from app.services.pdf_parser import parse_pdf
from app.services.taxonomy_tagger import tag_extraction
from app.storage.file_store import file_store
from app.storage.metadata_store import metadata_store
from app.storage.taxonomy_store import taxonomy_store
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
    status: SkillStatus = "success",
) -> SkillResponse:
    return SkillResponse(
        status=status,
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
    document = parse_pdf(
        pdf_path,
        document_id=document_id,
        use_backup=request.use_backup,
        mineru_output_dir=request.mineru_output_dir,
        original_file_name=file_store.original_name(request.file_id),
    )
    document.chunks = chunk_pages(document.document_id, document.pages)
    chat_client = configured_chat_client()
    if chat_client is None:
        raise error_response(
            503,
            ErrorCode.EXTRACTION_FAILED,
            "LLM extractor is not configured.",
        )

    try:
        extraction = LLMPaperExtractor(chat_client).extract(
            document,
            extract_level=request.extract_level,
        )
    except ExtractionError as exc:
        raise error_response(502, ErrorCode.EXTRACTION_FAILED, str(exc)) from exc

    warnings = bind_required_evidence(extraction)

    if request.project_id:
        taxonomy_payload = taxonomy_store.load_taxonomy(request.project_id)
        if taxonomy_payload is not None:
            taxonomy = ProjectTaxonomy.model_validate(taxonomy_payload)
            try:
                warnings.extend(tag_extraction(extraction, taxonomy, chat_client))
            except ExtractionError as exc:
                warnings.append(f"Tagging failed; extraction saved untagged: {exc}")

    metadata_store.save_extraction(
        document_id,
        extraction.model_dump(mode="json"),
        extra_output_dir=request.metadata_output_dir,
    )

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
    if settings.enable_embedding:
        embedding_client = configured_embedding_client()
        if embedding_client is None:
            raise error_response(
                503,
                ErrorCode.EMBEDDING_FAILED,
                "Embedding provider is not configured.",
            )
        attach_evidence_embeddings(
            request.paper_extraction,
            embedding_client,
            model=settings.embedding_model,
        )
        attach_paper_embedding(
            request.paper_extraction,
            embedding_client,
            model=settings.embedding_model,
        )
    graph_payload = map_extraction_to_graph(request.paper_extraction)
    try:
        result = graph_client.write_graph(
            graph_payload,
            confirm=request.confirm,
            project_id=request.project_id,
        )
    except GraphWriteError as exc:
        raise error_response(502, ErrorCode.GRAPH_WRITE_FAILED, str(exc)) from exc
    return success_response(data=result, project_id=request.project_id)
