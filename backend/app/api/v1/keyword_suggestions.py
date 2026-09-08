"""AI keyword suggestion from a project's own website — the "enter your URL, AI finds
keywords" step. Deliberately its own router, not folded into agent_configs.py: that file's
module docstring states "no agent-specific code here or ever should be", and keyword
derivation from a URL is conceptually project-level (feeding conversation_finder's config,
today), not a generic per-agent-key capability the way trigger/runs endpoints are.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_settings_dep, require_project_access
from app.core.config import Settings
from app.core.llm.factory import build_llm_provider
from app.models.project import Project
from app.schemas.agent import KeywordSuggestionRequest, KeywordSuggestionResponse
from app.services.keyword_suggestion_service import KeywordSuggestionService
from app.services.llm_usage import LlmUsageClient

router = APIRouter(prefix="/projects/{project_id}", tags=["keyword-suggestions"])


@router.post("/keyword-suggestions", response_model=KeywordSuggestionResponse)
async def suggest_keywords(
    body: KeywordSuggestionRequest,
    project: Project = Depends(require_project_access),
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_db),
) -> KeywordSuggestionResponse:
    """Suggestion only — writes nothing to conversation_finder's own config (the frontend
    shows these for the user to review and edit before saving through the ordinary
    `PUT /projects/{project_id}/agent-configs/conversation_finder` path); it does write one
    llm_usage_logs row for the real cost of the suggestion call itself, see
    app/services/llm_usage.py."""
    keywords = await KeywordSuggestionService().suggest(
        url=str(body.url),
        llm=build_llm_provider(settings),
        usage=LlmUsageClient(session),
        org_id=project.org_id,
        project_id=project.id,
    )
    return KeywordSuggestionResponse(keywords=keywords)
