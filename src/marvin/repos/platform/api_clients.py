"""API clients repository."""

import secrets
from datetime import UTC, datetime
from typing import Any

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.core.config import get_app_settings
from marvin.core.security.hasher import find_token, get_hasher, token_lookup
from marvin.db.models.platform import APIClients
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform import APIClientRead, APIClientWithToken

settings = get_app_settings()


class APIClientsRepository(GroupRepositoryGeneric[APIClientRead, APIClients]):
    """Repository for workspace-scoped API clients."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=APIClients,
            schema=APIClientRead,
            group_id=group_id,
        )

    def create(self, data: Any) -> APIClientWithToken:
        """
        Create a new API client with token generation.

        Returns:
            APIClientWithToken: The created API client with plaintext token.
                               This is the ONLY time the plaintext token is shown.
        """
        data_dict = data if isinstance(data, dict) else data.model_dump()

        # Inject group_id
        if self.group_id:
            data_dict["group_id"] = self.group_id

        # Auto-generate slug from name if not provided
        from slugify import slugify

        if not data_dict.get("slug"):
            data_dict["slug"] = slugify(data_dict["name"])

        # Generate secure token with marvin_sk_ prefix
        plaintext_token = self._generate_token()

        # Hash the token for storage (never store plaintext)
        data_dict["token_hash"] = get_hasher().hash(plaintext_token)
        data_dict["token_lookup"] = token_lookup(plaintext_token)

        # Ensure permissions is a dict (default if not provided)
        if "permissions" not in data_dict or data_dict["permissions"] is None:
            data_dict["permissions"] = {
                "read:published_entries": True,
                "read:collections": True,
                "read:assets": True,
            }

        # Create the API client
        api_client_model = self.model(session=self.session, **data_dict)
        self.session.add(api_client_model)
        self.session.commit()
        self.session.refresh(api_client_model)

        # Return with plaintext token (shown once)
        return APIClientWithToken(
            id=api_client_model.id,
            group_id=api_client_model.group_id,
            name=api_client_model.name,
            slug=api_client_model.slug,
            description=api_client_model.description,
            permissions=api_client_model.permissions,
            token=plaintext_token,  # IMPORTANT: Only shown here
            enabled=api_client_model.enabled,
            created_at=api_client_model.created_at,
        )

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None, _allow_token_hash: bool = False) -> APIClientRead:
        """Update API client (cannot change group_id or token unless explicitly allowed)."""
        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)

        # Prevent group_id changes (always)
        data_dict.pop("group_id", None)

        # Prevent token_hash changes unless explicitly allowed (e.g., from rotate_token)
        if not _allow_token_hash:
            data_dict.pop("token_hash", None)
            data_dict.pop("token_lookup", None)

        return super().update(match_value, data_dict, match_key=match_key)

    def rotate_token(self, api_client_id: UUID4) -> APIClientWithToken:
        """
        Rotate/regenerate the token for an API client.

        Args:
            api_client_id: ID of API client to rotate token for

        Returns:
            APIClientWithToken with new plaintext token (shown once)
        """
        # Get the API client
        api_client = self.get_one(api_client_id)
        if not api_client:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API client not found.")

        # Generate new token
        plaintext_token = self._generate_token()

        # Update with new token hash (allow token_hash update via internal flag)
        updated = self.update(
            api_client_id,
            {"token_hash": get_hasher().hash(plaintext_token), "token_lookup": token_lookup(plaintext_token)},
            _allow_token_hash=True,
        )

        # Return with new plaintext token
        return APIClientWithToken(
            id=updated.id,
            group_id=updated.group_id,
            name=updated.name,
            slug=updated.slug,
            description=getattr(updated, "description", None),
            permissions=updated.permissions,
            token=plaintext_token,  # IMPORTANT: Only shown here
            enabled=updated.enabled,
            created_at=updated.created_at,
        )

    def revoke(self, api_client_id: UUID4) -> APIClientRead:
        """
        Revoke an API client token (soft delete).

        Args:
            api_client_id: ID of API client to revoke

        Returns:
            Updated API client with revoked_at timestamp
        """
        return self.update(
            api_client_id,
            {
                "enabled": False,
                "revoked_at": datetime.now(UTC),
            },
        )

    def validate_token(self, plaintext_token: str) -> APIClients | None:
        """
        Validate an API client token and return the API client if valid.

        Args:
            plaintext_token: The bearer token from Authorization header

        Returns:
            APIClients model if valid and enabled, None otherwise
        """
        # Query all enabled API clients for this group
        query = self.session.query(APIClients).filter(
            APIClients.enabled == True,  # noqa: E712
            APIClients.revoked_at.is_(None),
        )

        if self.group_id:
            query = query.filter(APIClients.group_id == self.group_id)

        api_client = find_token(query, APIClients, plaintext_token)
        if api_client is not None:
            api_client.last_used_at = datetime.now(UTC)
            self.session.commit()
        return api_client

    def get_by_slug(self, slug: str) -> APIClientRead | None:
        """
        Get an API client by its slug.

        Args:
            slug: The slug of the API client

        Returns:
            APIClientRead if found, None otherwise
        """
        return self.get_one(slug, key="slug")

    def _generate_token(self) -> str:
        """
        Generate a secure API token with configurable prefix.

        Format: {prefix}{random-base64url-string}
        Uses settings.SECURITY_TOKEN_PREFIX_CLIENT and settings.SECURITY_TOKEN_RANDOM_BYTES
        """
        token_prefix = settings.SECURITY_TOKEN_PREFIX_CLIENT
        random_part = secrets.token_urlsafe(settings.SECURITY_TOKEN_RANDOM_BYTES)
        return f"{token_prefix}{random_part}"
