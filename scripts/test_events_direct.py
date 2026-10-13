#!/usr/bin/env python3
"""
Direct Event Dispatcher Test

Directly uses the event bus to dispatch test events, bypassing the API.
This verifies that the event system is wired up correctly.

Usage:
    source .venv/bin/activate && python scripts/test_events_direct.py
    OR
    ./scripts/test_events_direct.py (when virtual env is activated)
"""

import sys
from pathlib import Path
from uuid import uuid4

# Add src directory to path for imports when running directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


from marvin.core.config import get_app_settings
from marvin.db.db_setup import generate_session
from marvin.db.models.groups import Groups
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import (
    EventAPIClientData,
    EventOperation,
    EventTypes,
)

settings = get_app_settings()


def test_event_dispatching():
    """Test that events can be dispatched through the event bus."""
    print("\n🧪 Testing Event Dispatching System")
    print("=" * 80)

    # Get a database session
    session = next(generate_session())

    # Get the first workspace
    workspace = session.query(Groups).first()
    if not workspace:
        print("❌ No workspace found in database")
        return

    print(f"✅ Using workspace: {workspace.name} (ID: {workspace.id})")
    print()

    # Create event bus service WITHOUT background tasks
    # This ensures events are published synchronously so we can see the console output
    event_bus = EventBusService(session=session, bg_tasks=None)

    # Test 1: Dispatch API Client Created Event
    print("Test 1: Dispatching api_client_created event...")
    try:
        event_bus.dispatch(
            integration_id="test_event_system",
            group_id=workspace.id,
            event_type=EventTypes.api_client_created,
            document_data=EventAPIClientData(
                operation=EventOperation.create,
                api_client_id=uuid4(),
                api_client_name="Test Event Client",
                api_client_slug="test-event-client",
                workspace_id=workspace.id,
                permissions={"read:published_entries": True},
                enabled=True,
            ),
            message="Test event: API client created",
        )
        print("✅ Event dispatched successfully")
        print("   Type: api_client_created")
        print("   Integration: test_event_system")
        print("   Message: Test event: API client created")
    except Exception as e:
        print(f"❌ Failed to dispatch event: {e}")
        import traceback

        traceback.print_exc()

    print()

    # Test 2: Dispatch Entry Created Event
    print("Test 2: Dispatching entry_created event...")
    try:
        from marvin.services.event_bus_service.event_types import EventEntryData

        event_bus.dispatch(
            integration_id="test_event_system",
            group_id=workspace.id,
            event_type=EventTypes.entry_created,
            document_data=EventEntryData(
                operation=EventOperation.create,
                entry_id=uuid4(),
                entry_title="Test Entry",
                entry_type="page",
                workspace_id=workspace.id,
                author_id=uuid4(),
            ),
            message="Test event: Entry created",
        )
        print("✅ Event dispatched successfully")
        print("   Type: entry_created")
        print("   Integration: test_event_system")
        print("   Message: Test event: Entry created")
    except Exception as e:
        print(f"❌ Failed to dispatch event: {e}")
        import traceback

        traceback.print_exc()

    print()
    print("=" * 80)
    print("✨ Test complete!")
    print()
    print("Events were dispatched to the event bus.")
    print("They will be delivered to:")
    print("  • Configured webhooks")
    print("  • Integration actions wired to events (e.g. Apprise notifications)")
    print("  • Email subscriptions (if SMTP enabled)")
    print()
    print("To verify event delivery:")
    print("  1. Check server logs for 'Event dispatched' messages")
    print("  2. Configure a webhook and check delivery")
    print("  3. Connect an integration action (e.g. Apprise) to an event and check delivery")


if __name__ == "__main__":
    test_event_dispatching()
