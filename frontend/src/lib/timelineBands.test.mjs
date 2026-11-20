import assert from "node:assert/strict";
import { test } from "node:test";
import { layout } from "./timeline.ts";
import { assignWords, bandChoices, bandItemKeys, bandRunWords } from "./timelineBands.ts";

const row = (slug, data, extra = {}) => ({ id: `id-${slug}`, slug, title: slug, dataJson: data, ...extra });

const spec = {
  kind: "timeline",
  title: "Timeline",
  entry_type: "story",
  spine: {
    entry_type: "beat",
    of: "story",
    order: "number",
    seconds: { hold: "hold_seconds", defaults: { hold: 4 } },
    run: { workflow: "render", entry: "story", item: "beats", field: "number", label: "Draft" },
    bands: [{ entry_type: "band", field: "band", title: "Band", run: true, assign: true }],
    cards: { intro: { title: "intro_title", seconds: "intro_seconds", default_seconds: 2 } },
  },
  lanes: [],
};

/** Five beats, numbered 1 to 5, with these bands: the layout the page draws and the band buttons read. */
const laid = (bands) =>
  layout(spec, {
    entry: row("s", { intro_title: "A title" }),
    spine: bands.map((band, i) => row(`b${i + 1}`, { story: "s", number: i + 1, band })),
    lanes: {},
    bands: { band: [row("opening", {}, { title: "The opening" }), row("storm", {}, { title: "Storm" })] },
  });

test("a band's run drafts every item that holds it, across the gaps between its strips, in timeline order", () => {
  const { items, bands } = laid(["opening", "", "opening", "storm", "storm"]);
  assert.equal(bands.band.filter((b) => b.slug === "opening").length, 2); // two strips with a gap
  assert.deepEqual(bandItemKeys(items, bands.band, "opening"), ["1", "3"]);
  assert.deepEqual(bandItemKeys(items, bands.band, "storm"), ["4", "5"]);
  assert.deepEqual(bandItemKeys(items, bands.band, "gone"), []);
});

test("the title card and an item with no run value are left out of a band's draft", () => {
  const { items, bands } = laid(["opening", "opening"]);
  assert.ok(items.some((i) => i.card)); // the intro card is laid out before the beats
  const unnumbered = items.map((i) => (i.id === "id-b2" ? { ...i, key: "" } : i));
  assert.deepEqual(bandItemKeys(unnumbered, bands.band, "opening"), ["1"]);
});

test("the run button says what it will draft", () => {
  assert.equal(bandRunWords("Draft", "beat", 2, "Test Band"), "Draft the 2 beats of Test Band");
  assert.equal(bandRunWords("Draft", "beat", 1, "Test Band"), "Draft the beat of Test Band");
});

const options = [
  { slug: "calm", title: "Calm", match: { story: "s" } },
  { slug: "other", title: "Other story's", match: { story: "t" } },
  { slug: "shared", title: "Shared", match: {} },
];

test("the bands offered are the ones the entry form offers each selected item: its ref_match against the item's own fields", () => {
  assert.deepEqual(
    bandChoices(options, { story: "story" }, [{ story: "s" }, { story: "s" }]).map((o) => o.slug),
    ["calm"],
  );
  // items of two stories share no band
  assert.deepEqual(bandChoices(options, { story: "story" }, [{ story: "s" }, { story: "t" }]), []);
  // with no ref_match, or nothing to match on yet, every band of the type is offered, as in the form
  assert.deepEqual(
    bandChoices(options, {}, [{ story: "s" }]).map((o) => o.slug),
    ["calm", "other", "shared"],
  );
  assert.deepEqual(
    bandChoices(options, { story: "story" }, [{}]).map((o) => o.slug),
    ["calm", "other", "shared"],
  );
});

test("writing a band says what changed, and names each item not changed with why", () => {
  assert.equal(assignWords("Band", "Storm", "beat", [{ key: "2" }, { key: "4" }]), "Band set to Storm on beats 2, 4.");
  assert.equal(assignWords("Band", null, "beat", [{ key: "2" }]), "Band cleared on beat 2.");
  assert.equal(
    assignWords("Band", "Storm", "beat", [{ key: "2" }, { key: "4", problem: "you may not edit it" }]),
    "Band set to Storm on beat 2. Not changed: beat 4 (you may not edit it).",
  );
  assert.equal(
    assignWords("Band", "Storm", "beat", [{ key: "4", problem: "403" }]),
    "Band not changed. Not changed: beat 4 (403).",
  );
});
