/**
 * Rows of Admin → Backups' bundle table (pages/admin/backups.astro) as the browser rebuilds them after a
 * create or a filter. Pure, so it is tested with node --test (backups.test.mjs); the page turns each cell
 * into DOM with textContent — a filename or workspace slug is text from the server, never markup.
 */

/** One workspace bundle, as GET /api/admin/backups lists it (and POST …/workspaces/{id} returns it). */
export type BackupFile = { filename: string; size: number; created_at: string; workspace_slug?: string | null };

/** A table cell: plain text, or the Download link. */
export type BackupCell = { className: string; text: string; link?: { href: string; download: string } };

/** The table's column headings, matching the server-rendered table. */
export const BACKUP_COLUMNS = ["Workspace", "Filename", "Size", "Created", ""] as const;

export const backupDownloadHref = (filename: string) => `/api/admin/backups/${encodeURIComponent(filename)}`;

/** One bundle's cells, in BACKUP_COLUMNS order; `size` and `date` format the numbers for people. */
export function backupCells(
  b: BackupFile,
  size: (bytes: number) => string,
  date: (iso: string) => string,
): BackupCell[] {
  return [
    { className: "slug-cell", text: b.workspace_slug ?? "" },
    { className: "filename-cell", text: b.filename },
    { className: "num-cell", text: size(b.size) },
    { className: "num-cell", text: date(b.created_at) },
    {
      className: "action-cell",
      text: "Download",
      link: { href: backupDownloadHref(b.filename), download: b.filename },
    },
  ];
}
