"""The AI providers this platform can use — core's built-ins and installed ``marvin.ai_providers``
plugins (services/ai/registry.py). AI Settings builds its provider list and model picker from this."""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.group.ai_provider import AICredentialRead, AIProviderTypeRead

router = APIRouter(prefix="/ai/provider-types", route_class=MarvinCrudRoute)


def provider_types() -> list[AIProviderTypeRead]:
    from marvin.services.ai import registry

    out = []
    for slug, plugin in sorted(registry.plugins().items(), key=lambda kv: kv[1].name.lower()):
        cls = plugin.provider
        report = registry.report_for(slug)
        out.append(
            AIProviderTypeRead(
                slug=slug,
                name=plugin.name,
                description=plugin.description,
                source="builtin" if report is None else "plugin",
                package=report.distribution if report else None,
                version=report.version if report else None,
                capabilities=[name for name, on in cls.capabilities().items() if on],
                credentials=[
                    AICredentialRead(key=c.key, label=c.label, secret=c.secret, required=c.required, default=c.default, help=c.help)
                    for c in cls.credentials
                ],
                default_model=cls.default_model,
                suggested_models=list(cls.suggested_models),
                self_hosted=cls.self_hosted,
            )
        )
    return out


def require_installed_provider(slug: str) -> None:
    """422 naming what is installed, when nothing provides ``slug``."""
    from marvin.services.ai.base import AIConfigError
    from marvin.services.ai.registry import provider_class

    try:
        provider_class(slug)
    except AIConfigError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from None


@controller(router)
class AIProviderTypesController(BaseUserController):
    @router.get("", response_model=list[AIProviderTypeRead], summary="List AI Provider Types")
    def list_provider_types(self) -> list[AIProviderTypeRead]:
        """The AI providers this platform can use (built in or installed as plugins), what each can do,
        the credentials it needs and the models it suggests. Nothing here is secret."""
        return provider_types()
