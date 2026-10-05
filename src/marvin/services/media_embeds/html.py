"""The one place Marvin writes embed HTML. Every attribute value and every text node goes through
:func:`attrs` / :func:`text`, so nothing a provider (or an editor) supplied reaches a page unescaped.

Three shapes, matching the publishing contract:

- **direct** — ``<figure class="marvin-embed marvin-embed--{kind}">`` holding the iframe;
- **click_to_load** — the same figure with ``marvin-embed--facade``: a button carrying the iframe's
  ``src``, its attributes (JSON, ``src`` included) and the hosts it may load from, then a plain link
  fallback. Nothing third-party loads until the visitor clicks (a site's loader swaps the button for
  the iframe after checking the src host);
- **link card** — ``<a class="marvin-embed-link">`` when there is no safe player.

Sizing travels on the figure as a CSS custom property — ``--marvin-embed-aspect:16/9`` for video
players, ``--marvin-embed-height:352px`` for fixed-height ones — which the site's embed CSS reads.
The iframe carries only ``src``, ``title``, ``allow``, ``sandbox``, ``referrerpolicy`` and ``loading``
(the attributes a site loader allow-lists); fullscreen is granted through ``allow``, not
``allowfullscreen``.
"""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any

DEFAULT_CONSENT_TEXT = "Loading this player connects to {provider}, which may set cookies."
REFERRER_POLICY = "strict-origin-when-cross-origin"
_ASPECT = re.compile(r"^\d{1,3}/\d{1,3}$")


def text(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def attrs(values: dict[str, Any]) -> str:
    """Render attributes in order: ``None``/``False`` are dropped, ``True`` is a bare attribute, anything
    else is escaped (quotes included) inside double quotes. Returns a leading space when non-empty."""
    out: list[str] = []
    for name, value in values.items():
        if value is None or value is False:
            continue
        if value is True:
            out.append(f" {name}")
        else:
            out.append(f' {name}="{text(value)}"')
    return "".join(out)


def iframe_attributes(iframe: dict[str, Any]) -> dict[str, str]:
    """The iframe's attributes in render order — also the facade's ``data-marvin-embed-attrs``."""
    return {
        "src": iframe["src"],
        "title": iframe.get("title") or "",
        "allow": iframe.get("allow") or "",
        "sandbox": iframe.get("sandbox") or "",
        "referrerpolicy": iframe.get("referrerpolicy") or REFERRER_POLICY,
        "loading": "lazy",
    }


def sizing_style(iframe: dict[str, Any]) -> str | None:
    """The figure's sizing custom property, from Marvin's own registry values (validated anyway)."""
    height = iframe.get("height")
    if isinstance(height, int) and 0 < height < 5000:
        return f"--marvin-embed-height:{height}px"
    aspect = iframe.get("aspectRatio") or iframe.get("aspect_ratio")
    if isinstance(aspect, str) and _ASPECT.match(aspect):
        return f"--marvin-embed-aspect:{aspect}"
    return None


def consent(consent_text: str | None, provider_name: str) -> str:
    return (consent_text or DEFAULT_CONSENT_TEXT).replace("{provider}", provider_name)


def link_card_html(*, provider: str, href: str, title: str, provider_name: str, has_title: bool) -> str:
    inner = f'<span class="marvin-embed-link__title">{text(title)}</span>'
    if has_title:
        inner += f' <span class="marvin-embed-link__provider">on {text(provider_name)}</span>'
    return f"<a{attrs({'class': 'marvin-embed-link', 'href': href, 'rel': 'noopener noreferrer', 'data-provider': provider})}>{inner}</a>"


def player_html(
    *,
    provider: str,
    provider_name: str,
    kind: str,
    iframe: dict[str, Any],
    frame_hosts: list[str],
    link_href: str,
    link_title: str,
    title: str | None,
    mode: str,
    consent_text: str | None,
) -> str:
    """The figure for an ``ok`` embed, in ``direct`` or ``click_to_load`` mode."""
    iframe_attrs = iframe_attributes(iframe)
    figure_classes = f"marvin-embed marvin-embed--{kind}"
    figure_attrs: dict[str, Any] = {"data-provider": provider, "style": sizing_style(iframe)}

    if mode == "direct":
        frame = f"<iframe{attrs(iframe_attrs)}></iframe>"
        return f"<figure{attrs({'class': figure_classes, **figure_attrs})}>{frame}</figure>"

    button_attrs = {
        "type": "button",
        "class": "marvin-embed__load",
        "data-marvin-embed-src": iframe_attrs["src"],
        "data-marvin-embed-attrs": json.dumps(iframe_attrs, separators=(",", ":")),
        "data-marvin-embed-hosts": json.dumps(list(frame_hosts), separators=(",", ":")),
    }
    button = (
        f"<button{attrs(button_attrs)}>"
        f'<span class="marvin-embed__provider">{text(provider_name)}</span>'
        f'<span class="marvin-embed__title">{text(title or link_title)}</span>'
        f'<span class="marvin-embed__consent">{text(consent(consent_text, provider_name))}</span>'
        "</button>"
    )
    fallback = f"<a{attrs({'class': 'marvin-embed__link', 'href': link_href, 'rel': 'noopener noreferrer'})}>{text(link_title)}</a>"
    return f"<figure{attrs({'class': figure_classes + ' marvin-embed--facade', **figure_attrs})}>{button}{fallback}</figure>"
