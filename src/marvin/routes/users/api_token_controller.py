"""
This module defines the FastAPI controller for managing user-specific API tokens
(long-lived tokens) within the Marvin application.

Upgraded to use secure hashed token storage matching API Clients security model.

Endpoints (all under /self/api-tokens for authenticated user):
- GET /self/api-tokens - List user's tokens
- POST /self/api-tokens - Create new token (returns plaintext token ONCE)
- GET /self/api-tokens/{id} - Get specific token
- PATCH /self/api-tokens/{id} - Update token metadata
- DELETE /self/api-tokens/{id} - Delete token
- POST /self/api-tokens/{id}/rotate - Rotate token (returns new plaintext token ONCE)
- POST /self/api-tokens/{id}/revoke - Revoke token (soft delete)
"""

from fastapi import HTTPException, status
from pydantic import UUID4

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.routers import UserAPIRouter
from marvin.schemas.user import (
    LongLiveTokenCreate,
    LongLiveTokenRead,
    LongLiveTokenUpdate,
    LongLiveTokenWithToken,
    TokenResponseDelete,
)
from marvin.services.event_bus_service.event_types import EventAPITokenData, EventOperation, EventTypes

router = UserAPIRouter(prefix="/self/api-tokens", tags=["User: Self Service"])


@controller(router)
class UserApiTokensController(BaseUserController):
    """
    Controller for managing user-specific API tokens (Personal Access Tokens).

    Security model:
    - Tokens are bcrypt-hashed in database (no plaintext storage)
    - Plaintext token shown only on create/rotate
    - Token format: marvin_tk_{43-character-random}
    - Supports rotation, revocation, usage tracking
    """

    def _announce(self, event_type: EventTypes, operation: EventOperation, token, verb: str) -> None:
        """api_token_created / _rotated / _revoked (platform scope, always audited): the token's name and owner —
        never its value or hash."""
        workspace_id = self.user.active_group_id or self.user.group_id  # stored with it, shown only to super admins
        if not workspace_id:
            return
        owner = getattr(self.user, "full_name", None) or self.user.username
        self.event_bus.dispatch(
            integration_id="api_token_management",
            group_id=workspace_id,
            event_type=event_type,
            document_data=EventAPITokenData(
                operation=operation,
                token_id=token.id,
                token_name=token.name,
                user_id=self.user.id,
                user_name=owner,
            ),
            message=f"Personal API token '{token.name}' {verb} for {owner}",
            user_id=self.user.id,
            entity_id=token.id,
            entity_type="api_token",
        )

    @router.get("", response_model=list[LongLiveTokenRead], summary="List API Tokens")
    def list_tokens(self) -> list[LongLiveTokenRead]:
        """
        List all API tokens for the authenticated user.

        Returns tokens without plaintext token string (security).
        Shows metadata: name, description, enabled status, last_used_at, etc.
        """
        # Filter tokens by current user
        all_tokens = self.repos.api_tokens.get_all(order_by="created_at")
        user_tokens = [t for t in all_tokens if t.user_id == self.user.id]
        return user_tokens

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=LongLiveTokenWithToken,
        summary="Create API Token",
    )
    def create_token(self, data: LongLiveTokenCreate) -> LongLiveTokenWithToken:
        """
        Create a new long-lived API token.

        **IMPORTANT**: The plaintext token is returned ONLY ONCE.
        Store it securely. It cannot be retrieved again.

        Token format: marvin_tk_{43-random-characters}

        Args:
            data: Token name, description, integration_id

        Returns:
            LongLiveTokenWithToken: Token metadata with plaintext token
        """
        # Inject user_id for token ownership
        token_data = data.model_dump()
        token_data["user_id"] = self.user.id

        # Repository handles token generation, hashing, and storage
        new_token = self.repos.api_tokens.create(token_data)

        self.logger.info(f"API Token '{data.name}' created for user {self.user.username}")
        self._announce(EventTypes.api_token_created, EventOperation.create, new_token, "created")
        return new_token

    @router.get("/{token_id}", response_model=LongLiveTokenRead, summary="Get API Token")
    def get_token(self, token_id: UUID4) -> LongLiveTokenRead:
        """
        Get a specific API token by ID.

        Users can only access their own tokens.

        Args:
            token_id: UUID of the token

        Returns:
            LongLiveTokenRead: Token metadata (no plaintext token)

        Raises:
            HTTPException: 404 if not found, 403 if not owned by user
        """
        token = self.repos.api_tokens.get_one(token_id)

        if not token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found.")

        # Verify ownership
        if token.user_id != self.user.id:
            self.logger.warning(f"User {self.user.id} attempted to access token {token_id} owned by {token.user_id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to access this token.")

        return token

    @router.patch("/{token_id}", response_model=LongLiveTokenRead, summary="Update API Token")
    def update_token(self, token_id: UUID4, data: LongLiveTokenUpdate) -> LongLiveTokenRead:
        """
        Update API token metadata (name, description, enabled status).

        Cannot change user_id or token_hash.

        Args:
            token_id: UUID of the token
            data: Fields to update (all optional)

        Returns:
            LongLiveTokenRead: Updated token metadata

        Raises:
            HTTPException: 404 if not found, 403 if not owned by user
        """
        # Verify token exists and belongs to user
        self.get_token(token_id)  # Reuses ownership check

        # Update token
        updated = self.repos.api_tokens.update(token_id, data)
        self.logger.info(f"API Token {token_id} updated by user {self.user.username}")
        return updated

    @router.delete("/{token_id}", response_model=TokenResponseDelete, summary="Delete API Token")
    def delete_token(self, token_id: UUID4) -> TokenResponseDelete:
        """
        Permanently delete an API token.

        Users can only delete their own tokens.

        Args:
            token_id: UUID of the token to delete

        Returns:
            TokenResponseDelete: Confirmation with token name

        Raises:
            HTTPException: 404 if not found, 403 if not owned by user
        """
        # Verify token exists and belongs to user
        self.get_token(token_id)  # Reuses ownership check

        # Delete token
        deleted = self.repos.api_tokens.delete(token_id)
        self.logger.info(f"API Token '{deleted.name}' (ID: {token_id}) deleted by user {self.user.username}")
        # Deleting a token revokes it too (it stops working), so the security record says so.
        self._announce(EventTypes.api_token_revoked, EventOperation.delete, deleted, "deleted")

        return TokenResponseDelete(token_delete=deleted.name)

    @router.post(
        "/{token_id}/rotate",
        response_model=LongLiveTokenWithToken,
        summary="Rotate API Token",
    )
    def rotate_token(self, token_id: UUID4) -> LongLiveTokenWithToken:
        """
        Rotate/regenerate the token for an API client.

        **IMPORTANT**:
        - The old token is invalidated immediately
        - The new token is returned ONLY ONCE
        - Store it securely. It cannot be retrieved again.

        Use this to:
        - Rotate tokens periodically for security
        - Regenerate if token may have been compromised
        - Replace token without deleting metadata

        Args:
            token_id: UUID of the token to rotate

        Returns:
            LongLiveTokenWithToken: Token metadata with new plaintext token

        Raises:
            HTTPException: 404 if not found, 403 if not owned by user
        """
        # Verify token exists and belongs to user
        token = self.get_token(token_id)  # Reuses ownership check

        # Rotate token
        rotated = self.repos.api_tokens.rotate_token(token_id)
        self.logger.info(f"API Token '{token.name}' (ID: {token_id}) rotated by user {self.user.username}")
        self._announce(EventTypes.api_token_rotated, EventOperation.update, rotated, "rotated")

        return rotated

    @router.post("/{token_id}/revoke", response_model=LongLiveTokenRead, summary="Revoke API Token")
    def revoke_token(self, token_id: UUID4) -> LongLiveTokenRead:
        """
        Revoke an API token (soft delete).

        Sets enabled=false and revoked_at timestamp.
        The token can no longer be used for authentication.

        Revoked tokens remain in the database for audit purposes.
        Use DELETE to permanently remove a token.

        Args:
            token_id: UUID of the token to revoke

        Returns:
            LongLiveTokenRead: Revoked token metadata

        Raises:
            HTTPException: 404 if not found, 403 if not owned by user
        """
        # Verify token exists and belongs to user
        token = self.get_token(token_id)  # Reuses ownership check

        # Revoke token
        revoked = self.repos.api_tokens.revoke(token_id)
        self.logger.info(f"API Token '{token.name}' (ID: {token_id}) revoked by user {self.user.username}")
        self._announce(EventTypes.api_token_revoked, EventOperation.update, revoked, "revoked")

        return revoked
