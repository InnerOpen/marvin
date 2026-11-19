// Times in an Ask answer as links to the cited recording's moment (askTimeLinks.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { answerMarkdownHtml, timeLinksIn } from "./askTimeLinks.ts";

const REC = "a6e76f6c-1362-43f3-8bfa-c11642c974d2";
const REC_TITLE = "Recording Nov 18, 2026, 5:46:18 PM";
// The sources of the answer Jared got: one timed recording among its transcript files (no startSeconds).
const ONE = [
  { entityType: "asset", entityId: REC, title: REC_TITLE, startSeconds: 0 },
  { entityType: "asset", entityId: "378c9a4e", title: `Transcript: ${REC_TITLE}` },
  { entityType: "asset", entityId: "b3e7d536", title: `Transcript with times: ${REC_TITLE}` },
];
const A = { entityType: "asset", entityId: "aaa", title: "Morning walk", startSeconds: 12 };
const B = { entityType: "asset", entityId: "bbb", title: "Evening call", startSeconds: 0 };

/** [linked text, seconds, asset] for each link `timeLinksIn` finds. */
const found = (text, sources) =>
  timeLinksIn(text, sources).map((l) => [text.slice(l.start, l.end), l.seconds, l.assetId]);

describe("timeLinksIn", () => {
  test("one timed recording: every time is its, bracketed or not, h:mm:ss or m:ss", () => {
    assert.deepEqual(found("**[0:00:10]** — “So, it’s 10 seconds now…”", ONE), [["[0:00:10]", 10, REC]]);
    assert.deepEqual(found("**0:00:00** — “I’m trying…”", ONE), [["0:00:00", 0, REC]]);
    assert.deepEqual(found("at 1:05 and again at [12:30]", ONE), [
      ["1:05", 65, REC],
      ["[12:30]", 750, REC],
    ]);
    assert.deepEqual(found("[1:02:03] later", ONE), [["[1:02:03]", 3723, REC]]);
  });

  test("a time inside a cited title is not one (the recording's own name holds 5:46:18)", () => {
    assert.deepEqual(found(`Found it. In **${REC_TITLE}**: [0:00:10] words`, ONE), [["[0:00:10]", 10, REC]]);
    assert.deepEqual(found(`the full transcript for ${REC_TITLE.toLowerCase()}`, ONE), []);
  });

  test("nonsense and look-alikes stay text", () => {
    for (const text of [
      "99:99",
      "1:60",
      "1:61:00",
      "0:00:99",
      "at 5:46 PM",
      "at 5:46pm",
      "11:30 a.m.",
      "2026-11-18T17:46:18Z",
      "0:10.5",
      "00:00:10,500 --> 00:00:12,000",
      "a ratio 16:9",
      "http://host:8080/x",
      "v1:23:45x",
      "1:2:3",
    ])
      assert.deepEqual(found(text, ONE), [], text);
  });

  test("a lone bracket stays outside the link", () => {
    assert.deepEqual(found("from [0:10 on", ONE), [["0:10", 10, REC]]);
    assert.deepEqual(found("until 0:10] then", ONE), [["0:10", 10, REC]]);
  });

  test("no timed recording among the sources: nothing is linked", () => {
    assert.deepEqual(found("[0:00:10] words", ONE.slice(1)), []);
    assert.deepEqual(found("[0:00:10] words", []), []);
    assert.deepEqual(found("[0:00:10] words", null), []);
    assert.deepEqual(
      found("[0:00:10] words", [{ entityType: "entry", entityId: "e1", title: "Notes", startSeconds: 3 }]),
      [],
    );
  });

  test("/ask's retrieved_sources (snake_case, a source per chunk) count once", () => {
    const retrieved = [
      { entity_type: "asset", entity_id: REC, title: REC_TITLE, start_seconds: 0 },
      { entity_type: "asset", entity_id: REC, title: REC_TITLE, start_seconds: 30 },
    ];
    assert.deepEqual(found("at [0:00:40]", retrieved), [["[0:00:40]", 40, REC]]);
  });

  test("several timed recordings: a time is the one named nearest before it on its line", () => {
    const both = [A, B];
    assert.deepEqual(found("In Morning walk at 0:12, then in Evening call at [0:00:03].", both), [
      ["0:12", 12, "aaa"],
      ["[0:00:03]", 3, "bbb"],
    ]);
    assert.deepEqual(found("**morning walk** — [0:00:05] hello", both), [["[0:00:05]", 5, "aaa"]]);
  });

  test("several timed recordings: an unnamed time, or one named on another line or after it, stays text", () => {
    const both = [A, B];
    assert.deepEqual(found("[0:00:05] hello", both), []);
    assert.deepEqual(found("Morning walk:\n[0:00:05] hello", both), []);
    assert.deepEqual(found("[0:00:05] in Morning walk", both), []);
  });

  test("several timed recordings with the same title: never a guess", () => {
    const twins = [A, { ...A, entityId: "ccc" }];
    assert.deepEqual(found("Morning walk at 0:12", twins), []);
  });

  test("the longer title wins where two end at the same place", () => {
    const longer = { entityType: "asset", entityId: "ddd", title: "Long Morning walk", startSeconds: 0 };
    assert.deepEqual(found("Long Morning walk at 0:12", [A, longer]), [["0:12", 12, "ddd"]]);
    assert.deepEqual(found("A Morning walk at 0:12", [A, longer]), [["0:12", 12, "aaa"]]);
  });

  test("positions count across lines", () => {
    const text = "first\nsecond [0:00:10]";
    const [link] = timeLinksIn(text, ONE);
    assert.equal(text.slice(link.start, link.end), "[0:00:10]");
  });
});

