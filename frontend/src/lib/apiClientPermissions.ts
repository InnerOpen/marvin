// The permissions an API client can be granted, shared by the create and edit forms. Keys are the
// canonical strings the publishing routes check (marvin.core.permissions.Permissions);
// tests/test_api_clients.py fails if this list drifts from what the backend enforces.

export type PermissionGroup = "Content" | "Forms";

export type APIClientPermission = {
  key: string;
  label: string;
  description: string;
  group: PermissionGroup;
  /** Ticked on a new client — matches the backend's default permissions. */
  isDefault: boolean;
};

export const API_CLIENT_PERMISSIONS: readonly APIClientPermission[] = [
  {
    key: "read:published_entries",
    label: "Read Published Entries",
    description: "Access all published entries (production sites)",
    group: "Content",
    isDefault: true,
  },
  {
    key: "read:all_entries",
    label: "Read All Entries",
    description: "Access entries regardless of status, drafts included (preview environments, admin tools)",
    group: "Content",
    isDefault: false,
  },
  {
    key: "read:collections",
    label: "Read Collections",
    description: "Access collection metadata and entry lists",
    group: "Content",
    isDefault: true,
  },
  {
    key: "read:assets",
    label: "Read Assets",
    description: "Access uploaded media files",
    group: "Content",
    isDefault: true,
  },
  {
    key: "read:resources",
    label: "Read Resources",
    description: "Access resource metadata",
    group: "Content",
    isDefault: false,
  },
  {
    key: "write:form_submissions",
    label: "Submit Forms",
    description: "Accept form submissions (newsletter sign-ups, contact forms) from the site",
    group: "Forms",
    isDefault: false,
  },
  {
    key: "write:public_entries",
    label: "Submit Public Entries",
    description: "Create inbox entries of submittable entry types from the site (also allows form submits)",
    group: "Forms",
    isDefault: false,
  },
];

export const PERMISSION_GROUPS: readonly PermissionGroup[] = ["Content", "Forms"];

const KNOWN_KEYS = new Set(API_CLIENT_PERMISSIONS.map((p) => p.key));

/** Granted keys on a client that the form doesn't list (legacy or never-enforced), so they can still be seen and removed. */
export function unlistedGrantedKeys(permissions: Record<string, unknown> | null | undefined): string[] {
  return Object.entries(permissions ?? {})
    .filter(([key, value]) => value === true && !KNOWN_KEYS.has(key))
    .map(([key]) => key)
    .sort();
}

/** The keys to pre-tick: the client's grants when editing, the backend defaults when creating. */
export function initiallyGranted(permissions?: Record<string, unknown> | null): Set<string> {
  if (!permissions) return new Set(API_CLIENT_PERMISSIONS.filter((p) => p.isDefault).map((p) => p.key));
  return new Set(Object.keys(permissions).filter((key) => permissions[key] === true));
}

/** Permissions JSON from the ticked checkbox names — the whole dict, since the backend replaces it on update. */
export function permissionsFromChecked(checkedKeys: Iterable<string>): Record<string, boolean> {
  const permissions: Record<string, boolean> = {};
  for (const key of checkedKeys) {
    if (key) permissions[key] = true;
  }
  return permissions;
}
