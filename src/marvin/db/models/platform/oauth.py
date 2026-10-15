"""The remote MCP server's OAuth 2.1 records (tasks/mcp-oauth-plan.md §2.1).

A client registers itself (`oauth_clients`, RFC 7591), sends the user to sign in and approve
(`oauth_authorization_requests`, which also carries the one-time code), and the approval becomes a grant: one
connected app, bound to one user, one workspace and one scope (`oauth_grants`). The grant's access and refresh
tokens are `oauth_tokens`. Every secret is stored as its SHA-256 only (`*_lookup`, `*_hash`): the values carry 256
bits of randomness, so a plain hash is enough to find them and useless to whoever reads the table.

None of these tokens is accepted by the REST API: `get_current_user` knows only personal tokens and session JWTs.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.datetime import NaiveDateTime
from .._model_utils.guid import GUID


class OAuthClientModel(SqlAlchemyBase, BaseMixins):
    """An MCP client that registered itself (claude.ai, ChatGPT, Claude Code…). Purged once unused for 7 days."""

    __tablename__ = "oauth_clients"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    client_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """The public `marvin_oc_…` id the client sends."""
    client_secret_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """SHA-256 of the client secret; null for a public client (`token_endpoint_auth_method` "none")."""
    token_endpoint_auth_method: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    redirect_uris: Mapped[list] = mapped_column(sa.JSON, nullable=False)
    grant_types: Mapped[list] = mapped_column(sa.JSON, nullable=False)
    client_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    """As the client calls itself: shown at consent as unverified."""
    client_uri: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    logo_uri: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    software_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    software_version: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    registered_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)

    __table_args__ = (sa.UniqueConstraint("client_id", name="uq_oauth_clients_client_id"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass


class OAuthAuthorizationRequestModel(SqlAlchemyBase, BaseMixins):
    """One sign-in in progress, from `/oauth/authorize` to the code being exchanged.

    The consent page finds it by the `req` value in its URL (never a cookie: ChatGPT opens the page in a webview
    without one), and it lives in the database so a deploy mid-sign-in loses nothing. Approving it stores the
    one-time code on the same row.
    """

    __tablename__ = "oauth_authorization_requests"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    ref_lookup: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """SHA-256 of the `req` value in the consent page's URL."""
    client_fk: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(sa.String(1000), nullable=False)
    state: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    code_challenge: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    """PKCE S256 challenge (the only method accepted)."""
    requested_scope: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    resource: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    consent_nonce_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="pending", server_default="pending")
    """pending | approved | denied | expired"""
    user_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    group_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    granted_scope: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    grant_id: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("oauth_grants.id", ondelete="SET NULL"), nullable=True)
    """The grant the code was exchanged for, so a reused code can revoke what it issued (RFC 6749 §4.1.2)."""
    code_lookup: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """SHA-256 of the one-time authorization code, once approved."""
    code_expires_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    code_used_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False)
    created_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("ref_lookup", name="uq_oauth_authorization_requests_ref_lookup"),
        sa.UniqueConstraint("code_lookup", name="uq_oauth_authorization_requests_code_lookup"),
        sa.Index("ix_oauth_authorization_requests_expires_at", "expires_at"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass


class OAuthGrantModel(SqlAlchemyBase, BaseMixins):
    """A connected app: one approval, for one user in one workspace at one scope. The row the UI lists and revokes."""

    __tablename__ = "oauth_grants"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    user_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    client_fk: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    """"marvin:read" or "marvin:read marvin:write"."""
    resource: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    """The MCP server it was issued for (RFC 8707); checked on every request."""
    client_name_snapshot: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    redirect_host: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    last_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    last_user_agent: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """user | admin | reuse_detected | membership_lost | policy"""

    __table_args__ = (
        sa.Index("ix_oauth_grants_user_id", "user_id"),
        sa.Index("ix_oauth_grants_group_id", "group_id"),
        sa.Index("ix_oauth_grants_client_fk", "client_fk"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass


class OAuthTokenModel(SqlAlchemyBase, BaseMixins):
    """An opaque access or refresh token of a grant (SHA-256 only). A refresh token is replaced on every use."""

    __tablename__ = "oauth_tokens"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    grant_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("oauth_grants.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """access | refresh"""
    token_lookup: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(NaiveDateTime, nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, nullable=True)
    """When a refresh token was exchanged for a new one (presenting it again after that is reuse)."""
    replaced_by: Mapped[GUID | None] = mapped_column(GUID, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("token_lookup", name="uq_oauth_tokens_token_lookup"),
        sa.Index("ix_oauth_tokens_grant_id", "grant_id"),
        sa.Index("ix_oauth_tokens_expires_at", "expires_at"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
