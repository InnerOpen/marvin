// A view's entries as picker cards (viewPicker.ts), and the markup that draws them (ViewPickerCards.astro). Run with `npm test`.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  badgeText,
  countsLine,
  initialsOf,
  lengthText,
  pickerCard,
  refsWanted,
  sampleEvenly,
  stripLimit,
  stripQuery,
  stripsByOwner,
  subtitleOf,
  subtitleParts,
  videoSeconds,
} from "./viewPicker.ts";

const SPINE = { entry_type: "beat", of: "story", order: "number", picture: "still" };
const STUDIO = { picture: "cover", subtitle: ["series", { field: "episode", before: "Ep " }], badges: ["status"], strip: { limit: 16 }, play: "video" };

const image = (id, role, url = `https://cdn/${id}.png`) => ({ id, role, publicUrl: url, mimeType: "image/png" });
const story = (slug, data = {}, assets = []) => ({ id: `id-${slug}`, slug, title: slug.replace(/-/g, " "), dataJson: data, assets });
const beat = (storySlug, number, still) => ({
  id: `b-${storySlug}-${number}`,
  slug: `${storySlug}-b${number}`,
  title: `${storySlug} ${number}`,
  dataJson: { story: storySlug, number, ...(still ? { still } : {}) },
  assets: still ? [image(still, "still")] : [],
});

describe("stripLimit", () => {
  test("off without strip, or without a spine picture to show", () => {
    assert.equal(stripLimit({}, SPINE), 0);
    assert.equal(stripLimit({ strip: false }, SPINE), 0);
    assert.equal(stripLimit({ strip: true }, { ...SPINE, picture: undefined }), 0);
    assert.equal(stripLimit(null, SPINE), 0);
  });
  test("16 by default, the view's own limit, never past 24", () => {
    assert.equal(stripLimit({ strip: true }, SPINE), 16);
    assert.equal(stripLimit({ strip: {} }, SPINE), 16);
    assert.equal(stripLimit({ strip: { limit: 8 } }, SPINE), 8);
    assert.equal(stripLimit({ strip: { limit: 99 } }, SPINE), 24);
  });
});

describe("sampleEvenly", () => {
  const list = Array.from({ length: 40 }, (_, i) => i + 1);
  test("a short list is kept whole", () => {
    assert.deepEqual(sampleEvenly([1, 2, 3], 16), [1, 2, 3]);
    assert.deepEqual(sampleEvenly([], 16), []);
  });
  test("a long one gives n, from the first to the last, in order, none twice", () => {
    const picked = sampleEvenly(list, 16);
    assert.equal(picked.length, 16);
    assert.equal(picked[0], 1);
    assert.equal(picked.at(-1), 40);
    assert.deepEqual([...picked].sort((a, b) => a - b), picked);
    assert.equal(new Set(picked).size, 16);
  });
  test("evenly: the gaps differ by at most one", () => {
    const picked = sampleEvenly(list, 16);
    const gaps = picked.slice(1).map((v, i) => v - picked[i]);
    assert.ok(Math.max(...gaps) - Math.min(...gaps) <= 1, String(gaps));
  });
  test("one is the first; none is nothing", () => {
    assert.deepEqual(sampleEvenly(list, 1), [1]);
    assert.deepEqual(sampleEvenly(list, 0), []);
  });
});

describe("stripQuery", () => {
  test("one query for all the stories' beats, by story then number", () => {
    assert.deepEqual(stripQuery(SPINE, ["a", "b"]), {
      entry_type: "beat",
      where: [{ field: "story", op: "in", value: ["a", "b"] }],
      // biome-ignore lint/suspicious/noThenProperty: the entries query's second sort key is named then
      sort: { by: "story", then: "number" },
    });
  });
  test("a spine with no order sorts by its entry alone", () => {
    assert.deepEqual(stripQuery({ entry_type: "beat", of: "story" }, ["a"]).sort, { by: "story" });
  });
});

describe("stripsByOwner", () => {
  const rows = [beat("a", "01", "s1"), beat("a", "02"), beat("b", "01", "s3"), beat("x", "01")];
  test("each story's beats in the order read, with their count; a story with none has 0; an unlisted owner is dropped", () => {
    const strips = stripsByOwner(rows, "story", ["a", "b", "c"], true);
    assert.deepEqual([...strips.keys()], ["a", "b", "c"]);
    assert.deepEqual(strips.get("a").items.map((r) => r.dataJson.number), ["01", "02"]);
    assert.equal(strips.get("a").count, 2);
    assert.equal(strips.get("b").count, 1);
    assert.equal(strips.get("c").count, 0);
  });
  test("cut short: the last story read and those with none are not counted; the others are exact", () => {
    const strips = stripsByOwner(rows.slice(0, 3), "story", ["a", "b", "c"], false);
    assert.equal(strips.get("a").count, 2);
    assert.equal(strips.get("b").count, null);
    assert.equal(strips.get("c").count, null);
  });
});

