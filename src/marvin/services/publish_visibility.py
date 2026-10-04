"""What the publishing API serves — shared by the publishing controller and the site-rebuild trigger,
so "can a site see this?" has one answer."""


def is_publishable_type(entry_type) -> bool:
    """False only for an entry type whose capabilities say `publishable: false` — submissions (contact,
    newsletter signups…) and other private records. Absent capabilities count as publishable."""
    caps = entry_type.capabilities_json if isinstance(entry_type.capabilities_json, dict) else {}
    return caps.get("publishable") is not False


def non_publishable_type_ids(entry_types) -> list:
    """Ids of the entry types the publishing API never serves, whatever their entries' status."""
    return [et.id for et in entry_types if not is_publishable_type(et)]
