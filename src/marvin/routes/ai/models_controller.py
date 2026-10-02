"""Ollama model management — list what's installed locally and pull new models on demand
(Ollama's /api/tags + /api/pull).

This is deliberately Ollama-specific: "installed models" and on-demand pulls only mean something for
a self-hosted runtime. Hosted providers (OpenAI, Anthropic) expose a fixed API catalogue, not an
installable set, so this surface targets Ollama directly — resolving its base URL from the
workspace's Ollama provider row, else the platform OLLAMA_BASE_URL, else localhost — independent of
whichever provider the workspace currently has *selected*. That lets an admin pull models into Ollama
while still setting it up.

A pull can take minutes (multi-GB), so the endpoint starts it in the background and returns a job id;
the client polls `GET /ai/models/pull/{job_id}` for progress. ADMIN/OWNER only.
"""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.checks import require_workspace_admin
from marvin.routes._base.controller import controller
from marvin.schemas.group.ai_provider import (
    InstalledModels,
    ModelPullRequest,
    ModelPullStatus,
)

router = APIRouter(prefix="/ai", route_class=MarvinCrudRoute)

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


_require_admin = require_workspace_admin


@controller(router)
class AIModelsController(BaseUserController):
    """List installed Ollama models + pull new ones (ADMIN/OWNER)."""

    def _ollama_base_url(self) -> str:
        """Resolve the Ollama endpoint: workspace Ollama provider row → platform setting → localhost."""
        from marvin.core.config import get_app_settings
        from marvin.db.models.groups.ai_providers import AIProviderModel

        row = self.session.query(AIProviderModel).filter_by(group_id=self.group_id, provider_type="ollama").first()
        if row and getattr(row, "base_url", None):
            return row.base_url
        return getattr(get_app_settings(), "OLLAMA_BASE_URL", None) or DEFAULT_OLLAMA_BASE_URL

    def _ollama_provider(self):
        from marvin.services.ai.providers.ollama import OllamaProvider

        return OllamaProvider(base_url=self._ollama_base_url())

    @router.get("/installed-models", response_model=InstalledModels, summary="List installed Ollama models")
    def installed_models(self) -> InstalledModels:
        """The models actually present in Ollama right now (its /api/tags)."""
        _require_admin(self.user, self.group_id)
        provider = self._ollama_provider()
        try:
            models = provider.list_models()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Couldn't reach Ollama at {self._ollama_base_url()} — is it running? ({e})",
            ) from e
        return InstalledModels(provider_type="ollama", supports_pull=True, models=models)

    @router.post("/models/pull", response_model=ModelPullStatus, status_code=status.HTTP_202_ACCEPTED, summary="Pull an Ollama model")
    def pull_model(self, data: ModelPullRequest) -> ModelPullStatus:
        """Start a background download of `name` into Ollama; poll the returned job id for progress."""
        _require_admin(self.user, self.group_id)
        name = (data.name or "").strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A model name is required.")

        from marvin.services.ai.model_pull import start_pull

        job = start_pull(self._ollama_provider(), name)
        return ModelPullStatus(**job.to_dict())

    @router.get("/models/pull/{job_id}", response_model=ModelPullStatus, summary="Model pull status")
    def pull_status(self, job_id: str) -> ModelPullStatus:
        _require_admin(self.user, self.group_id)
        from marvin.services.ai.model_pull import get_job

        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pull job not found (it may have expired).")
        return ModelPullStatus(**job.to_dict())
