// lib/captionCheck.ts: what a social.post step's caption check sends, and how each network's verdict is drawn.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { captionRequest, captionResultsHtml, isTemplate } from "./captionCheck.ts";

describe("what is checked", () => {
  test("the step's text, its link and a named integration", () => {
    assert.deepEqual(captionRequest('{"text": "Hello", "link": " https://x.example "}', "ig"), {
      text: "Hello",
      link: "https://x.example",
      integrations: ["ig"],
    });
  });

  test("every network when no integration is named, or it is a template", () => {
    assert.deepEqual(captionRequest('{"text": "Hi"}', ""), { text: "Hi" });
    assert.deepEqual(captionRequest('{"text": "Hi"}', "${event.integration}"), { text: "Hi" });
  });

  test("nothing until there is text and the JSON parses", () => {
    assert.equal(captionRequest("", ""), null);
    assert.equal(captionRequest('{"text": "  "}', ""), null);
    assert.equal(captionRequest("{oops", ""), null);
    assert.equal(captionRequest('{"text": 5}', ""), null);
  });

  test("a template is recognised", () => {
    assert.equal(isTemplate("New: ${entry.title}"), true);
    assert.equal(isTemplate("New post"), false);
  });
});

describe("the verdict", () => {
  const ig = {
    network: "instagram", name: "Instagram", unit: "characters", length: 2300, max: 2200, over: true,
    visibleText: "Hey <b>guys</b>", cut: true,
    issues: [
      { code: "opens_with_greeting", message: "It opens with a greeting", severity: "warn" },
      { code: "too_long", message: "100 too many", severity: "error" },
    ],
  };

  test("the count, the visible window with … more, errors first, all escaped", () => {
    const html = captionResultsHtml([ig], "Hey guys");
    assert.match(html, /cc-count over">2300 \/ 2200 characters/);
    assert.match(html, /Hey &lt;b&gt;guys&lt;\/b&gt;<span class="cc-more">… more<\/span>/);
    assert.ok(html.indexOf("100 too many") < html.indexOf("It opens with a greeting"));
  });

  test("a clean caption says so; a network without limits says that; none connected says that", () => {
    assert.match(captionResultsHtml([{ network: "bluesky", name: "Bluesky", length: 10, max: 300, issues: [] }], "x"), /Looks fine for Bluesky/);
    assert.match(captionResultsHtml([{ network: "x", name: "X", unknown: true, issues: [] }], "x"), /states no limits/);
    assert.match(captionResultsHtml([], "x"), /No connected network posts yet/);
  });

  test("a template gets a note that the real text comes at run time", () => {
    assert.match(captionResultsHtml([{ network: "bluesky", length: 1, max: 300, issues: [] }], "${entry.title}"), /Checked as written/);
  });
});
