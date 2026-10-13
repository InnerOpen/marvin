"""Media-embed routes for the admin editor.

``GET /media-embeds/providers`` (any member) lists the allow-listed providers, the hosts each owns and
every player origin. ``POST /media-embeds/resolve`` (AUTHOR and above) turns a pasted link — or a
provider's ``<iframe>`` embed code — into the link to store plus its ``PublishedEmbed`` preview. It may
call the provider's oEmbed (filling the platform-wide cache the publishing API reads), so it is rate
limited per user.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, status

from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_role
from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.publishing import PublishedEmbed
from marvin.services.media_embeds.cache import resolve_cached
from marvin.services.media_embeds.matcher import url_from_input
from marvin.services.media_embeds.providers import PROVIDERS, frame_sources
from marvin.services.media_embeds.publish import build_embed, site_embeds
from marvin.services.security.rate_limit_service import RateLimitService

router = APIRouter(prefix="/media-embeds")

RESOLVE_LIMIT = 60
"""Resolves per user per RESOLVE_WINDOW_MINUTES (the editor caches per link, so this is generous)."""
RESOLVE_WINDOW_MINUTES = 1
_RATE_IDENTIFIER = "media-embeds:resolve"


class EmbedProviderInfo(_MarvinModel):
    key: str
    name: str
    kinds: list[str]
    hosts: list[str]
    """Exact hostnames; ``*.domain`` means any subdomain of domain."""
    examples: list[str]
    link_only: bool
    """A plain link never becomes a player (paste the provider's embed code instead)."""
    notes: str | None = None


class EmbedProvidersResponse(_MarvinModel):
    providers: list[EmbedProviderInfo]
    frame_sources: list[str]


class ResolveEmbedRequest(_MarvinModel):
    input: str
    """A link, or a provider's ``<iframe>`` embed code."""
    mode: Literal["direct", "click_to_load"] = "direct"
    """Which ``html`` to build; the editor preview wants the player itself."""


class ResolveEmbedResponse(_MarvinModel):
    input: str
    url: str | None = None
    """The link to store in the field (embed code reduced to the provider link); null if unsupported."""
    embed: PublishedEmbed | None = None
    error: str | None = None


@controller(router)
class MediaEmbedsController(BaseUserController):
    @router.get("/providers", response_model=EmbedProvidersResponse, summary="List Media Embed Providers")
    def list_providers(self) -> EmbedProvidersResponse:
        return EmbedProvidersResponse(
            providers=[
                EmbedProviderInfo(
                    key=p.key,
                    name=p.name,
                    kinds=list(p.kinds),
                    hosts=list(p.hosts),
                    examples=list(p.examples),
                    link_only=p.link_only,
                    notes=p.notes or None,
                )
                for p in PROVIDERS.values()
            ],
            frame_sources=frame_sources(),
        )

    @router.post("/resolve", response_model=ResolveEmbedResponse, summary="Resolve a Media Link")
    def resolve(self, body: ResolveEmbedRequest) -> ResolveEmbedResponse:
        require_workspace_role(self.user, self.group_id, WorkspaceRole.AUTHOR)
        text = (body.input or "").strip()
        if len(text) > 20_000:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That is too long to be a link or embed code.")
        if not RateLimitService(self.session).check_subject_limit(self.user.id, _RATE_IDENTIFIER, RESOLVE_LIMIT, RESOLVE_WINDOW_MINUTES):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many links checked in a minute — try again shortly.")

        url = url_from_input(text)
        if url is None:
            names = ", ".join(p.name for p in PROVIDERS.values())
            return ResolveEmbedResponse(input=text, error=f"Not a supported media link or embed code. Supported: {names}.")
        row = resolve_cached(self.session, url)
        settings = site_embeds(self._site_metadata()).model_copy(update={"mode": body.mode})
        embed = build_embed(url, row, settings)
        if embed is None:  # matched a moment ago, so only a provider change could get here
            return ResolveEmbedResponse(input=text, error="Not a supported media link.")
        return ResolveEmbedResponse(input=text, url=url, embed=embed, error=row.error if row is not None and embed.status != "ok" else None)

    def _site_metadata(self) -> dict | None:
        from marvin.db.models.groups import GroupPreferencesModel

        prefs = self.session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == self.group_id).first()
        return prefs.site_metadata_json if prefs else None
