// A form's submission settings as the entry type page reads them (submissionSettings.ts): either spelling of a setting's name
// shows and saves as one. Run with `npm test` (plain `node --test`). Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { camelSettings } from "./submissionSettings.ts";

describe("camelSettings", () => {
  test("a form stored with underscores reads the way the page's boxes are named", () => {
    const stored = { enable_honeypot: true, honeypot_field: "_website", rate_limit_max: 5, rate_limit_window_seconds: 3600, notify: true };
    assert.deepEqual(camelSettings(stored), {
      enableHoneypot: true,
      honeypotField: "_website",
      rateLimitMax: 5,
      rateLimitWindowSeconds: 3600,
      notify: true,
    });
  });

  test("a form the page saved is left as it is, and a value is never changed (only names are)", () => {
    const stored = { enableCaptcha: true, captchaSecretRef: "{{TURNSTILE_SECRET_KEY}}", honeypotField: "_website", titleTemplate: "From {{ first_name }}" };
    assert.deepEqual(camelSettings(stored), stored);
  });

  test("stored both ways, the page's own spelling wins and there is one copy", () => {
    assert.deepEqual(camelSettings({ enable_captcha: true, enableCaptcha: false }), { enableCaptcha: false });
    assert.deepEqual(camelSettings({ enableCaptcha: false, enable_captcha: true }), { enableCaptcha: false });
  });

  test("nothing stored, or something that is not settings, is no settings", () => {
    for (const nothing of [undefined, null, "x", 3, []]) assert.deepEqual(camelSettings(nothing), {});
  });
});
