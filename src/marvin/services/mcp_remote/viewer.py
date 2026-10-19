"""The MCP Apps image viewer: the page `show_image` points its clients at.

MCP Apps (the `io.modelcontextprotocol/ui` extension, spec 2026-01-26) lets a tool name a `ui://` resource in
`_meta.ui.resourceUri`. A host that supports it fetches that resource (`text/html;profile=mcp-app`), renders it in a
sandboxed iframe in the conversation and hands it the tool's result over `postMessage` (JSON-RPC): `ui/initialize`,
`ui/notifications/initialized`, then `ui/notifications/tool-result` carrying the same `CallToolResult` a plain client
gets. So the result stays what it is (a text block with the asset's details and an image block) and the page only
draws it; a client without the extension shows the image block as before.

No SDK support is needed on the server: the `mcp` package passes `_meta` on tools, resources and their contents
through, and the extension is plain metadata plus a resource. What is outside this server's control is whether a given
host renders it. The page asks for nothing beyond the default sandbox (the default CSP allows `data:` images, which is
how the picture arrives; no network, no scripts from elsewhere), and uses no library.
"""

from __future__ import annotations

VIEWER_URI = "ui://marvin/image-viewer"
VIEWER_MIME = "text/html;profile=mcp-app"
PROTOCOL_VERSION = "2026-01-26"
UI_EXTENSION = "io.modelcontextprotocol/ui"

# The tool's `_meta`: the nested form the spec uses, and the flat key older hosts read.
TOOL_META = {"ui": {"resourceUri": VIEWER_URI}, "ui/resourceUri": VIEWER_URI}

VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Marvin image</title>
<style>
  :root { color-scheme: light dark; --ink: #1f2933; --muted: #62707d; --line: #d5dbe1; --accent: #2457c5; }
  :root[data-theme="light"] { color-scheme: light; }
  :root[data-theme="dark"] { color-scheme: dark; }
  :root[data-theme="dark"] { --ink: #e8ecef; --muted: #9aa7b2; --line: #36414b; --accent: #7aa2f7; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --ink: #e8ecef; --muted: #9aa7b2; --line: #36414b; --accent: #7aa2f7; } }
  html, body { margin: 0; background: transparent; color: var(--ink); font: 14px/1.4 system-ui, sans-serif; }
  figure { margin: 0; padding: 8px; }
  img { display: block; max-width: 100%; height: auto; border-radius: 6px; border: 1px solid var(--line); }
  figcaption { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; }
  .name { font-weight: 600; overflow-wrap: anywhere; }
  .size { color: var(--muted); font-size: 12px; }
  a { color: var(--accent); }
  p { margin: 0; padding: 8px; color: var(--muted); }
</style>
</head>
<body>
<main id="root"><p>Loading the picture…</p></main>
<script>
(function () {
  "use strict";
  var pending = {}, nextId = 1, root = document.getElementById("root");

  function post(message) {
    message.jsonrpc = "2.0";
    window.parent.postMessage(message, "*");
  }
  function request(method, params) {
    return new Promise(function (resolve, reject) {
      var id = nextId++;
      pending[id] = { resolve: resolve, reject: reject };
      post({ id: id, method: method, params: params });
    });
  }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function say(text) { root.replaceChildren(el("p", "", text)); }
  function safeUrl(value) {
    try { var u = new URL(value); return u.protocol === "https:" || u.protocol === "http:" ? u.href : null; } catch (e) { return null; }
  }
  function reportSize() {
    var h = Math.ceil(document.documentElement.getBoundingClientRect().height);
    post({ method: "ui/notifications/size-changed", params: { width: Math.ceil(document.documentElement.scrollWidth), height: h } });
  }

  function render(result) {
    var blocks = (result && result.content) || [], image = null, info = null, plain = "";
    blocks.forEach(function (b) {
      if (b.type === "image" && !image) image = b;
      if (b.type === "text" && !info) {
        plain = b.text;
        try { info = JSON.parse(b.text); } catch (e) { info = null; }
      }
    });
    if (!image) { say((info && info.error) || plain || "There is no picture in this result."); return; }
    var figure = el("figure"), img = document.createElement("img");
    img.src = "data:" + (image.mimeType || "image/jpeg") + ";base64," + image.data;
    img.alt = (info && (info.altText || info.name)) || "Image from Marvin";
    if (info && info.width) { img.width = info.width; img.height = info.height; }
    img.addEventListener("load", reportSize);
    figure.appendChild(img);
    var caption = el("figcaption");
    if (info && info.name) caption.appendChild(el("span", "name", info.name));
    if (info && info.width) caption.appendChild(el("span", "size", info.width + " \\u00d7 " + info.height + " px"));
    var href = info && safeUrl(info.url);
    if (href) {
      var a = el("a", "", "Open in Marvin");
      a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.addEventListener("click", function (ev) {
        ev.preventDefault();  // a sandboxed frame can't open windows itself: ask the host to
        request("ui/open-link", { url: href }).catch(function () {});
      });
      caption.appendChild(a);
    }
    figure.appendChild(caption);
    root.replaceChildren(figure);
    reportSize();
  }

  function theme(context) {
    if (context && (context.theme === "dark" || context.theme === "light")) document.documentElement.dataset.theme = context.theme;
  }

  window.addEventListener("message", function (event) {
    if (event.source !== window.parent) return;
    var m = event.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.method === undefined && m.id !== undefined) {  // an answer to one of our requests
      var p = pending[m.id];
      if (p) { delete pending[m.id]; if (m.error) p.reject(m.error); else p.resolve(m.result); }
      return;
    }
    if (m.method === "ui/notifications/tool-result") render(m.params);
    else if (m.method === "ui/notifications/host-context-changed") theme(m.params);
    else if (m.method === "ui/resource-teardown" && m.id !== undefined) post({ id: m.id, result: {} });
  });

  if (window.parent === window) { say("This page shows a Marvin picture inside an assistant that supports MCP Apps."); return; }
  request("ui/initialize", {
    protocolVersion: "__PROTOCOL_VERSION__",
    appInfo: { name: "Marvin image viewer", version: "1" },
    clientInfo: { name: "Marvin image viewer", version: "1" },
    appCapabilities: {}
  }).then(function (result) {
    theme(result && result.hostContext);
    post({ method: "ui/notifications/initialized", params: {} });
    reportSize();
  }).catch(function () { say("The assistant did not accept the viewer; the picture is in the tool result."); });
  if (window.ResizeObserver) new ResizeObserver(reportSize).observe(document.body);
})();
</script>
</body>
</html>
""".replace("__PROTOCOL_VERSION__", PROTOCOL_VERSION)
