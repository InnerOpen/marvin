"""CRUD routes for AI providers and their models."""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.db.models.groups.ai_providers import AIModelModel, AIProviderModel
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.checks import require_workspace_admin
from marvin.routes._base.controller import controller
from marvin.schemas.group.ai_provider import (
    AIModelCreate,
    AIModelRead,
    AIModelUpdate,
    AIProviderCreate,
    AIProviderRead,
    AIProviderTestResult,
    AIProviderUpdate,
)

router = APIRouter(prefix="/ai/providers", route_class=MarvinCrudRoute)


_require_admin = require_workspace_admin


def _get_provider_or_404(session, provider_id: UUID4, group_id: UUID4) -> AIProviderModel:
    row = session.get(AIProviderModel, provider_id)
    if not row or row.group_id != group_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found.")
    return row


def _get_model_or_404(session, model_id: UUID4, provider: AIProviderModel) -> AIModelModel:
    row = session.get(AIModelModel, model_id)
    if not row or row.provider_id != provider.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found.")
    return row


@controller(router)
class AIProvidersController(BaseUserController):
    """Manage workspace AI providers and their models."""

    # ── Providers ─────────────────────────────────────────────────────────

    @router.get("", response_model=list[AIProviderRead], summary="List AI Providers")
    def list_providers(self) -> list[AIProviderRead]:
        _require_admin(self.user, self.group_id)  # provider config is admin-managed (§14)
        rows = self.session.query(AIProviderModel).filter_by(group_id=self.group_id).order_by(AIProviderModel.name).all()
        return [AIProviderRead.model_validate(r) for r in rows]

    @router.post("", response_model=AIProviderRead, status_code=status.HTTP_201_CREATED, summary="Create AI Provider")
    def create_provider(self, data: AIProviderCreate) -> AIProviderRead:
        _require_admin(self.user, self.group_id)

        existing = self.session.query(AIProviderModel).filter_by(group_id=self.group_id, slug=data.slug).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Provider slug '{data.slug}' already exists.")

        # If this is the new default, clear others
        if data.is_default:
            self.session.query(AIProviderModel).filter_by(group_id=self.group_id, is_default=True).update({"is_default": False})

        row = AIProviderModel(session=self.session, group_id=self.group_id, **data.model_dump())
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return AIProviderRead.model_validate(row)

    @router.get("/{provider_id}", response_model=AIProviderRead, summary="Get AI Provider")
    def get_provider(self, provider_id: UUID4) -> AIProviderRead:
        _require_admin(self.user, self.group_id)  # provider config is admin-managed (§14)
        row = _get_provider_or_404(self.session, provider_id, self.group_id)
        return AIProviderRead.model_validate(row)

    @router.patch("/{provider_id}", response_model=AIProviderRead, summary="Update AI Provider")
    def update_provider(self, provider_id: UUID4, data: AIProviderUpdate) -> AIProviderRead:
        _require_admin(self.user, self.group_id)
        row = _get_provider_or_404(self.session, provider_id, self.group_id)

        if data.is_default:
            self.session.query(AIProviderModel).filter_by(group_id=self.group_id, is_default=True).update({"is_default": False})

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(row, field, value)

        self.session.commit()
        self.session.refresh(row)
        return AIProviderRead.model_validate(row)

    @router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete AI Provider")
    def delete_provider(self, provider_id: UUID4) -> None:
        _require_admin(self.user, self.group_id)
        row = _get_provider_or_404(self.session, provider_id, self.group_id)
        self.session.delete(row)
        self.session.commit()

    @router.post("/{provider_id}/test", response_model=AIProviderTestResult, summary="Test AI Provider Connection")
    def test_provider(self, provider_id: UUID4) -> AIProviderTestResult:
        _require_admin(self.user, self.group_id)
        row = _get_provider_or_404(self.session, provider_id, self.group_id)

        from marvin.services.ai.factory import get_ai_provider
        from marvin.services.secrets.resolver import resolve_secret

        api_key = resolve_secret(row.secret_ref, self.group_id) if row.secret_ref else None
        try:
            provider = get_ai_provider(row.provider_type, api_key, row.base_url, row.metadata_json)
            success, message = provider.test_connection()
            models = provider.list_models() if success else []
            return AIProviderTestResult(success=success, message=message, available_models=models)
        except Exception as e:
            return AIProviderTestResult(success=False, message=str(e))

    # ── Models ────────────────────────────────────────────────────────────

    @router.get("/{provider_id}/models", response_model=list[AIModelRead], summary="List Models")
    def list_models(self, provider_id: UUID4) -> list[AIModelRead]:
        _require_admin(self.user, self.group_id)  # model config is admin-managed (§14)
        provider = _get_provider_or_404(self.session, provider_id, self.group_id)
        rows = self.session.query(AIModelModel).filter_by(provider_id=provider.id).order_by(AIModelModel.name).all()
        return [AIModelRead.model_validate(r) for r in rows]

    @router.post("/{provider_id}/models", response_model=AIModelRead, status_code=status.HTTP_201_CREATED, summary="Add Model")
    def create_model(self, provider_id: UUID4, data: AIModelCreate) -> AIModelRead:
        _require_admin(self.user, self.group_id)
        provider = _get_provider_or_404(self.session, provider_id, self.group_id)

        existing = self.session.query(AIModelModel).filter_by(provider_id=provider.id, model_id=data.model_id).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Model '{data.model_id}' already exists for this provider.")

        if data.is_default:
            self.session.query(AIModelModel).filter_by(provider_id=provider.id, is_default=True).update({"is_default": False})

        row = AIModelModel(session=self.session, provider_id=provider.id, group_id=self.group_id, **data.model_dump())
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return AIModelRead.model_validate(row)

    @router.patch("/{provider_id}/models/{model_id}", response_model=AIModelRead, summary="Update Model")
    def update_model(self, provider_id: UUID4, model_id: UUID4, data: AIModelUpdate) -> AIModelRead:
        _require_admin(self.user, self.group_id)
        provider = _get_provider_or_404(self.session, provider_id, self.group_id)
        row = _get_model_or_404(self.session, model_id, provider)

        if data.is_default:
            self.session.query(AIModelModel).filter_by(provider_id=provider.id, is_default=True).update({"is_default": False})

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(row, field, value)

        self.session.commit()
        self.session.refresh(row)
        return AIModelRead.model_validate(row)

    @router.delete("/{provider_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Model")
    def delete_model(self, provider_id: UUID4, model_id: UUID4) -> None:
        _require_admin(self.user, self.group_id)
        provider = _get_provider_or_404(self.session, provider_id, self.group_id)
        row = _get_model_or_404(self.session, model_id, provider)
        self.session.delete(row)
        self.session.commit()
