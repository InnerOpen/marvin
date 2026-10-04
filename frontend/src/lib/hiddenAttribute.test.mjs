// The `hidden` attribute is only a UA `display: none`, so any class rule that sets `display` shows the
// element anyway (the Ask page's empty attachment chip with its stray "×"). For the pages below, every
// element rendered `hidden` whose class sets `display` must also have a `.class[hidden]` rule.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

const SRC = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, SRC), "utf8");
const GLOBAL_CSS = read("styles/global.css");
const PAGES = ["pages/workspace/settings/ai-ask.astro", "components/Marvin.astro"];

/** Classes that a rule of their own (`.name { … display: x }`, x not none) gives a display. */
function displayClasses(css) {
  const out = new Set();
  for (const [, selectors, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!/(^|;|\s)display:\s*(?!none)/.test(body)) continue;
    for (const sel of selectors.split(",")) {
      const m = sel.trim().match(/^\.([\w-]+)$/);
      if (m) out.add(m[1]);
    }
  }
  return out;
}

/** Class lists of the elements the markup renders with a bare `hidden` attribute. */
function hiddenElementClasses(markup) {
  return [...markup.matchAll(/<\w+\b[^>]*?\sclass="([^"]+)"[^>]*?\shidden(?=[\s/>])[^>]*>/g)].map((m) =>
    m[1].split(/\s+/),
  );
}

describe("hidden elements stay hidden", () => {
  for (const page of PAGES) {
    test(page, () => {
      const source = read(page);
      const css = `${GLOBAL_CSS}\n${source}`;
      const shown = displayClasses(css);
      const missing = hiddenElementClasses(source)
        .flat()
        .filter((cls) => shown.has(cls) && !css.includes(`.${cls}[hidden]`));
      assert.deepEqual([...new Set(missing)], []);
    });
  }
});