describe("the line under the title", () => {
  test("parts as written: a key, or {field, before}", () => {
    assert.deepEqual(subtitleParts(STUDIO.subtitle), [
      { field: "series", before: "" },
      { field: "episode", before: "Ep " },
    ]);
    assert.deepEqual(subtitleParts("premise"), [{ field: "premise", before: "" }]);
    assert.deepEqual(subtitleParts(undefined), []);
  });
  test("a ref field shows the title of the entry it names; the parts that hold something, joined with a dot", () => {
    const titles = new Map([["series", new Map([["night-shift", "Night Shift"]])]]);
    assert.equal(subtitleOf(story("s", { series: "night-shift", episode: 3 }), STUDIO, titles), "Night Shift · Ep 3");
    assert.equal(subtitleOf(story("s", { series: "unknown-one", episode: 2 }), STUDIO, titles), "unknown-one · Ep 2");
    assert.equal(subtitleOf(story("s", { episode: "" }), STUDIO, titles), "");
    assert.equal(subtitleOf(story("s", { series: { odd: 1 } }), STUDIO, titles), "");
  });
  test("refsWanted: the slugs each ref type is asked for, once each", () => {
    const rows = [story("a", { series: "s1" }), story("b", { series: "s1" }), story("c", { series: "s2" }), story("d", {})];
    const wanted = refsWanted(rows, STUDIO, (f) => (f === "series" ? "series" : undefined));
    assert.deepEqual([...wanted], [["series", ["s1", "s2"]]]);
    assert.equal(refsWanted(rows, { subtitle: ["premise"] }, () => undefined).size, 0);
  });
});

describe("words and numbers", () => {
  test("a chip reads a select's value as words", () => {
    assert.equal(badgeText("rough-cut"), "rough cut");
    assert.equal(badgeText("final"), "final");
    assert.equal(badgeText(null), "");
  });
  test("a length is a clock", () => {
    assert.equal(lengthText(87.4), "1:27");
    assert.equal(lengthText(7), "0:07");
    assert.equal(lengthText(59.6), "1:00");
    assert.equal(lengthText(3723), "1:02:03");
    assert.equal(lengthText(0), "");
    assert.equal(lengthText(null), "");
    assert.equal(lengthText(Number.NaN), "");
  });
  test("the counts line: beats, then the render's length; either left out when unknown", () => {
    assert.equal(countsLine(24, "beat", 87.4), "24 beats · 1:27");
    assert.equal(countsLine(1, "beat", null), "1 beat");
    assert.equal(countsLine(0, "beat", null), "0 beats");
    assert.equal(countsLine(null, "beat", 30), "0:30");
    assert.equal(countsLine(null, "beat", null), "");
  });
  test("initials: the first letters of the first two words", () => {
    assert.equal(initialsOf("The Last Onion"), "TL");
    assert.equal(initialsOf("onion"), "O");
    assert.equal(initialsOf("  “quoted” title "), "QT");
    assert.equal(initialsOf(""), "?");
  });
  test("a video's length: a render's seconds, else what an automation or the recorder saved", () => {
    assert.equal(videoSeconds({ seconds: 87.4, quality: "draft" }), 87.4);
    assert.equal(videoSeconds({ duration_seconds: 12 }), 12);
    assert.equal(videoSeconds({ recording: { duration_seconds: 5 } }), 5);
    assert.equal(videoSeconds({}), null);
    assert.equal(videoSeconds(null), null);
  });
});

