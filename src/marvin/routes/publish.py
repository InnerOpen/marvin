"""Publishing API routes - read-only access for external sites via site client tokens."""

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.db.db_setup import generate_session
from marvin.db.models.groups import Groups
from marvin.repos.platform.assets import AssetsRepository
from marvin.schemas.platform import (
    CollectionRead,
    EntrySummary,
    EntryRead,
    AssetSummary,
    AssetRead,
)

router = APIRouter(prefix="/publish")


async def get_site_client_from_token(authorization: str | None = Header(None), db: Session = Depends(generate_session)):
    """
    Validate and extract site client from bearer token.

    Args:
        authorization: The Authorization header value
        db: Database session

    Returns:
        tuple: (site_client, group_slug, group_id)

    Raises:
        HTTPException: If token is invalid or expired
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid authorization header")

    token = authorization[7:]  # Remove "Bearer " prefix

    # TODO: Implement token validation
    # 1. Hash the token
    # 2. Look up site client by token hash
    # 3. Verify site client is active and not revoked
    # 4. Return site client and group

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


@router.get("/{group_slug}/collections", response_model=list[CollectionRead], summary="List Published Collections", tags=["Publishing API"])
async def list_collections(
    group_slug: str,
    site_client_info: tuple = Depends(get_site_client_from_token),
):
    """
    List all published collections for a workspace.

    Requires valid site client token with read:collections permission.
    Only returns collections and entries for the authenticated workspace.

    Args:
        group_slug: The slug of the workspace
        site_client_info: Validated site client and group info

    Returns:
        List of published collections
    """
    # TODO: Implement collection listing
    # 1. Verify group_slug matches site client's group
    # 2. Query collections in the group
    # 3. Respect collection visibility rules
    return []


@router.get("/{group_slug}/entries", response_model=list[EntrySummary], summary="List Published Entries", tags=["Publishing API"])
async def list_entries(
    group_slug: str,
    page: int = 1,
    limit: int = 20,
    collection_slug: str | None = None,
    entry_type: str | None = None,
    site_client_info: tuple = Depends(get_site_client_from_token),
):
    """
    List all published entries for a workspace.

    Requires valid site client token with read:published_entries permission.
    Only returns published entries and respects collection filters.

    Args:
        group_slug: The slug of the workspace
        page: Page number for pagination
        limit: Number of entries per page (max 100)
        collection_slug: Optional filter by collection
        entry_type: Optional filter by entry type
        site_client_info: Validated site client and group info

    Returns:
        Paginated list of published entries
    """
    # TODO: Implement entry listing
    # 1. Verify group_slug matches site client's group
    # 2. Query entries with status=published
    # 3. Apply collection and type filters
    # 4. Validate pagination limits
    # 5. Return paginated results
    return []


@router.get("/{group_slug}/entries/{entry_slug}", response_model=EntryRead, summary="Get Published Entry", tags=["Publishing API"])
async def get_entry(
    group_slug: str,
    entry_slug: str,
    site_client_info: tuple = Depends(get_site_client_from_token),
):
    """
    Get a specific published entry with full Markdown content.

    Requires valid site client token with read:published_entries permission.
    Only returns the entry if it's in published status.

    Args:
        group_slug: The slug of the workspace
        entry_slug: The slug of the entry
        site_client_info: Validated site client and group info

    Returns:
        Full entry with Markdown content and metadata

    Raises:
        HTTPException: If entry not found or not published
    """
    # TODO: Implement entry retrieval
    # 1. Verify group_slug matches site client's group
    # 2. Query entry by slug with status=published
    # 3. Return full entry with content and metadata
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found or not published")


@router.get("/{group_slug}/assets", response_model=list[AssetSummary], summary="List Published Assets", tags=["Publishing API"])
async def list_assets(
    group_slug: str,
    limit: int = 50,
    offset: int = 0,
    asset_type: str | None = None,
    db: Session = Depends(generate_session),
):
    """
    List all assets for a workspace.

    TODO: Add site client token authentication when site clients are implemented.
    For now, this is a read-only endpoint accessible without authentication.

    Args:
        group_slug: The slug of the workspace
        limit: Number of assets to return (max 100)
        offset: Number of assets to skip
        asset_type: Optional filter by asset type (image, document, video, etc.)
        db: Database session

    Returns:
        List of asset summaries
    """
    # Get workspace by slug
    workspace = db.query(Groups).filter(Groups.slug == group_slug).first()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workspace '{group_slug}' not found")

    # Validate pagination limits
    limit = min(limit, 100)

    # Query assets for this workspace
    repo = AssetsRepository(session=db, group_id=workspace.id)
    query = repo.query()

    # Apply asset_type filter if provided
    if asset_type:
        from marvin.db.models.platform import Assets

        query = query.filter(Assets.asset_type == asset_type)

    # Apply pagination
    assets = query.offset(offset).limit(limit).all()

    # Convert to AssetSummary (excludes internal fields)
    return [AssetSummary.model_validate(asset) for asset in assets]


@router.get("/{group_slug}/assets/{asset_slug}", response_model=AssetSummary, summary="Get Published Asset", tags=["Publishing API"])
async def get_asset(
    group_slug: str,
    asset_slug: str,
    db: Session = Depends(generate_session),
):
    """
    Get a specific asset by slug.

    TODO: Add site client token authentication when site clients are implemented.
    For now, this is a read-only endpoint accessible without authentication.

    Args:
        group_slug: The slug of the workspace
        asset_slug: The slug of the asset
        db: Database session

    Returns:
        Asset summary metadata

    Raises:
        HTTPException: If workspace or asset not found
    """
    # Get workspace by slug
    workspace = db.query(Groups).filter(Groups.slug == group_slug).first()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workspace '{group_slug}' not found")

    # Query asset by slug
    repo = AssetsRepository(session=db, group_id=workspace.id)
    try:
        asset = repo.get_one(match_value=asset_slug, match_key="slug")
        return AssetSummary.model_validate(asset)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset '{asset_slug}' not found in workspace '{group_slug}'")
