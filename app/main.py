from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from app.api import evidence, health, literature, papers, projects
from app.config import settings

app = FastAPI(title=settings.app_name, version=settings.app_version)


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    if isinstance(exc.detail, dict) and "status" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health.router)
app.include_router(papers.router)
app.include_router(literature.router)
app.include_router(evidence.router)
app.include_router(projects.router)
