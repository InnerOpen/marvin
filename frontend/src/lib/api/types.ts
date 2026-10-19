export type WorkspaceRole = "OWNER" | "ADMIN" | "EDITOR" | "AUTHOR" | "VIEWER";

// SDK Types - Re-export from SDK for type compatibility
import type {
  PlatformAPIClient,
  PlatformCollection,
  PlatformEntry,
  PlatformEntryType,
} from "@inneropen/marvin-sdk/platform";

export type EntryRead = PlatformEntry;
export type EntryTypeRead = PlatformEntryType;
export type CollectionRead = PlatformCollection;
export type APIClientRead = PlatformAPIClient;

// Resource types
export interface ResourceRead {
  id: string;
  slug: string;
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
