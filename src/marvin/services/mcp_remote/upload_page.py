"""The photo upload page an MCP assistant's upload link opens (`/mcp/upload#<secret>`).

One self-contained page, served by the API host so it needs no sign-in (a chat's in-app browser has none). The secret
is in the URL fragment: the script reads it, removes it from the address bar, checks the link (`POST /mcp/upload/check`)
and sends the chosen file with it (`POST /mcp/upload`). The server sees it only in those request bodies. The script
and style carry a per-response nonce under a CSP that allows nothing else (no framing, no other origins).
"""

from __future__ import annotations

# ruff: noqa: E501 — a page's CSS and script, not Python

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="referrer" content="no-referrer">
<title>Add a photo to Marvin</title>
<style nonce="__NONCE__">
  :root { color-scheme: light dark; --bg: #f4f6f8; --panel: #fff; --ink: #1f2933; --muted: #62707d; --line: #d5dbe1; --accent: #2457c5; --on-accent: #fff; --ok: #1a7f4b; --bad: #c0392b; }
  @media (prefers-color-scheme: dark) { :root { --bg: #14181c; --panel: #1d2329; --ink: #e8ecef; --muted: #9aa7b2; --line: #36414b; --accent: #7aa2f7; --on-accent: #10161c; --ok: #5fcf8f; --bad: #ff8a7a; } }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { width: 100%; max-width: 440px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 24px 20px; }
  h1 { margin: 0 0 6px; font-size: 22px; line-height: 1.25; }
  p { margin: 0 0 14px; }
  .muted { color: var(--muted); font-size: 14px; }
  .pick { display: block; width: 100%; padding: 28px 12px; border: 2px dashed var(--line); border-radius: 10px; text-align: center; cursor: pointer; color: var(--accent); font-weight: 600; }
  .pick:focus-within, .pick:hover { border-color: var(--accent); }
  .pick input { position: absolute; width: 1px; height: 1px; opacity: 0; }
  img.preview { display: block; width: 100%; max-height: 280px; object-fit: contain; margin: 14px 0 0; border-radius: 8px; border: 1px solid var(--line); background: var(--bg); }
  button { width: 100%; margin-top: 16px; padding: 14px; border: 0; border-radius: 10px; background: var(--accent); color: var(--on-accent); font: inherit; font-weight: 600; cursor: pointer; min-height: 48px; }
  button[disabled] { opacity: .55; cursor: default; }
  button.secondary { background: transparent; color: var(--accent); border: 1px solid var(--line); margin-top: 10px; }
  .status { margin-top: 14px; font-size: 15px; overflow-wrap: anywhere; }
  .status.error { color: var(--bad); }
  .status.ok { color: var(--ok); }
  code { font-size: 13px; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 1px 6px; overflow-wrap: anywhere; }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<main>
  <h1>Add a photo to Marvin</h1>
  <p id="who" class="muted">Checking the link…</p>
  <div id="form" hidden>
    <label class="pick" id="pick">
      <span id="pick-text">Choose a photo</span>
      <input id="file" type="file" accept="image/*">
    </label>
    <img id="preview" class="preview" alt="Preview of the chosen photo" hidden>
    <button id="send" type="button" disabled>Upload</button>
  </div>
  <div id="done" hidden>
    <p class="status ok" id="done-text"></p>
    <p class="muted">Go back to the chat and tell the assistant it's done. It can find the photo from there.</p>
    <p class="muted">Asset id: <code id="asset-id"></code></p>
    <button class="secondary" id="copy" type="button">Copy the id</button>
  </div>
  <p id="status" class="status" role="status" aria-live="polite"></p>
</main>
<script nonce="__NONCE__">
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var secret = decodeURIComponent((location.hash || "").slice(1));
  if (secret) history.replaceState(null, "", location.pathname);  // keep the secret out of the address bar and history
  var maxBytes = 0, busy = false, previewUrl = null;

  function say(text, kind) { var s = $("status"); s.textContent = text; s.className = "status" + (kind ? " " + kind : ""); }
  function fail(text) { $("who").hidden = true; $("form").hidden = true; say(text, "error"); }
  function megabytes(n) { return Math.round(n / 1048576) + " MB"; }
  function sizeText(n) { return n < 1048576 ? Math.max(1, Math.round(n / 1024)) + " KB" : (n / 1048576).toFixed(1) + " MB"; }

  function answer(res) {
    return res.json().catch(function () { return {}; }).then(function (body) {
      if (!res.ok) throw new Error(body.error || "Something went wrong (" + res.status + ").");
      return body;
    });
  }

  if (!secret) {
    fail("This page needs the link the assistant gave you. Ask it for a new upload link.");
  } else {
    fetch("/mcp/upload/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: secret }), credentials: "omit", cache: "no-store" })
      .then(answer)
      .then(function (info) {
        maxBytes = info.maxBytes;
        $("who").textContent = "For " + info.workspace + ", from " + info.app + " (signed in as " + info.user + "). One photo, up to " + megabytes(info.maxBytes) + ".";
        $("form").hidden = false;
      })
      .catch(function (e) { fail(e.message); });
  }

  $("file").addEventListener("change", function () {
    var f = this.files && this.files[0];
    if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
    $("preview").hidden = true;
    $("send").disabled = true;
    if (!f) { $("pick-text").textContent = "Choose a photo"; return; }
    $("pick-text").textContent = f.name + " (" + sizeText(f.size) + "), choose another";
    if (maxBytes && f.size > maxBytes) { say("That file is " + megabytes(f.size) + "; the limit is " + megabytes(maxBytes) + ".", "error"); return; }
    say("");
    if (/^image\\//.test(f.type)) { previewUrl = URL.createObjectURL(f); $("preview").src = previewUrl; $("preview").hidden = false; }
    $("send").disabled = false;
  });

  $("send").addEventListener("click", function () {
    var f = $("file").files && $("file").files[0];
    if (!f || busy) return;
    busy = true; $("send").disabled = true; say("Uploading…");
    var body = new FormData();
    body.append("token", secret);
    body.append("file", f, f.name);
    fetch("/mcp/upload", { method: "POST", body: body, credentials: "omit", cache: "no-store" })
      .then(answer)
      .then(function (out) {
        $("form").hidden = true; $("who").hidden = true; say("");
        $("done-text").textContent = "Added " + (out.name || "your photo") + " to the library.";
        $("asset-id").textContent = out.assetId;
        $("done").hidden = false;
      })
      .catch(function (e) {
        busy = false; $("send").disabled = false;
        say(e.message, "error");
      });
  });

  $("copy").addEventListener("click", function () {
    var text = $("asset-id").textContent;
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(function () { $("copy").textContent = "Copied"; }, function () {});
  });
})();
</script>
</body>
</html>
"""


def render(nonce: str) -> str:
    return PAGE.replace("__NONCE__", nonce)
