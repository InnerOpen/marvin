import assert from "node:assert/strict";
import { test } from "node:test";
import { entryActions } from "./entryActions.ts";

const schema = { fields: [{ key: "filmstrip", label: "Filmstrip (web page)" }, { key: "video", label: "Video" }, { key: "script_pdf", label: "Script (PDF)" }, { key: "cover", label: "Cover image" }] };
const base = { views: [], viewHref: (s) => `/v/${s}`, setups: [], site: null, assets: [], schema };

test("views and guided setups come first as the primary buttons, then files, then the site link", () => {
  const out = entryActions({
    ...base,
    views: [{ slug: "story-timeline", name: "Timeline" }],
    setups: [{ label: "Takes", href: "/w/takes" }],
    site: { href: "https://site/x" },
    assets: [{ role: "filmstrip", publicUrl: "https://cdn/f.html", mimeType: "text/html" }],
  });
  assert.deepEqual(out.map((a) => [a.label, a.tone, !!a.external]), [["Timeline", "primary", false], ["Takes", "primary", false], ["Filmstrip", "secondary", true], ["View on site", "secondary", true]]);
  assert.equal(out[0].href, "/v/story-timeline");
});

test("an attached web page, PDF or video is a link named by the field it fills; a picture or sound is not", () => {
  const out = entryActions({
    ...base,
    assets: [
      { role: "video", publicUrl: "https://cdn/v.mp4", mimeType: "video/mp4" },
      { role: "script_pdf", publicUrl: "https://cdn/s.pdf", mimeType: "application/pdf" },
      { role: "cover", publicUrl: "https://cdn/c.png", mimeType: "image/png" },
      { role: "audio", publicUrl: "https://cdn/a.mp3", mimeType: "audio/mpeg" },
    ],
  });
  assert.deepEqual(out.map((a) => a.label), ["Video", "Script"]);
});

test("a file with no field label falls back to its name, and the same file twice is one link", () => {
  const f = { role: "stray", name: "Notes page", publicUrl: "https://cdn/n.html", mimeType: "text/html; charset=utf-8" };
  assert.deepEqual(entryActions({ ...base, assets: [f, f] }).map((a) => a.label), ["Notes page"]);
});

test("the site link before publishing is a disabled button that says why", () => {
  const [site] = entryActions({ ...base, site: { disabled: true, hint: "Publish first." } });
  assert.deepEqual([site.label, site.disabled], ["View on site", "Publish first."]);
});

test("an entry with nothing to open has no actions", () => {
  assert.deepEqual(entryActions(base), []);
});
