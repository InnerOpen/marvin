import assert from "node:assert/strict";
import { test } from "node:test";
import { UPLOAD_LIMIT_BYTES, uploadTooBig } from "./uploadLimit.ts";

test("a file within the limit is fine, one over it is refused with its size, the limit and what to do", () => {
  assert.equal(uploadTooBig({ name: "rain.mp4", size: UPLOAD_LIMIT_BYTES }), null);
  assert.equal(uploadTooBig({ name: "empty.txt", size: 0 }), null);
  const said = uploadTooBig({ name: "rain.mp4", size: 132_000_000 });
  assert.match(said, /^rain\.mp4 is 132 MB; an upload can carry about 99 MB\./);
  assert.match(said, /smaller/);
});

test("a size just over the limit still reads as whole megabytes", () => {
  assert.match(uploadTooBig({ name: "a.mov", size: UPLOAD_LIMIT_BYTES + 1 }), /is 99 MB;/);
});
