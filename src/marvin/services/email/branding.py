"""The brand an email's wrapper shows: the name in its header, the line in its footer, the colour of its accents.

A workspace's emails (invitations, its workflows' sends, its alerts) carry the workspace's brand, each value falling
back on its own: the name to the workspace's setting, then its site title, then its name; the footer to its setting,
then "Sent by <name>"; the colour to its setting, then the platform's. Emails with no workspace (password resets,
platform alerts) carry the platform's brand (Admin → Email → Branding, services/platform_policy.py).

The workspace's settings are `group_preferences.email_branding_json` (Settings → Email → Branding).
"""

from __future__ import annotations

from marvin.services.platform_policy import clean_email_branding, email_branding


def _workspace_row(session, group_id):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    group = session.get(Groups, group_id)
    prefs = session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == group_id).first()
    return group, prefs


def _resolve(stored: dict, site_title: str | None, workspace_name: str | None) -> dict:
    name = stored.get("product_name") or (site_title or "").strip() or (workspace_name or "").strip() or email_branding()["product_name"]
    return {
        "product_name": name,
        "footer_text": stored.get("footer_text") or f"Sent by {name}",
        "accent_color": stored.get("accent_color") or email_branding()["accent_color"],
    }


def workspace_branding_view(session, group_id) -> dict:
    """The workspace's own values (blank where unset) and what its emails show with them."""
    group, prefs = _workspace_row(session, group_id)
    stored = dict((prefs.email_branding_json if prefs else None) or {})
    effective = _resolve(stored, prefs.site_title if prefs else None, group.name if group else None)
    return {
        "product_name": stored.get("product_name", ""),
        "footer_text": stored.get("footer_text", ""),
        "accent_color": stored.get("accent_color", ""),
        "effective": effective,
    }


def save_workspace_branding(session, group_id, values: dict) -> dict:
    """Store the set values (a blank one falls back). Raises platform_policy.PolicyError on a bad value."""
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    clean = clean_email_branding(values)
    _, prefs = _workspace_row(session, group_id)
    if prefs is None:
        prefs = GroupPreferencesModel(session=session, group_id=group_id)
        session.add(prefs)
    prefs.email_branding_json = clean or None
    session.commit()
    return workspace_branding_view(session, group_id)


def effective_branding(group_id=None) -> dict:
    """What an email shows: the workspace's brand when it has one, else the platform's."""
    if not group_id:
        return email_branding()
    try:
        from marvin.db.db_setup import session_context

        with session_context() as session:
            return workspace_branding_view(session, group_id)["effective"]
    except Exception:  # noqa: BLE001 — no database (a script, a test without one): the platform's brand
        return email_branding()
