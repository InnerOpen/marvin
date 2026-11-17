import assert from "node:assert/strict";
import { test } from "node:test";
import { BACK_PARAM, isSetupLink, nextLines, backStep, backValue, carriedCtx, choicesOnly, nextStep, parseBack, readCtx, seeAlsoHref, seeAlsoOf, shownLines, stepHref, withBack, withoutFrom } from "./wizard.ts";

const narrate = {
  title: "Narrate a story",
  steps: [
    { id: "world", kind: "choose", title: "World", as: "world", entry_type: "world" },
    { id: "story", kind: "choose", title: "Story", as: "story", entry_type: "story" },
    { id: "details", kind: "form", title: "Story details", entry: "story", fields: ["title"] },
    { id: "sounds", kind: "list", title: "Sounds: are these read right?", entry_type: "sound", parent: "story", parent_field: "story" },
  ],
};

const params = (href) => new URL(href, "http://x").searchParams;

test("a see_also link opens the other setup on its step, with the carried choices and the way back here", () => {
  const item = { label: "Make music", setup: "sounds-for-a-story", step: "music", carry: { story: "story", world: "story.world", gone: "nothing" } };
  const ctx = { world: "w1", story: "tin-soldier" };
  const carried = carriedCtx(item.carry, ctx, { story: { dataJson: { world: "w1" } } });
  assert.deepEqual(carried, { story: "tin-soldier", world: "w1" });
  const back = backValue("narrate-a-story", ctx, "sounds");
  assert.equal(back, "/workspace/setups/narrate-a-story?step=sounds&world=w1&story=tin-soldier");
  const href = seeAlsoHref(item, carried, back);
  assert.ok(href.startsWith("/workspace/setups/sounds-for-a-story?step=music&"));
  const p = params(href);
  assert.equal(p.get("story"), "tin-soldier");
  assert.equal(p.get(BACK_PARAM), back);
  // The other setup does not read the marker as a choice.
  assert.deepEqual(readCtx(p), { story: "tin-soldier", world: "w1" });
});

test("the way back leaves out a list of picks and any marker of its own: one way back, never a chain", () => {
  const ctx = { story: "s", picks: "a,b,c", [BACK_PARAM]: "/workspace/setups/other?step=x" };
  assert.equal(backValue("lines", ctx, "takes", new Set(["picks"])), "/workspace/setups/lines?step=takes&story=s");
});

test("the way back rides along on every step of the setup it opened, and survives going round again", () => {
  const back = "/workspace/setups/narrate-a-story?step=sounds&world=w1&story=tin-soldier";
  const ctx = withBack({ story: "tin-soldier" }, params(`/workspace/setups/sounds?story=tin-soldier&back=${encodeURIComponent(back)}`));
  assert.equal(ctx[BACK_PARAM], back);
  const next = stepHref("sounds-for-a-story", ctx, "check");
  assert.equal(parseBack(params(next).get(BACK_PARAM))?.href, back);
  assert.equal(withoutFrom(narrate, ctx, "story")[BACK_PARAM], back);
  assert.deepEqual(choicesOnly(ctx), { story: "tin-soldier" });
  assert.equal(nextStep(narrate, ctx, "story")?.id, "details"); // the marker is no choice: it opens no step
});

test("the way back is rebuilt from a setup, a step and choices: nothing else gets through", () => {
  const ok = parseBack("/workspace/setups/narrate-a-story?step=sounds&world=w1&story=tin-soldier&notice=saved&run=x&back=%2Fworkspace%2Fsetups%2Fa");
  assert.deepEqual(ok, {
    setup: "narrate-a-story",
    step: "sounds",
    ctx: { world: "w1", story: "tin-soldier" },
    href: "/workspace/setups/narrate-a-story?step=sounds&world=w1&story=tin-soldier",
  });
  for (const bad of [
    "//evil.example/workspace/setups/x",
    "/\\evil.example/workspace/setups/x",
    "https://evil.example/workspace/setups/x",
    "javascript:alert(1)",
    "/workspace/setups/../admin",
    "/workspace/setups/%2e%2e/admin",
    "/workspace/setups/Narrate",
    "/workspace/setups/a/b",
    "/workspace/entries/123",
    "/workspace/setups/x?step=a b",
    `/workspace/setups/x?story=${"a".repeat(1600)}`,
    "",
    null,
    undefined,
  ]) assert.equal(parseBack(bad), null, String(bad));
  // A step id that is not one is dropped; the setup still opens.
  assert.equal(parseBack("/workspace/setups/x?step=%3Cscript%3E&story=s")?.href, "/workspace/setups/x?story=s");
  // A bad marker is not carried.
  assert.deepEqual(withBack({ story: "s" }, params("/x?back=https%3A%2F%2Fevil.example")), { story: "s" });
});

