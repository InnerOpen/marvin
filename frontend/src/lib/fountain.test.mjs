import assert from "node:assert/strict";
import { test } from "node:test";

import { fountainToHtml, inline, parseFountain } from "./fountain.ts";

const kinds = (text) => parseFountain(text).map((b) => b.kind);

test("a title page is the key: value lines at the top, with indented lines continuing a value", () => {
  const [page] = parseFountain("Title: THE DEVIL'S SHOALS\nCredit: Written by\nContact:\n    Agent: Blackbeard\n    info@example.com\n\nINT. CABIN - NIGHT");
  assert.equal(page.kind, "title");
  assert.deepEqual(page.pairs, [
    { key: "Title", value: "THE DEVIL'S SHOALS" },
    { key: "Credit", value: "Written by" },
    { key: "Contact", value: "Agent: Blackbeard\ninfo@example.com" },
  ]);
});

test("a first line that merely has a colon in it is action, not a title page", () => {
  assert.deepEqual(kinds("Note: the captain is late.\nShe waits.\n\nINT. CABIN - NIGHT"), ["action", "scene"]);
});

test("a scene heading starts with INT, EXT or INT./EXT, or a leading dot, and keeps its number apart", () => {
  const blocks = parseFountain("INT. CAPTAIN'S CABIN - NIGHT #2#\n\nEXT. THE REEF - DAWN\n\n.UNDERWATER - CONTINUOUS\n\nINTERESTING times.");
  assert.deepEqual(blocks.map((b) => [b.kind, b.text, b.number]), [
    ["scene", "INT. CAPTAIN'S CABIN - NIGHT", "2"],
    ["scene", "EXT. THE REEF - DAWN", ""],
    ["scene", "UNDERWATER - CONTINUOUS", ""],
    ["action", "INTERESTING times.", undefined],
  ]);
});

test("a heading with its synopsis line under it, and no blank between, is both", () => {
  assert.deepEqual(kinds("INT. CABIN - NIGHT #1#\n= Valerie refuses to back down.\n\nThe lantern swings."), ["scene", "synopsis", "action"]);
});

test("a speaker in capitals followed by lines is dialogue, with the extension and the delivery kept apart", () => {
  const [d] = parseFountain("CHET (O.S.)\n(shouting over the storm)\nThe hull is groaning, Captain!");
  assert.equal(d.kind, "dialogue");
  assert.equal(d.character, "CHET");
  assert.equal(d.extension, "(O.S.)");
  assert.deepEqual(d.lines, [
    { kind: "parenthetical", text: "(shouting over the storm)" },
    { kind: "dialogue", text: "The hull is groaning, Captain!" },
  ]);
});

test("a speaker in lower case is action, and a capitals line alone is not a speaker", () => {
  assert.deepEqual(kinds("chet\nThe hull is groaning."), ["action"]);
  assert.deepEqual(kinds("A DEAFENING CRUNCH"), ["action"]);
});

test("a capitals line above action is read as a speaker, which is what shows the slip", () => {
  assert.deepEqual(kinds("THE PLAGUE OF THE SEA RISES.\nLightning splits the sky."), ["dialogue"]);
  assert.deepEqual(kinds("!THE PLAGUE OF THE SEA RISES.\nLightning splits the sky."), ["action"]);
});

test("a transition ends in TO: in capitals, or starts with >, and stands alone", () => {
  assert.deepEqual(kinds("CUT TO:\n\nDISSOLVE TO:\n\n> FADE OUT.\n\nCUT TO: the street"), ["transition", "transition", "transition", "action"]);
  assert.deepEqual(kinds("> THE END <"), ["centered"]);
});

test("sections, synopses and page breaks are their own elements", () => {
  const blocks = parseFountain("# ACT I: THE WRECK\n\n## SCENE 2\n\n===\n\n= a note to self");
  assert.deepEqual(
    blocks.map((b) => b.kind),
    ["section", "section", "break", "synopsis"],
  );
  assert.deepEqual([blocks[0].depth, blocks[0].text, blocks[1].depth], [1, "ACT I: THE WRECK", 2]);
  assert.equal(blocks[3].text, "a note to self");
});

test("a boneyard is dropped and a note-only paragraph is a note", () => {
  assert.deepEqual(kinds("INT. CABIN - DAY\n\n/* cut this\n\nand this */\n\n[[Beat 1003. Hold: 1s.]]\n\nShe waits."), ["scene", "note", "action"]);
});

test("emphasis, underline and notes are read; everything else is escaped", () => {
  assert.equal(inline("a *soft* and **loud** and ***both*** and _under_"), "a <i>soft</i> and <b>loud</b> and <b><i>both</i></b> and <u>under</u>");
  assert.equal(inline("5 * 3 and \\*plain\\*"), "5 * 3 and *plain*");
  assert.equal(inline("go [[Sound: thunder at 0.4s.]] now"), 'go <span class="ft-note">Sound: thunder at 0.4s.</span> now');
  assert.equal(inline("<script>alert(1)</script> & \"quotes\""), "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;quotes&quot;");
});

test("the page is escaped end to end, so text cannot add markup", () => {
  const html = fountainToHtml("Title: <img src=x onerror=alert(1)>\n\nINT. <b>CABIN</b> - NIGHT\n\n<i>NAME\n<script>x</script>");
  for (const markup of ["<img", "<script", "<b>CABIN"]) assert.ok(!html.includes(markup), `${markup} must not appear`);
  assert.match(html, /ft-scene/);
});

test("nothing to read gives nothing to show", () => {
  assert.equal(fountainToHtml(""), "");
  assert.equal(fountainToHtml("  \n\n  "), "");
  assert.deepEqual(parseFountain(undefined), []);
});

test("the story's own file reads as it is meant to: heading, speaker, delivery, line, transition", () => {
  const text = "Title: THE DEVIL'S SHOALS\nAuthor: Jared\n\n# ACT I: THE WRECK\n\nEXT. THE REEF - NIGHT #1#\n= Black rocks break the surface.\n\nLightning reveals the ship.\n\n[[Sound: timber grinding at 0s.]]\n\nCHET (O.S.)\n(shouting)\nThe hull is groaning, Captain!\n\nCUT TO:\n\nINT. CAPTAIN'S CABIN - CONTINUOUS #2#\n";
  assert.deepEqual(kinds(text), ["title", "section", "scene", "synopsis", "action", "note", "dialogue", "transition", "scene"]);
});
