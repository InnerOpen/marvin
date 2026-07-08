// Enums
export type EntryStatus = "inbox" | "processing" | "draft" | "needs_review" | "approved" | "published" | "archived";

export type WorkspaceRole = "OWNER" | "ADMIN" | "EDITOR" | "AUTHOR" | "VIEWER";

export type AssetPlacementRole = "hero" | "featured" | "support" | "inline" | "download" | string;

export type AssetPlacementUsage = "material" | "process" | "detail" | "texture" | "workshop" | string;

/**
 * Asset type classification
 */
export type AssetType = "image" | "document" | "video" | "audio" | "archive" | "svg" | "other";

/**
 * Skinny Asset - Core asset data without placement metadata
 * This is the base asset record from the database
 */
export interface Asset {
  id: string;
  slug: string;
  name: string;
  mimeType: string;
  assetType: AssetType;
  fileSize: number;
  width?: number | null;
  height?: number | null;
  altText?: string | null;
  description?: string | null;
  publicUrl?: string | null;
  metadata?: Record<string, unknown> | null;
}

/**
 * Asset Placement - Entry-specific usage metadata
 * Describes how an asset is used within a specific entry context
 */
export interface AssetPlacement {
  assetId: string;
  role?: AssetPlacementRole | null;
  usage?: AssetPlacementUsage | null;
  position?: number;
  focalPoint?: string | null;
  caption?: string | null;
  placementMetadata?: Record<string, unknown> | null;
}

/**
 * Entry Asset - Asset + Placement combined for entry context
 * Used when displaying assets within an entry
 */
export interface EntryAsset extends Asset {
  placement: AssetPlacement;
}

/**
 * @deprecated Use Asset and AssetPlacement instead
 * Legacy combined type for backwards compatibility
 */
export interface MarvinAsset {
  id: string;
  slug: string;
  name: string;
  url?: string;
  mimeType: string;
  altText?: string | null;
  fileSize?: number;
  width?: number | null;
  height?: number | null;
  description?: string | null;
  metadata?: Record<string, unknown> | null;
  role?: AssetPlacementRole | null;
  usage?: AssetPlacementUsage | null;
  position?: number;
  focalPoint?: string | null;
  caption?: string | null;
  placementMetadata?: Record<string, unknown> | null;
}

// MarvinEntry is for sample/test data - uses snake_case for legacy compatibility
export interface MarvinEntry {
  id: string;
  slug: string;
  title: string;
  entry_type: string;
  entryTypeId: string;
  groupId: string;
  summary?: string | null;
  content_markdown?: string;
  frontmatter?: Record<string, unknown> | null;
  metadata_json?: Record<string, unknown> | null;
  status: EntryStatus;
  published_at?: string | null;
  collections?: string[];
  resources?: string[];
  assets?: MarvinAsset[];
}

// SDK Types - Re-export from SDK for type compatibility
import type {
  PlatformEntry,
  PlatformEntryType,
  PlatformCollection,
  PlatformAPIClient
} from '@inneropen/marvin-sdk/platform';

export type EntryRead = PlatformEntry;
export type EntryTypeRead = PlatformEntryType;
export type CollectionRead = PlatformCollection;
export type APIClientRead = PlatformAPIClient;

export interface SiteClient {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  scopes?: string[];
  created_at?: string;
}

// API List Response (pagination wrapper)
export interface ApiListResponse<T> {
  data: T[];
  total?: number;
  page?: number;
  pageSize?: number;
}

// Collection types (for create/update - read type comes from SDK)
export interface CollectionCreate {
  slug: string;
  name: string;
  description?: string | null;
}

export interface CollectionUpdate {
  slug?: string;
  name?: string;
  description?: string | null;
}

// Resource types
export interface ResourceRead {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
}

export interface ResourceCreate {
  slug: string;
  name: string;
  description?: string | null;
}

export interface ResourceUpdate {
  slug?: string;
  name?: string;
  description?: string | null;
}

// Entry Type (create/update - read type comes from SDK)
export interface EntryTypeCreate {
  slug: string;
  name: string;
  description?: string | null;
  schema?: Record<string, unknown> | null;
}

export interface EntryTypeUpdate {
  slug?: string;
  name?: string;
  description?: string | null;
  schema?: Record<string, unknown> | null;
}

// Entry CRUD types
export interface EntryCreate {
  slug: string;
  title: string;
  entryTypeId: string;
  summary?: string | null;
  description?: string | null;
  contentMarkdown?: string | null;
  status?: string;
  publishedAt?: string | null;
  metadataJson?: Record<string, unknown> | null;
}

export interface EntryUpdate {
  slug?: string;
  title?: string;
  summary?: string | null;
  description?: string | null;
  contentMarkdown?: string | null;
  status?: string;
  publishedAt?: string | null;
  metadataJson?: Record<string, unknown> | null;
}

// API Client types (create/update - read type comes from SDK)
export interface APIClientCreate {
  name: string;
  description?: string | null;
}

export interface APIClientUpdate {
  name?: string;
  description?: string | null;
  enabled?: boolean;
}

export interface APIClientWithToken extends APIClientRead {
  token: string;
}

export interface WorkspaceSiteInfo {
  id: string;
  name: string;
  description?: string | null;
}

// Workspace types
export interface GroupRead {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
}

export interface GroupCreate {
  slug: string;
  name: string;
  description?: string | null;
}

export interface GroupAdminUpdate {
  slug?: string;
  name?: string;
  description?: string | null;
}

export interface WorkspaceWithMembership {
  workspace: GroupRead;
  role: WorkspaceRole;
  is_active: boolean;
}

export interface WorkspaceActivationRequest {
  workspace_id: string;
}

// Workspace Member types
export interface WorkspaceMembershipRead {
  userId: string;
  username: string;
  email: string;
  role: WorkspaceRole;
  joinedAt: string;
}

export interface WorkspaceMemberCreate {
  userId: string;
  role: WorkspaceRole;
}

export interface WorkspaceMemberUpdate {
  role: WorkspaceRole;
}

// Invite types
export interface InviteTokenRead {
  id: string;
  token: string;
  role: WorkspaceRole;
  uses_remaining?: number | null;
  expires_at?: string | null;
  created_at: string;
}

export interface InviteTokenCreate {
  role: WorkspaceRole;
  uses_remaining?: number | null;
  expires_at?: string | null;
}

export interface EmailInvitation {
  email: string;
  role: WorkspaceRole;
}

// Group Preferences types
export interface GroupPreferencesRead {
  groupId: string;
  privateGroup: boolean;
  firstDayOfWeek: number;
  siteTitle?: string | null;
  siteTagline?: string | null;
  siteDescription?: string | null;
  siteCanonicalUrl?: string | null;
  siteLogo?: string | null;
  siteFavicon?: string | null;
  siteLocale: string | null;
  siteTimezone: string | null;
  siteContactEmail?: string | null;
  siteSocialJson?: Record<string, unknown> | null;
  siteMetadataJson?: Record<string, unknown> | null;
}

export interface GroupPreferencesUpdate {
  privateGroup?: boolean;
  firstDayOfWeek?: number;
  siteTitle?: string | null;
  siteTagline?: string | null;
  siteDescription?: string | null;
  siteCanonicalUrl?: string | null;
  siteLogo?: string | null;
  siteFavicon?: string | null;
  siteLocale?: string | null;
  siteTimezone?: string | null;
  siteContactEmail?: string | null;
  siteSocialJson?: Record<string, unknown> | null;
  siteMetadataJson?: Record<string, unknown> | null;
}
