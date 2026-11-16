import assert from "node:assert/strict";
import { test } from "node:test";
import { READER_MAX_BYTES, lineFromHash, readerLines, sizeWords, tooBigToRead } from "./textReader.ts";

const bytes = (s) => new TextEncoder().encode(s);

test("lines are counted as the Fountain check counts them: no BOM, CRLF and CR as breaks, from 1", () => {
  assert.deepEqual(readerLines(bytes("﻿Title: Porch\r\n\r\nINT. PORCH - DUSK\rAction.\n")), ["Title: Porch", "", "INT. PORCH - DUSK", "Action."]);
  assert.deepEqual(readerLines(bytes("one")), ["one"]);
  assert.deepEqual(readerLines(bytes("")), [""]);
  assert.deepEqual(readerLines(bytes("a\n\n")), ["a", ""]);
});

test("a byte that is no UTF-8 reads as a replacement, not an error", () => {
  assert.deepEqual(readerLines(new Uint8Array([0x61, 0xff, 0x0a, 0x62])), ["a�", "b"]);
});

test("an address asks for a line as #L17", () => {
  assert.equal(lineFromHash("#L17"), 17);
  for (const h of ["", "#L0", "#L", "#l17", "#L17x", "#top"]) assert.equal(lineFromHash(h), null, h);
});

test("a file past 1.5 MB is linked, not read", () => {
  assert.equal(tooBigToRead(250_000), null);
  assert.equal(tooBigToRead(READER_MAX_BYTES), null);
  assert.equal(tooBigToRead(null), null);
  assert.equal(tooBigToRead(2_400_000), "This file is 2.4 MB: the reader shows files up to 1.5 MB. Open the file to read it.");
  assert.equal(sizeWords(250_123), "250 KB");
});
