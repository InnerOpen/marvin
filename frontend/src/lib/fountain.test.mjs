import assert from "node:assert/strict";
import { test } from "node:test";

import { applyFountain, fountainToHtml, inline, parseFountain } from "./fountain.ts";

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

// ── the toolbar's edits ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
const run = (tool, value, start = value.length, end = start) => {
  const edit = applyFountain(tool, value, start, end);
  return { text: edit.value, picked: edit.value.slice(edit.start, edit.end) };
};

test("toolbar: a scene heading starts its own paragraph, with the place to type selected", () => {
  assert.deepEqual(run("scene", ""), { text: "INT. PLACE - DAY\n\n", picked: "PLACE" });
  assert.deepEqual(run("scene", "She waits."), { text: "She waits.\n\nINT. PLACE - DAY\n\n", picked: "PLACE" });
  assert.deepEqual(run("scene", "She waits.\n"), { text: "She waits.\n\nINT. PLACE - DAY\n\n", picked: "PLACE" });
  assert.deepEqual(run("scene", "She waits.\n\n"), { text: "She waits.\n\nINT. PLACE - DAY\n\n", picked: "PLACE" });
});

test("toolbar: selected words become the place, upper-cased, and a heading already written is only upper-cased", () => {
  assert.deepEqual(run("scene", "the cabin", 0, 9), { text: "INT. THE CABIN - DAY\n\n", picked: "THE CABIN" });
  assert.deepEqual(run("scene", "ext. reef - night", 0, 17), { text: "EXT. REEF - NIGHT\n\n", picked: "EXT. REEF - NIGHT" });
});

test("toolbar: a speaker is a name over what is said, the name selected; a selection is what is said", () => {
  assert.deepEqual(run("character", ""), { text: "NAME\nDialogue.\n\n", picked: "NAME" });
  const said = run("character", "Aye, Captain.", 0, 13);
  assert.equal(said.text, "NAME\nAye, Captain.\n\n");
  assert.equal(parseFountain(said.text)[0].kind, "dialogue");
});

test("toolbar: a parenthetical goes on its own line, not its own paragraph, so it stays inside the speech", () => {
  assert.deepEqual(run("parenthetical", "CHET\n"), { text: "CHET\n(delivery)", picked: "delivery" });
  assert.deepEqual(run("parenthetical", "CHET"), { text: "CHET\n(delivery)", picked: "delivery" });
  const speech = run("parenthetical", "CHET\n").text + "\nThe hull groans.";
  assert.deepEqual(parseFountain(speech)[0].lines.map((l) => l.kind), ["parenthetical", "dialogue"]);
});

test("toolbar: a transition is upper-cased with its colon, and the default is CUT TO:", () => {
  assert.deepEqual(run("transition", ""), { text: "CUT TO:\n\n", picked: "CUT" });
  assert.equal(run("transition", "dissolve to", 0, 11).text, "DISSOLVE TO:\n\n");
  assert.equal(parseFountain(run("transition", "").text)[0].kind, "transition");
});

test("toolbar: a centered line is > text < on one line, and many selected lines become one", () => {
  assert.deepEqual(run("centered", ""), { text: "> TEXT <\n\n", picked: "TEXT" });
  assert.equal(run("centered", "THE\nEND", 0, 7).text, "> THE END <\n\n");
  assert.equal(parseFountain(run("centered", "THE END", 0, 7).text)[0].kind, "centered");
});

test("toolbar: a section, a synopsis, lyrics and a page break are each read back as what they are", () => {
  assert.equal(parseFountain(run("section", "").text)[0].kind, "section");
  assert.equal(parseFountain(run("synopsis", "").text)[0].kind, "synopsis");
  assert.equal(run("lyrics", "").text, "~A line of the song\n\n");
  assert.equal(parseFountain(run("break", "Before.").text)[1].kind, "break");
});

test("toolbar: a note, bold, italic and underline wrap the selection where it stands, or a placeholder", () => {
  assert.deepEqual(run("note", "A line.", 2, 6), { text: "A [[line]].", picked: "line" });
  assert.deepEqual(run("bold", "go", 0, 2), { text: "**go**", picked: "go" });
  assert.deepEqual(run("italic", ""), { text: "*italic*", picked: "italic" });
  assert.deepEqual(run("underline", "x ", 2), { text: "x _underlined_", picked: "underlined" });
  assert.equal(inline("**go** *x* _y_ [[n]]").includes("<b>go</b>"), true);
});

test("toolbar: an edit in the middle of the text keeps what comes after on its own paragraph", () => {
  const edit = applyFountain("scene", "One.\n\nTwo.", 6, 6);
  assert.equal(edit.value, "One.\n\nINT. PLACE - DAY\n\nTwo.");
  assert.equal(edit.value.slice(edit.start, edit.end), "PLACE");
});

test("toolbar: a selection backwards or past the end is taken as it is", () => {
  assert.equal(applyFountain("bold", "abc", 3, 0).value, "**abc**");
  assert.equal(applyFountain("note", "abc", 99, 99).value, "abc[[note]]");
});
