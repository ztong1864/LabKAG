from fastapi import APIRouter

from app.adapters.query_store_factory import build_query_store
from app.schemas.errors import ErrorCode
from app.schemas.taxonomy import ProjectTaxonomy
from app.services.skill_orchestrator import error_response, success_response
from app.services.taxonomy_service import get_taxonomy, set_taxonomy

router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.get("/{project_id}/taxonomy")
def get_taxonomy_route(project_id: str):
    taxonomy = get_taxonomy(project_id)
    if taxonomy is None:
        raise error_response(
            404,
            ErrorCode.TAXONOMY_NOT_CONFIGURED,
            f"No taxonomy configured for project {project_id}.",
        )
    return success_response(data={"taxonomy": taxonomy}, project_id=project_id)


@router.post("/{project_id}/taxonomy")
def set_taxonomy_route(project_id: str, payload: ProjectTaxonomy, confirm: bool = False):
    payload.project_id = project_id
    try:
        result = set_taxonomy(project_id, payload, confirm, build_query_store)
    except RuntimeError as exc:
        raise error_response(502, ErrorCode.GRAPH_QUERY_FAILED, str(exc)) from exc
    return success_response(
        data={k: v for k, v in result.items() if k != "status"},
        project_id=project_id,
        status=result["status"],
    )