test("the banner counts the step as the person saw it there", () => {
  const back = parseBack("/workspace/setups/narrate-a-story?step=sounds&world=w1&story=s");
  assert.deepEqual(backStep(narrate, back), { number: 4, title: "Sounds: are these read right?" });
  assert.equal(backStep(narrate, parseBack("/workspace/setups/narrate-a-story?step=gone")), null);
});

test("see_also as the page draws it: malformed ones left out, at most three", () => {
  const step = { id: "s", kind: "list", title: "S", see_also: [{ label: "A", setup: "a" }, { label: "", setup: "b" }, { label: "C", setup: "Bad Slug" }, { label: "D", setup: "d" }, { label: "E", setup: "e" }, { label: "F", setup: "f" }] };
  assert.deepEqual(seeAlsoOf(step).map((s) => s.setup), ["a", "d", "e"]);
  assert.deepEqual(seeAlsoOf({ id: "x", kind: "form", title: "X" }), []);
  // A carry key the page uses itself is never set.
  assert.deepEqual(carriedCtx({ step: "story", back: "story", story: "story" }, { story: "s" }, {}), { story: "s" });
});

test("a show card states an empty field when the step says what empty means", () => {
  const schema = { fields: [{ key: "import_part", label: "Chapters to bring in" }, { key: "title", label: "Title" }] };
  assert.deepEqual(shownLines({ import_part: "" }, schema, ["import_part", "title"]), []);
  assert.deepEqual(shownLines({ import_part: " " }, schema, ["import_part", "title"], { import_part: "All the chapters" }), [{ key: "import_part", label: "Chapters to bring in", value: "All the chapters" }]);
  assert.deepEqual(shownLines({ import_part: "2-4" }, schema, ["import_part"], { import_part: "All the chapters" })[0].value, "2-4");
  assert.deepEqual(shownLines({}, schema, ["import_part", "title"], "Not set").map((l) => l.value), ["Not set", "Not set"]);
});

test("an empty step's link to another setup carries the choices and the way back, as see_also does", async () => {
  const { emptyLinks } = await import("./wizardEmpty.ts");
  const lines = {
    title: "Lines of a beat",
    steps: [
      { id: "story", kind: "choose", title: "Story", as: "story", entry_type: "story" },
      { id: "beat", kind: "choose", title: "Beat", as: "beat", entry_type: "beat", scope: { story: "${story}" },
        empty_next: { text: "Bring the Fountain in: Narrate a story", setup: "narrate-a-story", step: "details", carry: { story: "story", world: "story.world" } } },
    ],
  };
  const [link] = emptyLinks(lines, { story: "tin" }, lines.steps[1], "lines-in-a-beat", [], { story: { dataJson: { world: "w1" } } });
  assert.equal(link.label, "Bring the Fountain in: Narrate a story");
  const p = params(link.href);
  assert.ok(link.href.startsWith("/workspace/setups/narrate-a-story?step=details&"));
  assert.deepEqual(readCtx(p), { story: "tin", world: "w1" });
  assert.equal(parseBack(p.get(BACK_PARAM))?.href, "/workspace/setups/lines-in-a-beat?step=beat&story=tin");
  // The old forms are as they were: an earlier step, a plain path.
  const old = { ...lines, steps: [lines.steps[0], { ...lines.steps[1], empty_next: { text: "Open call", href: "/workspace/setups/open-call" } }] };
  assert.deepEqual(emptyLinks(old, {}, old.steps[1], "x"), [{ label: "Open call", href: "/workspace/setups/open-call" }]);
  const back = { ...lines, steps: [lines.steps[0], { ...lines.steps[1], empty_next: { step: "story" } }] };
  assert.equal(emptyLinks(back, { story: "tin" }, back.steps[1], "x")[0].href, "/workspace/setups/x?step=story&story=tin");
});

test("a setup's next lines: a plain one as it is, one to another setup with the choices and the way back to this end", () => {
  const def = {
    title: "Narrate",
    steps: narrate.steps,
    next: [{ text: "Read the beats." }, { text: "Workflows", href: "/automation/workflows" }, { text: "Cast the actors", setup: "casting-call", step: "roles", carry: { world: "world", story: "story" } }],
  };
  const out = nextLines(def, { slug: "narrate-a-story", step: "sounds", ctx: { world: "w1", story: "s", [BACK_PARAM]: "/workspace/setups/a" } });
  assert.deepEqual(out.slice(0, 2), [{ text: "Read the beats.", href: undefined }, { text: "Workflows", href: "/automation/workflows" }]);
  const p = params(out[2].href);
  assert.equal(new URL(out[2].href, "http://x").pathname, "/workspace/setups/casting-call");
  assert.deepEqual(readCtx(p), { world: "w1", story: "s" });
  assert.equal(p.get(BACK_PARAM), "/workspace/setups/narrate-a-story?step=sounds&world=w1&story=s"); // never a chain
  assert.equal(isSetupLink({ text: "x", setup: "Bad Slug" }), false);
  assert.equal(isSetupLink({ text: " ", setup: "ok" }), false);
});
