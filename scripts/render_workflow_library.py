#!/usr/bin/env python3
"""Render docs/workflow-library/catalogue.md from the Workflow Library's catalogue.

The catalogue (src/marvin/services/automation/recipes/catalogue.json) is the source of truth; this writes
the readable table of contents from it. tests/test_workflow_library.py fails when the markdown is stale.

    uv run python scripts/render_workflow_library.py            # rewrite docs/workflow-library/catalogue.md
    uv run python scripts/render_workflow_library.py --stdout   # print it
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "src" / "marvin" / "services" / "automation" / "recipes" / "catalogue.json"
OUT = ROOT / "docs" / "workflow-library" / "catalogue.md"
RECIPE_URL = "../../src/marvin/services/automation/recipes"

STATUS_ORDER = ("verified-current", "supported-after-configuration", "needs-adapter", "needs-engine-capability", "concept")


def _trigger(r: dict) -> str:
    t = r.get("trigger") or {}
    kind, event = t.get("type"), t.get("event")
    if kind == "event":
        return f"`{event}`"
    if kind == "subscription":
        return f"subscription: `{event}`"
    if kind in ("on_error", "chained"):
        return f"`{kind}` (`{event}`)"
    return f"`{kind}`" if kind else "—"


def _deps(r: dict) -> str:
    return ", ".join(d["capability"] for d in r.get("dependencies") or []) or "—"


def _recipe_link(r: dict) -> str:
    if r.get("recipe"):
        return f"[{r['id']}]({RECIPE_URL}/{r['recipe']})"
    return f"`{r['id']}`"


def render(cat: dict) -> str:
    recipes = cat["recipes"]
    counts = cat["counts"]
    lines = [
        "# Workflow Library catalogue",
        "",
        "Rendered from `src/marvin/services/automation/recipes/catalogue.json` by `scripts/render_workflow_library.py` — do not edit by hand.",
        "",
        f"{len(recipes)} recipes: " + ", ".join(f"**{counts.get(s, 0)}** {s}" for s in STATUS_ORDER if counts.get(s)) + ".",
        "",
        "Statuses are defined in [README.md](README.md). A recipe link opens its workflow JSON (with `{{setup}}` placeholders); "
        "`<id>.vars.json` beside it declares each placeholder's type.",
        "",
        "## Runnable today",
        "",
        "| Recipe | Status | Trigger | Needs | Side effects |",
        "|---|---|---|---|---|",
    ]
    for r in recipes:
        if not r["runnable"]:
            continue
        needs = []
        for i in (r.get("prerequisites") or {}).get("integrations") or []:
            needs.append(
                f"{i['provider']} integration" if i.get("provider") else f"an integration that can {i['capability']} ({i.get('examples') or 'any'})"
            )
        needs += (r.get("prerequisites") or {}).get("features") or []
        for o in r.get("supporting_objects") or []:
            if o.get("required") and o["kind"] not in ("integration_connection",):
                needs.append(o["kind"].replace("_", " "))
        effects = ", ".join(sorted({e["kind"].replace("_", " ") + (" ⚠" if e.get("flag") else "") for e in r.get("side_effects") or []})) or "—"
        lines.append(f"| {_recipe_link(r)} — {r['title']} | {r['status']} | {_trigger(r)} | {'; '.join(dict.fromkeys(needs)) or '—'} | {effects} |")
    lines += ["", "## Waiting on a capability or an adapter", "", "| Recipe | Status | Trigger | Blocked by |", "|---|---|---|---|"]
    for r in recipes:
        if r["runnable"]:
            continue
        lines.append(f"| `{r['id']}` — {r['title']} | {r['status']} | {_trigger(r)} | {_deps(r)} |")
    lines += ["", "## By category", ""]
    by_cat: dict[str, list[dict]] = {}
    for r in recipes:
        by_cat.setdefault(r["category"], []).append(r)
    for cat_name, items in by_cat.items():
        lines += [f"### {cat_name}", ""]
        for r in items:
            lines.append(f"- {_recipe_link(r)} — **{r['title']}** · {r['status']} · {_trigger(r)}  ")
            lines.append(f"  {r['outcome']}")
            for n in r.get("notes") or []:
                lines.append(f"  - {n}")
            if r.get("dependencies"):
                lines.append(
                    "  - Blocked by: " + "; ".join(f"`{d['capability']}`" + (f" ({d['why']})" if d.get("why") else "") for d in r["dependencies"])
                )
        lines.append("")
    lines += ["## Capability gaps", "", "| Id | Capability | Priority | Recipes blocked | Acceptance |", "|---|---|---|---|---|"]
    blocked: dict[str, int] = {}
    for r in recipes:
        for d in r.get("dependencies") or []:
            blocked[d["capability"]] = blocked.get(d["capability"], 0) + 1
    for gid, g in sorted(cat["capabilities"].items(), key=lambda kv: (-blocked.get(kv[0], 0), kv[0])):
        lines.append(f"| `{gid}` | {g['name']} | {g['priority']} | {blocked.get(gid, 0)} | {g['acceptance']} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    text = render(json.loads(CATALOGUE.read_text(encoding="utf-8")))
    if "--stdout" in argv:
        sys.stdout.write(text)
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
