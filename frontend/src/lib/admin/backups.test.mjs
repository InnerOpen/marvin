// Admin → Backups table rows (backups.ts). Run with `npm test`.
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { BACKUP_COLUMNS, backupCells, backupDownloadHref } from "./backups.ts";

const size = (n) => `${n} B`;
const date = (iso) => `on ${iso}`;

describe("backupCells", () => {
  test("one cell per column, in order, with the classes the page styles", () => {
    const cells = backupCells(
      { filename: "acme-2026.zip", size: 12, created_at: "2026-10-07", workspace_slug: "acme" },
      size,
      date,
    );
    assert.equal(cells.length, BACKUP_COLUMNS.length);
    assert.deepEqual(
      cells.map((c) => [c.className, c.text]),
      [
        ["slug-cell", "acme"],
        ["filename-cell", "acme-2026.zip"],
        ["num-cell", "12 B"],
        ["num-cell", "on 2026-10-07"],
        ["action-cell", "Download"],
      ],
    );
    assert.deepEqual(cells[4].link, { href: "/api/admin/backups/acme-2026.zip", download: "acme-2026.zip" });
  });

  test("server strings stay text: markup in a filename or slug is carried as is, for textContent", () => {
    const evil = '<img src=x onerror="alert(1)">.zip';
    const cells = backupCells({ filename: evil, size: 1, created_at: "x", workspace_slug: "<b>ws</b>" }, size, date);
    assert.equal(cells[0].text, "<b>ws</b>");
    assert.equal(cells[1].text, evil);
    assert.equal(cells[4].link.download, evil);
    assert.equal(cells[4].link.href, `/api/admin/backups/${encodeURIComponent(evil)}`);
    assert.ok(!cells[4].link.href.includes("<") && !cells[4].link.href.includes('"'));
  });

  test("a bundle without a workspace slug gets an empty cell", () => {
    assert.equal(backupCells({ filename: "f.zip", size: 0, created_at: "x" }, size, date)[0].text, "");
    assert.equal(
      backupCells({ filename: "f.zip", size: 0, created_at: "x", workspace_slug: null }, size, date)[0].text,
      "",
    );
  });

  test("the download path encodes the filename", () => {
    assert.equal(backupDownloadHref("a b/c?.zip"), "/api/admin/backups/a%20b%2Fc%3F.zip");
  });
});