const href = (s) => `/workspace/assets/${REC}/view?t=${s}`;

describe("answerMarkdownHtml", () => {
  test("Jared's answer, one timed recording cited: its times are links to that moment, the title is not", () => {
    const md = [
      `Found it. In **${REC_TITLE}**:`,
      "",
      "- **0:00:00** — “I’m trying to record a video on my phone and have it managed and uploaded to our channel.”",
      "- **[0:00:10]** — “So, it’s 10 seconds now, let’s see how long it says and what kind of audio is it.”",
    ].join("\n");
    const html = answerMarkdownHtml(md, ONE);
    assert.ok(
      html.includes(`<strong><a href="${href(0)}" title="Play ${REC_TITLE} from 0:00">0:00:00</a></strong>`),
      html,
    );
    assert.ok(
      html.includes(`<strong><a href="${href(10)}" title="Play ${REC_TITLE} from 0:10">[0:00:10]</a></strong>`),
      html,
    );
    assert.ok(html.includes(`<strong>${REC_TITLE}</strong>`), html);
    assert.equal((html.match(/<a /g) ?? []).length, 2);
  });

  test("the full transcript as a quote, one line each, bold or not", () => {
    const md = "> **[0:00:00]** I’m trying.  \n> **[0:00:10]** So, it’s 10.\n\n> [0:00:20] plain\n\n- [0:00:30] item";
    const html = answerMarkdownHtml(md, ONE);
    for (const s of [0, 10, 20, 30]) assert.ok(html.includes(`href="${href(s)}"`), `t=${s}`);
  });

  test("escaped brackets: the time inside them is the link", () => {
    const html = answerMarkdownHtml("\\[0:00:10\\] words", ONE);
    assert.ok(html.includes(`[<a href="${href(10)}"`) && html.includes(">0:00:10</a>]"), html);
  });

  test("code, links and raw HTML are left alone", () => {
    const md = [
      "`[0:00:10]` and",
      "",
      "```",
      "0:00:20",
      "```",
      "",
      '[at 0:00:30](https://example.com) <a href="https://example.com">0:00:40</a> <code>0:00:50</code> <span>0:01:00</span>',
      "",
      "<div>0:01:10</div>",
    ].join("\n");
    const html = answerMarkdownHtml(md, ONE);
    assert.deepEqual(html.match(/\/view\?t=\d+/g), ["/view?t=60"], html); // only the time in a plain <span>
    assert.ok(html.includes("<code>[0:00:10]</code>"));
  });

  test("the text around a link stays escaped; the link's text is escaped too", () => {
    const html = answerMarkdownHtml("a < b at [0:00:10] & c", ONE);
    assert.ok(html.includes(`a &lt; b at <a href="${href(10)}"`), html);
    assert.ok(html.includes("</a> &amp; c"), html);
  });

  test("a title with quotes or markup cannot break out of the tooltip", () => {
    const evil = [{ entityType: "asset", entityId: REC, title: `x" onmouseover="alert(1)<b>`, startSeconds: 0 }];
    const html = answerMarkdownHtml("at 0:10", evil);
    assert.ok(html.includes('title="Play x&quot; onmouseover=&quot;alert(1)&lt;b&gt; from 0:10"'), html);
  });

  test("tables and headings link too", () => {
    const html = answerMarkdownHtml("## At 0:00:10\n\n| When | What |\n|---|---|\n| [0:00:20] | words |", ONE);
    assert.ok(html.includes(`href="${href(10)}"`) && html.includes(`href="${href(20)}"`), html);
  });

  test("without a timed recording it is exactly what marked makes", async () => {
    const { marked } = await import("marked");
    const md = "In **Recording**: [0:00:10] — words\n\n- 1:05 `x`";
    assert.equal(answerMarkdownHtml(md, ONE.slice(1)), marked.parse(md));
    assert.equal(answerMarkdownHtml(md, null), marked.parse(md));
  });
});
