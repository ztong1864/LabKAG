from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.adapters.embedding_client import configured_embedding_client
from app.adapters.query_store_factory import build_query_store
from app.config import settings
from app.schemas.errors import ErrorCode
from app.schemas.paper import ExtractPaperRequest, IngestPaperRequest
from app.schemas.taxonomy import MatchTopicRequest, ProjectTaxonomy
from app.services.skill_orchestrator import (
    error_response,
    extract_paper,
    ingest_paper,
    success_response,
)
from app.services.topic_matcher import TopicPlanError, match_topic, verify_plan
from app.storage.file_store import UnsupportedFileTypeError, file_store
from app.storage.metadata_store import metadata_store
from app.storage.taxonomy_store import taxonomy_store

router = APIRouter(prefix="/v1/papers", tags=["papers"])


@router.get("")
def list_papers_route(project_id: str, limit: int | None = None, offset: int = 0):
    try:
        query_store = build_query_store()
        papers = query_store.list_papers(project_id, limit=limit, offset=offset)
    except RuntimeError as exc:
        raise error_response(502, ErrorCode.GRAPH_QUERY_FAILED, str(exc)) from exc
    for paper in papers:
        paper.pop("paper_embedding", None)
    return success_response(data={"papers": papers}, project_id=project_id)


@router.post("/match-topic")
def match_topic_route(request: MatchTopicRequest):
    taxonomy_payload = taxonomy_store.load_taxonomy(request.project_id)
    if taxonomy_payload is None:
        raise error_response(
            404,
            ErrorCode.TAXONOMY_NOT_CONFIGURED,
            f"No taxonomy configured for project {request.project_id}.",
        )
    taxonomy = ProjectTaxonomy.model_validate(taxonomy_payload)

    try:
        verified_plan = verify_plan(request.plan, taxonomy)
    except TopicPlanError as exc:
        raise error_response(422, ErrorCode.TOPIC_UNRESOLVED, str(exc)) from exc

    embedding_client = configured_embedding_client() if settings.enable_embedding else None

    try:
        query_store = build_query_store()
        result = match_topic(
            request.project_id,
            verified_plan,
            request.min_essential_signals,
            request.include_borderline,
            request.limit,
            query_store,
            embedding_client,
            target_count=request.target_count,
        )
    except RuntimeError as exc:
        raise error_response(502, ErrorCode.GRAPH_QUERY_FAILED, str(exc)) from exc

    data = {
        "topic_plan": verified_plan.model_dump(mode="json"),
        "confirmed": [matched.model_dump(mode="json") for matched in result["confirmed"]],
        "borderline": [matched.model_dump(mode="json") for matched in result["borderline"]],
        "summary": result["summary"],
    }
    return success_response(data=data, project_id=request.project_id)


@router.post("/upload")
async def upload_paper(file: Annotated[UploadFile, File(...)]):
    content = await file.read()
    try:
        result = file_store.save_upload(file.filename or "paper.pdf", content)
    except UnsupportedFileTypeError as exc:
        raise error_response(400, ErrorCode.UNSUPPORTED_FILE_TYPE, str(exc)) from exc
    return success_response(data=result)


@router.post("/extract")
def extract_paper_route(request: ExtractPaperRequest):
    return extract_paper(request)


@router.post("/ingest")
def ingest_paper_route(request: IngestPaperRequest):
    return ingest_paper(request)


@router.get("/{paper_id}/knowledge")
def get_paper_knowledge(
    paper_id: str,
    project_id: str | None = None,
    include_evidence: bool = True,
):
    extraction = metadata_store.load_extraction_by_paper_id(paper_id)
    if extraction is None:
        raise error_response(404, ErrorCode.PAPER_NOT_FOUND, f"Paper {paper_id} not found.")

    data = {
        "paper": extraction.get("paper", {}),
        "methods": extraction.get("methods", []),
        "materials": extraction.get("materials", []),
        "conditions": extraction.get("conditions", []),
        "metrics": extraction.get("metrics", []),
        "results": extraction.get("results", []),
        "conclusions": extraction.get("conclusions", []),
    }
    if include_evidence:
        data["evidence"] = extraction.get("evidence", [])
    return success_response(data=data, project_id=project_id, evidence=data.get("evidence", []))
