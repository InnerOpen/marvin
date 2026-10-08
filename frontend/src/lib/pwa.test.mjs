// The installable app's manifest, colours and browser checks (pwa.ts). Run with `npm test` — plain `node --test`.

import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { existsSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import { appName, buildManifest, installMode, isIos, pushSupport, themeColors, urlBase64ToUint8Array } from "./pwa.ts";

const PUBLIC = fileURLToPath(new URL("../../public", import.meta.url));
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile/15E148 Safari/604.1";
const IPAD_AS_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15";
const ANDROID = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36";

describe("buildManifest", () => {
  test("has what browsers require to install, and every icon exists", () => {
    const m = buildManifest("");
    for (const key of [
      "name",
      "short_name",
      "start_url",
      "scope",
      "display",
      "icons",
      "theme_color",
      "background_color",
    ])
      assert.ok(m[key], key);
    assert.equal(m.name, "Marvin");
    assert.equal(m.display, "standalone");
    assert.equal(m.scope, "/");
    const sizes = m.icons.map((i) => `${i.sizes} ${i.purpose}`);
    assert.deepEqual(sizes, ["192x192 any", "512x512 any", "192x192 maskable", "512x512 maskable"]);
    for (const icon of m.icons) assert.ok(existsSync(`${PUBLIC}${icon.src}`), icon.src);
  });

  test("a share target the worker answers: POST, multipart, images, videos and PDFs plus title/text/url", async () => {
    const { share_target: target } = buildManifest("");
    const { SHARE_TARGET, SHARE_ACCEPT } = await import("../pwa/sw-logic.js");
    assert.equal(target.action, SHARE_TARGET);
    assert.equal(target.method, "POST");
    assert.equal(target.enctype, "multipart/form-data");
    assert.deepEqual([target.params.title, target.params.text, target.params.url], ["title", "text", "url"]);
    assert.deepEqual(target.params.files, [{ name: "files", accept: SHARE_ACCEPT }]);
    assert.ok(existsSync(new URL("../pages/share.astro", import.meta.url)), "the Share page");
    assert.ok(existsSync(new URL("../pages/share-target.ts", import.meta.url)), "the share target's fallback");
  });

  test("shortcuts go to real pages", () => {
    const urls = buildManifest("").shortcuts.map((s) => s.url);
    assert.deepEqual(urls, [
      "/workspace/settings/ai-ask",
      "/workspace/entries/new",
      "/workspace/entries?status=needs_review,approved",
    ]);
  });

  test("a labelled instance installs as itself: name, icons and colour", () => {
    const m = buildManifest("DEV");
    assert.equal(m.name, "Marvin DEV");
    assert.equal(m.short_name, "Marvin DEV");
    assert.ok(m.icons.every((i) => i.src.includes("-dev")));
    for (const icon of m.icons) assert.ok(existsSync(`${PUBLIC}${icon.src}`), icon.src);
    assert.notEqual(m.theme_color, buildManifest("").theme_color);
  });
});

test("appName and themeColors", () => {
  assert.equal(appName(""), "Marvin");
  assert.equal(appName("STAGING"), "Marvin STAGING");
  assert.deepEqual(themeColors(""), { light: "#fafaf9", dark: "#0c0a09" });
  assert.equal(themeColors("DEV").light, themeColors("DEV").dark);
  assert.notEqual(themeColors("DEV").light, themeColors("STAGING").light);
});

describe("install and push checks", () => {
  test("iOS, including iPadOS that reports a Mac with a touch screen", () => {
    assert.ok(isIos(IPHONE));
    assert.ok(isIos(IPAD_AS_MAC, 5));
    assert.ok(!isIos(IPAD_AS_MAC, 0));
    assert.ok(!isIos(ANDROID));
  });

  test("installMode", () => {
    assert.equal(installMode({ standalone: true, hasPrompt: true, userAgent: ANDROID }), "installed");
    assert.equal(installMode({ standalone: false, hasPrompt: true, userAgent: ANDROID }), "prompt");
    assert.equal(installMode({ standalone: false, hasPrompt: false, userAgent: IPHONE }), "ios");
    assert.equal(installMode({ standalone: false, hasPrompt: false, userAgent: ANDROID }), "menu");
  });

  test("pushSupport: iOS needs the installed app; blocked and unsupported say so", () => {
    const base = {
      hasPushManager: true,
      hasServiceWorker: true,
      permission: "default",
      standalone: false,
      userAgent: ANDROID,
    };
    assert.equal(pushSupport(base), "ok");
    assert.equal(pushSupport({ ...base, userAgent: IPHONE }), "ios-install");
    assert.equal(pushSupport({ ...base, userAgent: IPHONE, standalone: true }), "ok");
    assert.equal(pushSupport({ ...base, permission: "denied" }), "denied");
    assert.equal(pushSupport({ ...base, hasPushManager: false }), "unsupported");
  });

  test("urlBase64ToUint8Array decodes a VAPID public key", () => {
    // A fresh P-256 public key, as the backend's vapid script prints it (base64url, no padding).
    const { publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
    const raw = publicKey.export({ format: "der", type: "spki" }).subarray(-65);
    const bytes = urlBase64ToUint8Array(raw.toString("base64url"));
    assert.equal(bytes.length, 65);
    assert.equal(bytes[0], 4); // an uncompressed point
    assert.deepEqual([...bytes], [...raw]);
  });
});
