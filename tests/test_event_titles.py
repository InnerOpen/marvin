"""A newly sent event's title (`message_title` in the Event Log) is the catalog's display name, falling
back to one derived from the type name for types the catalog doesn't name for display."""

from enum import auto

from marvin.services.event_bus_service.event_types import EventBusMessage, EventTypeBase, EventTypes
from marvin.services.events.event_catalog import CATALOG, event_title


def test_webhook_triggered_is_titled_by_its_catalog_name():
    assert EventBusMessage.from_type(EventTypes.webhook_triggered).title == "Site Rebuild Sent"


def test_catalog_names_replace_derived_titles():
    assert EventBusMessage.from_type(EventTypes.automation_failed).title == "Workflow Failed"
    assert EventBusMessage.from_type(EventTypes.api_token_created).title == "API Token Created"
    assert EventBusMessage.from_type(EventTypes.entry_published, body="b") == EventBusMessage(title="Entry Published", body="b")


def test_aliases_and_internal_plumbing_keep_the_derived_title():
    # Their catalog names carry UI annotations: "Site Build Started (old name)", "Webhook Task (internal)".
    assert event_title("site_build_started") is None
    assert EventBusMessage.from_type(EventTypes.site_build_started).title == "Site Build Started"
    assert event_title("webhook_task") is None
    assert EventBusMessage.from_type(EventTypes.webhook_task).title == "Webhook Task"


def test_an_uncatalogued_type_keeps_the_derived_title():
    class PluginEvents(EventTypeBase):
        plugin_thing_happened = auto()

    assert event_title("plugin_thing_happened") is None
    assert EventBusMessage.from_type(PluginEvents.plugin_thing_happened).title == "Plugin Thing Happened"


def test_every_offered_title_is_the_catalog_name_without_annotations():
    for entry in CATALOG:
        title = event_title(entry.event_type)
        if title is not None:
            assert title == entry.name
            assert "(" not in title, f"{entry.event_type}: {title!r} carries a UI annotation"
