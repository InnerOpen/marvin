// Media embeds — the pure helpers (mediaEmbeds.ts). Run with `npm test` — plain `node --test`, which
// strips the .ts types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  buildIframeSpec,
  findEmbedCandidates,
  findProvider,
  hostMatches,
  insertEmbedParagraph,
  linkCardText,
  providerAllowed,
  renderMarkdownPreview,
  safeHref,
} from "./mediaEmbeds.ts";

const providers = [
  {
    key: "youtube",
    name: "YouTube",
    kinds: ["video", "playlist"],
    hosts: ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"],
    examples: [],
    linkOnly: false,
  },
  {
    key: "bandcamp",
    name: "Bandcamp",
    kinds: ["audio"],
    hosts: ["*.bandcamp.com"],
    examples: [],
    linkOnly: false,
  },
];
const frameSources = ["https://www.youtube-nocookie.com", "https://bandcamp.com/"];

const okEmbed = {
  url: "https://youtu.be/abc",
  canonicalUrl: "https://www.youtube.com/watch?v=abc",
  provider: "youtube",
  providerName: "YouTube",
  kind: "video",
  status: "ok",
  title: "A talk",
  iframe: {
    src: "https://www.youtube-nocookie.com/embed/abc",
    title: "A talk",
    allow: "encrypted-media; picture-in-picture",
    sandbox: "allow-scripts allow-same-origin allow-popups",
    referrerpolicy: "strict-origin-when-cross-origin",
    aspectRatio: "16/9",
  },
  link: { href: "https://www.youtube.com/watch?v=abc", title: "A talk", providerName: "YouTube" },
  html: "<div>ignored</div>",
};

describe("host matching", () => {
  test("exact hosts and *. subdomains match", () => {
    assert.equal(findProvider("https://www.youtube.com/watch?v=x", providers)?.key, "youtube");
    assert.equal(findProvider("https://YOUTU.BE/x", providers)?.key, "youtube");
    assert.equal(findProvider("https://artist.bandcamp.com/album/y", providers)?.key, "bandcamp");
    assert.equal(hostMatches("a.b.bandcamp.com", "*.bandcamp.com"), true);
  });

  test("look-alike hosts are rejected", () => {
    for (const url of [
      "https://youtube.com.evil.example/watch?v=x",
      "https://notyoutube.com/watch?v=x",
      "https://evilbandcamp.com/album/y",
      "https://bandcamp.com.evil.example/",
      "https://youtube.com@evil.example/",
    ]) {
      assert.equal(findProvider(url, providers), null, url);
    }
    // "*." means a subdomain, not the bare domain.
    assert.equal(hostMatches("bandcamp.com", "*.bandcamp.com"), false);
  });

  test("non-http URLs never match", () => {
    assert.equal(findProvider("javascript://youtube.com/%0aalert(1)", providers), null);
    assert.equal(findProvider("ftp://youtube.com/x", providers), null);
    assert.equal(findProvider("not a url", providers), null);
  });
});

describe("bare-URL embed candidates", () => {
  test("a URL alone in its paragraph is a candidate, keyed as written", () => {
    const md = "Intro.\n\nhttps://www.youtube.com/watch?v=abc&t=1\n\nOutro.";
    assert.deepEqual(findEmbedCandidates(md), ["https://www.youtube.com/watch?v=abc&t=1"]);
  });

  test("<url> and [text](url) stay links", () => {
    assert.deepEqual(findEmbedCandidates("<https://youtu.be/abc>"), []);
    assert.deepEqual(findEmbedCandidates("[watch](https://youtu.be/abc)"), []);
    assert.deepEqual(findEmbedCandidates("[https://youtu.be/abc](https://youtu.be/abc)"), []);
  });

  test("URLs in a sentence, with trailing punctuation, in lists, quotes or code are not candidates", () => {
    assert.deepEqual(findEmbedCandidates("Watch https://youtu.be/abc now"), []);
    assert.deepEqual(findEmbedCandidates("https://youtu.be/abc."), []);
    assert.deepEqual(findEmbedCandidates("- https://youtu.be/abc"), []);
    assert.deepEqual(findEmbedCandidates("> https://youtu.be/abc"), []);
    assert.deepEqual(findEmbedCandidates("    https://youtu.be/abc"), []);
    assert.deepEqual(findEmbedCandidates("```\nhttps://youtu.be/abc\n```"), []);
    assert.deepEqual(findEmbedCandidates("https://youtu.be/abc\nand more"), []);
  });
});

