/**
 * A file field's reader (`preview: "text"`, components/schema-fields/LinkedItemsField.astro): the file's text with its line numbers,
 * read-only, so an uploaded script reads in the form like a pasted one and "line 17" in Check the Fountain's findings can be found.
 */

/** The largest file the reader shows; a bigger one is linked instead (a feature film's Fountain is about a quarter of this). */
export const READER_MAX_BYTES = 1_500_000;

/** The file's lines, counted as the Fountain check counts them: UTF-8 (a bad byte becomes �), no byte order mark, CRLF and CR as plain
 *  line breaks, numbered from 1. A last line break does not make an empty last line. */
export function readerLines(bytes: ArrayBuffer | Uint8Array): string[] {
  const text = new TextDecoder("utf-8").decode(bytes).replace(/^﻿/, "").replace(/\r\n?/g, "\n");
  const lines = text.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/** The line a page address asks for (`#L17`), or null. */
export function lineFromHash(hash: string): number | null {
  const m = /^#L(\d{1,7})$/.exec(hash);
  return m && Number(m[1]) > 0 ? Number(m[1]) : null;
}

/** A size in words: 250 KB, 2.4 MB. */
export function sizeWords(bytes: number): string {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

/** Why a file is not shown in the reader, or null when it is. */
export function tooBigToRead(bytes: number | null | undefined): string | null {
  if (typeof bytes !== "number" || bytes <= READER_MAX_BYTES) return null;
  return `This file is ${sizeWords(bytes)}: the reader shows files up to ${sizeWords(READER_MAX_BYTES)}. Open the file to read it.`;
}
