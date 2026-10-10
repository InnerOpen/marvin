"""Long-lived tokens repository."""

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.core.config import get_app_settings
from marvin.core.security.hasher import find_token, get_hasher, token_lookup
from marvin.db.models.users.users import LongLiveToken
from marvin.repos.repository_generic import RepositoryGeneric
from marvin.schemas.user.user import LongLiveTokenRead, LongLiveTokenWithToken

settings = get_app_settings()


class LongLiveTokensRepository(RepositoryGeneric[LongLiveTokenRead, LongLiveToken]):
    """
    Repository for managing user long-lived API tokens (Personal Access Tokens).

    Security model matches APIClients:
    - Tokens are hashed with bcrypt before storage
    - Plaintext tokens shown only once (on create/rotate)
    - Supports token rotation, soft deletion, usage tracking
    """

    def __init__(self, session: Session, primary_key: str, sql_model, schema) -> None:
        super().__init__(
            session=session,
            primary_key=primary_key,
            sql_model=sql_model,
            schema=schema,
        )

    def create(self, data: Any) -> LongLiveTokenWithToken:
        """
        Create a new long-lived API token with secure token generation.

        Returns:
            LongLiveTokenWithToken: The created token with plaintext token.
                                   This is the ONLY time the plaintext token is shown.
        """
        data_dict = data if isinstance(data, dict) else data.model_dump()

        # Inject user_id and created_by (same user creates their own tokens)
        # Note: user_id should be provided in data from controller
        if "created_by" not in data_dict:
            data_dict["created_by"] = data_dict.get("user_id")

        # Generate secure token with marvin_tk_ prefix
        plaintext_token = self._generate_token()

        # Hash the token for storage (never store plaintext)
        data_dict["token_hash"] = get_hasher().hash(plaintext_token)
        data_dict["token_lookup"] = token_lookup(plaintext_token)

        # Set enabled by default
        if "enabled" not in data_dict:
            data_dict["enabled"] = True

        # Create the token record
        token_model = self.model(session=self.session, **data_dict)
        self.session.add(token_model)
        self.session.commit()
        self.session.refresh(token_model)

        # Return with plaintext token (shown once)
        return LongLiveTokenWithToken(
            id=token_model.id,
            user_id=token_model.user_id,
            name=token_model.name,
            description=token_model.description,
            enabled=token_model.enabled,
            token=plaintext_token,  # IMPORTANT: Only shown here
            created_at=token_model.created_at,
        )

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None) -> LongLiveTokenRead:
        """
        Update token metadata (cannot change user_id or token_hash).
        """
        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)

        # Prevent changing user ownership or token hash
        data_dict.pop("user_id", None)
        data_dict.pop("token_hash", None)
        data_dict.pop("created_by", None)

        return super().update(match_value, data_dict, match_key=match_key)

    def rotate_token(self, token_id: UUID4) -> LongLiveTokenWithToken:
        """
        Rotate/regenerate the token for a long-lived API token.

        The old token is invalidated immediately. The new token is returned
        ONCE and should be stored securely by the user.

        Args:
            token_id: ID of token to rotate

        Returns:
            LongLiveTokenWithToken with new plaintext token (shown once)

        Raises:
            HTTPException: 404 if token not found
        """
        # Get the token
        token = self.get_one(token_id)
        if not token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found.")

        # Generate new token
        plaintext_token = self._generate_token()
        new_hash = get_hasher().hash(plaintext_token)

        # Update token hash directly (bypass schema validation which excludes token_hash)
        db_token = self.session.query(LongLiveToken).filter(LongLiveToken.id == str(token_id)).first()
        if not db_token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found.")

        db_token.token_hash = new_hash
        db_token.token_lookup = token_lookup(plaintext_token)
        self.session.commit()
        self.session.refresh(db_token)

        # Return schema with new token
        updated = self.schema.model_validate(db_token)

        # Return with new plaintext token
        return LongLiveTokenWithToken(
            id=updated.id,
            user_id=updated.user_id,
            name=updated.name,
            description=updated.description,
            enabled=updated.enabled,
            token=plaintext_token,  # IMPORTANT: Only shown here
            created_at=updated.created_at,
        )

    def revoke(self, token_id: UUID4) -> LongLiveTokenRead:
        """
        Revoke a token (soft delete).

        Sets enabled=false and revoked_at timestamp. The token can no longer
        be used for authentication.

        Args:
            token_id: ID of token to revoke

        Returns:
            Updated token with revoked_at timestamp
        """
        return self.update(
            token_id,
            {
                "enabled": False,
                "revoked_at": datetime.now(UTC),
            },
        )

    def validate_token(self, plaintext_token: str, user_id: UUID4 | None = None) -> LongLiveToken | None:
        """
        Validate a token by checking its hash and update last_used_at.

        Args:
            plaintext_token: The bearer token from Authorization header
            user_id: Optional user ID to scope the search (performance optimization)

        Returns:
            LongLiveToken model if valid and enabled, None otherwise
        """
        # Query enabled, non-revoked tokens
        query = self.session.query(LongLiveToken).filter(
            LongLiveToken.enabled == True,  # noqa: E712
            LongLiveToken.revoked_at.is_(None),
        )

        # Optionally scope to specific user for performance
        if user_id:
            query = query.filter(LongLiveToken.user_id == user_id)

        token = find_token(query, LongLiveToken, plaintext_token)
        if token is not None:
            token.last_used_at = datetime.now(UTC)
            self.session.commit()
        return token

    def _generate_token(self) -> str:
        """
        Generate a secure API token with configurable prefix.

        Format: {prefix}{random-base64url-string}
        Uses settings.SECURITY_TOKEN_PREFIX_USER and settings.SECURITY_TOKEN_RANDOM_BYTES
        """
        token_prefix = settings.SECURITY_TOKEN_PREFIX_USER
        random_part = secrets.token_urlsafe(settings.SECURITY_TOKEN_RANDOM_BYTES)
        return f"{token_prefix}{random_part}"