describe("preview renderer", () => {
  test("bare URL paragraphs become placeholder slots; other markdown renders", () => {
    const { html, slots } = renderMarkdownPreview("# Hi\n\nhttps://youtu.be/abc\n\nText", { nonce: "n" });
    assert.deepEqual(slots, [{ id: "n-0", url: "https://youtu.be/abc" }]);
    assert.match(html, /<h1>Hi<\/h1>/);
    assert.match(html, /<div data-marvin-embed-slot="n-0"><\/div>/);
    assert.doesNotMatch(html, /<a href="https:\/\/youtu.be\/abc">/);
  });

  test("autoEmbed: false keeps the bare URL a plain link", () => {
    const { html, slots } = renderMarkdownPreview("https://youtu.be/abc", { autoEmbed: false });
    assert.deepEqual(slots, []);
    assert.match(html, /<a href="https:\/\/youtu.be\/abc">/);
  });

  test("javascript: and data: links are stripped", () => {
    const { html } = renderMarkdownPreview(
      "[a](javascript:alert(1)) [b](JaVaScRiPt:alert(1)) [c](data:text/html,x) ![i](javascript:x)",
    );
    assert.doesNotMatch(html, /javascript:/i);
    assert.doesNotMatch(html, /data:text/i);
  });

  test("safeHref keeps http(s), mailto and relative URLs", () => {
    assert.equal(safeHref("https://example.com/a"), "https://example.com/a");
    assert.equal(safeHref("mailto:a@example.com"), "mailto:a@example.com");
    assert.equal(safeHref("/about"), "/about");
    assert.equal(safeHref("#top"), "#top");
    assert.equal(safeHref("page.html"), "page.html");
    assert.equal(safeHref("java\tscript:alert(1)"), "");
    assert.equal(safeHref(" vbscript:x"), "");
  });
});

describe("iframe builder", () => {
  test("builds attributes from embed.iframe for an allowed frame source", () => {
    const spec = buildIframeSpec(okEmbed, frameSources);
    assert.ok(spec);
    assert.equal(spec.attrs.src, "https://www.youtube-nocookie.com/embed/abc");
    assert.equal(spec.attrs.loading, "lazy");
    assert.equal(spec.attrs.allowfullscreen, "");
    assert.equal(spec.attrs.sandbox, "allow-scripts allow-same-origin allow-popups");
    assert.equal(spec.aspectRatio, "16/9");
  });

  test("refuses a src whose host isn't an allowed frame source", () => {
    for (const src of [
      "https://evil.example/embed/abc",
      "https://www.youtube-nocookie.com.evil.example/embed/abc",
      "http://www.youtube-nocookie.com/embed/abc",
      "javascript:alert(1)",
    ]) {
      assert.equal(buildIframeSpec({ ...okEmbed, iframe: { ...okEmbed.iframe, src } }, frameSources), null, src);
    }
  });

  test("no player unless status is ok; audio gets no allowfullscreen and keeps its height", () => {
    assert.equal(buildIframeSpec({ ...okEmbed, status: "link" }, frameSources), null);
    const audio = {
      ...okEmbed,
      kind: "audio",
      iframe: {
        ...okEmbed.iframe,
        src: "https://bandcamp.com/EmbeddedPlayer/album=1",
        aspectRatio: undefined,
        height: 120,
      },
    };
    const spec = buildIframeSpec(audio, frameSources);
    assert.ok(spec);
    assert.equal("allowfullscreen" in spec.attrs, false);
    assert.equal(spec.height, 120);
    assert.equal(spec.aspectRatio, undefined);
  });

  test("link card text", () => {
    assert.equal(linkCardText({ ...okEmbed, status: "unavailable" }), "A talk · on YouTube");
  });
});

describe("inserting an embed URL", () => {
  test("adds blank lines around the URL as needed", () => {
    assert.deepEqual(insertEmbedParagraph("", 0, 0, "U"), { value: "U", caret: 1 });
    assert.deepEqual(insertEmbedParagraph("Hello", 5, 5, "U"), { value: "Hello\n\nU", caret: 8 });
    assert.deepEqual(insertEmbedParagraph("A\n\nB", 3, 3, "U"), { value: "A\n\nU\n\nB", caret: 4 });
    assert.deepEqual(insertEmbedParagraph("AB", 1, 1, "U"), { value: "A\n\nU\n\nB", caret: 4 });
    assert.deepEqual(insertEmbedParagraph("A x B", 2, 3, "U"), { value: "A\n\nU\n\nB", caret: 4 });
  });

  test("the inserted URL is an embed candidate", () => {
    const { value } = insertEmbedParagraph("Para one.", 4, 4, "https://youtu.be/abc");
    assert.deepEqual(findEmbedCandidates(value), ["https://youtu.be/abc"]);
  });
});

describe("providers filter", () => {
  test("empty or absent allows all", () => {
    assert.equal(providerAllowed("youtube", undefined), true);
    assert.equal(providerAllowed("youtube", []), true);
    assert.equal(providerAllowed("youtube", ["vimeo"]), false);
    assert.equal(providerAllowed("vimeo", ["vimeo"]), true);
  });
});