describe("pickerCard", () => {
  const render = { id: "v1", role: "video", publicUrl: "https://cdn/v1.mp4", mimeType: "video/mp4", metadataJson: { seconds: 87.4, quality: "draft" } };
  const beats = Array.from({ length: 30 }, (_, i) => beat("onion", String(i + 1).padStart(2, "0"), i % 2 ? `st${i}` : null));
  const ctx = (extra = {}) => ({ picker: STUDIO, spine: SPINE, href: "/workspace/views/story-timeline?entry=onion", strip: { items: beats, count: 30 }, ...extra });

  test("a story with a cover, a render and beats: everything on the card", () => {
    const row = story("onion", { cover: "c1", status: "rough-cut", series: "night-shift", episode: 3, video: "v1" }, [image("c1", "cover"), render]);
    const card = pickerCard(row, ctx({ titles: new Map([["series", new Map([["night-shift", "Night Shift"]])]]) }));
    assert.equal(card.picture, "https://cdn/c1.png");
    assert.equal(card.subtitle, "Night Shift · Ep 3");
    assert.deepEqual(card.badges, ["rough cut"]);
    assert.equal(card.counts, "30 beats · 1:27");
    assert.deepEqual(card.video, { url: "https://cdn/v1.mp4", seconds: 87.4 });
    assert.equal(card.strip, true);
    assert.equal(card.thumbs.length, 16);
    assert.equal(card.thumbs[0].title, "Beat 01");
    assert.equal(card.thumbs[0].picture, null); // beat 01 has no still yet: a blank tile
    assert.equal(card.thumbs.at(-1).title, "Beat 30");
    assert.equal(card.thumbs.at(-1).picture, "https://cdn/st29.png");
    assert.equal(card.href, "/workspace/views/story-timeline?entry=onion");
  });
  test("the cover is found by the id its field names, else by its role", () => {
    const byRole = story("onion", {}, [image("zz", "cover")]);
    assert.equal(pickerCard(byRole, ctx()).picture, "https://cdn/zz.png");
  });
  test("no cover: the first beat that has a still", () => {
    const card = pickerCard(story("onion", {}), ctx());
    assert.equal(card.picture, "https://cdn/st1.png");
  });
  test("no cover and no stills: no picture, the initials stand for it", () => {
    const card = pickerCard(story("the-onion", {}), ctx({ strip: { items: [beat("the-onion", "01")], count: 1 } }));
    assert.deepEqual(card.thumbs, [{ title: "Beat 01", picture: null }]);
    assert.equal(card.picture, null);
    assert.equal(card.initials, "TO");
  });
  test("no render: no Play, and the counts have no length; a video that is not one is ignored", () => {
    const card = pickerCard(story("onion", { video: "v2" }, [image("v2", "video")]), ctx());
    assert.equal(card.video, null);
    assert.equal(card.counts, "30 beats");
  });
  test("the beats could not be read: no strip, no count, the rest stays", () => {
    const card = pickerCard(story("onion", { video: "v1" }, [render]), ctx({ strip: null }));
    assert.equal(card.strip, false);
    assert.deepEqual(card.thumbs, []);
    assert.equal(card.counts, "1:27");
    assert.ok(card.video);
  });
  test("a story with no beats yet has an empty strip, so its card lines up with the others", () => {
    const card = pickerCard(story("onion", {}), ctx({ strip: { items: [], count: 0 } }));
    assert.equal(card.strip, true);
    assert.deepEqual(card.thumbs, []);
    assert.equal(card.counts, "0 beats");
  });
  test("a picker without a strip shows none, even when beats are given", () => {
    const card = pickerCard(story("onion", {}), ctx({ picker: { picture: "cover" } }));
    assert.equal(card.strip, false);
    assert.deepEqual(card.thumbs, []);
    assert.equal(card.counts, "");
    assert.equal(card.picture, null);
  });
});

describe("the markup", () => {
  const cards = readFileSync(new URL("../components/ViewPickerCards.astro", import.meta.url), "utf8");
  const page = readFileSync(new URL("../pages/workspace/views/[slug].astro", import.meta.url), "utf8");
  const video = readFileSync(new URL("../components/InlineVideo.astro", import.meta.url), "utf8");

  test("each card is one link; the Play button is outside it, so they are two focus stops and no control sits in a link", () => {
    const link = cards.slice(cards.indexOf('<a class="pc-link"'), cards.indexOf("</a>"));
    assert.ok(link.length > 0);
    assert.doesNotMatch(link, /<button|InlineVideo|PlayButton/);
    assert.match(cards.slice(cards.indexOf("</a>")), /<InlineVideo variant="fill" preload="none"/);
  });
  test("pictures load lazily into boxes that have their size already, so nothing jumps", () => {
    assert.equal((cards.match(/<img /g) ?? []).length, (cards.match(/loading="lazy"/g) ?? []).length);
    assert.match(cards, /\.pc-media \{[^}]*aspect-ratio: 16 \/ 9/);
    assert.match(cards, /\.pc-strip \{[^}]*height: 34px/);
    assert.match(cards, /\.pc-play \{[^}]*aspect-ratio: 16 \/ 9/);
  });
  test("each still says which beat it is; the strip is not read out twice", () => {
    assert.match(cards, /class:list=\{\["pc-thumb"[^>]*title=\{t\.title\}/);
    assert.match(cards, /class="pc-strip" aria-hidden="true"/);
  });
  test("motion is reduced when asked; colours are the theme's", () => {
    assert.match(cards, /@media \(prefers-reduced-motion: reduce\)/);
    assert.doesNotMatch(cards.replace(/rgb\(0 0 0 \/ [0-9.]+\)|#000/g, ""), /#[0-9a-f]{3,6}\b|rgb\(/i);
  });
  test("the video loads nothing until it is played, and never plays by itself", () => {
    assert.match(video, /preload\?: "metadata" \| "none"/);
    assert.match(video, /preload=\{preload\}/);
    assert.doesNotMatch(video + cards, /<video[^>]*autoplay/);
  });
  test("the page draws cards only for a view with `picker`, else the plain list it always had", () => {
    assert.match(page, /if \(spec\.picker\) cards = await pickerCards\(/);
    assert.match(page, /cards \? \(\s*<ViewPickerCards cards=\{cards\} \/>\s*\) : \(\s*<ul class="pick">/);
  });
});
