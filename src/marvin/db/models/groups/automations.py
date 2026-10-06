"""SQLAlchemy model for per-workspace user-configured automations (Flavor B).

An automation is a data-defined reaction: a trigger, a conditions matcher, and an ordered
`actions` pipeline — authored by a workspace admin rather than hardcoded in a listener class
(contrast the Flavor A developer-defined reactions in `_get_listeners`). One generic listener
(`AutomationReactionListener`) loads and runs these rows.
"""

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID
from .._model_utils.installed_by import InstalledByMixin

if TYPE_CHECKING:
    from .groups import Groups


# How each trigger type is stored. `trigger_event` is the event a trigger listens to — the trigger's
# own `event` for an event trigger, implied by the type for the others (None: nothing event-driven
# fires it). `trigger_ref` is the one thing a trigger type points at, under the key the API uses.
TRIGGER_TYPE_EVENTS: dict[str, str] = {"incoming_webhook": "incoming_webhook", "chained": "automation_ran", "on_error": "automation_failed"}
TRIGGER_REF_KEYS: dict[str, str] = {"incoming_webhook": "webhook", "chained": "automation", "on_error": "automation"}


def _canonical(event: str | None) -> str | None:
    """An old event name → the event it stands for (site_build_* → site_deployment_*)."""
    from marvin.services.events.event_catalog import canonical_event_type

    return canonical_event_type(event) if event else event


def canonical_body(body: dict | None) -> dict | None:
    """The rule with every Emit event step (actions and on-failure steps) naming the event an old name stands
    for. Returns `body` itself when nothing changes."""
    if not isinstance(body, dict):
        return body
    out = body
    for key in ("actions", "on_failure"):
        steps = body.get(key)
        if not isinstance(steps, list):
            continue
        fixed = [
            {**step, "event": _canonical(step["event"])}
            if isinstance(step, dict) and step.get("kind") == "emit_event" and isinstance(step.get("event"), str)
            else step
            for step in steps
        ]
        if fixed != steps:
            out = {**out, key: fixed}
    return out


def split_trigger(trigger: dict | None) -> dict:
    """The API's ``definition.trigger`` → the four trigger columns. ``assemble_trigger`` is the inverse.

    A trigger without a ``type`` is an event trigger (the engine's long-standing default), stored as
    one. Keys the columns don't model (a schedule's ``schedule_type``/``schedule_config``, or anything
    a forward-compatible definition adds) are kept verbatim in ``trigger_config``.
    """
    if not isinstance(trigger, dict):
        return {"trigger_type": None, "trigger_event": None, "trigger_ref": None, "trigger_config": None}
    rest = dict(trigger)
    ttype = rest.pop("type", None) or "event"
    event = ref = None
    if ttype == "event":
        if isinstance(rest.get("event"), str) or rest.get("event") is None:
            event = _canonical(rest.pop("event", None))
    elif ttype in TRIGGER_TYPE_EVENTS:
        event = TRIGGER_TYPE_EVENTS[ttype]
        key = TRIGGER_REF_KEYS[ttype]
        if isinstance(rest.get(key), str) or rest.get(key) is None:
            ref = rest.pop(key, None)
    return {"trigger_type": ttype, "trigger_event": event, "trigger_ref": ref, "trigger_config": rest or None}


def assemble_trigger(trigger_type: str | None, trigger_event: str | None, trigger_ref: str | None, trigger_config: dict | None) -> dict | None:
    """The four trigger columns → the API's ``definition.trigger`` (None: the workflow has no trigger)."""
    if trigger_type is None:
        return None
    trigger: dict = {"type": trigger_type}
    if trigger_type == "event" and trigger_event is not None:
        trigger["event"] = _canonical(trigger_event)
    if trigger_type in TRIGGER_REF_KEYS and trigger_ref is not None:
        trigger[TRIGGER_REF_KEYS[trigger_type]] = trigger_ref
    trigger.update(trigger_config or {})
    return trigger


class WorkspaceAutomationModel(SqlAlchemyBase, BaseMixins, InstalledByMixin):
    """A user-configured automation: `trigger → conditions → actions`.

    The API speaks one ``definition`` dict:
        {
          "trigger":    {"type": "event", "event": "entry_published"},
          "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "recipe"}],
          "actions":    [{"kind": "operation", "op": "generate-summary",
                          "input": {}, "write_back": true}]
        }

    Storage splits it: the trigger lives in real columns (``trigger_type``, ``trigger_event``,
    ``trigger_ref``, ``trigger_config``) so "what reacts to event X" is a query, and the rest
    (conditions, actions, target, on_failure, …) in the ``definition`` JSON column (``body``).
    ``definition`` and ``trigger`` below are the one accessor pair: read them, assign them; never
    reach for ``body`` or the trigger columns to rebuild the shape by hand.

    Deny-by-default: an automation does nothing unless `enabled` is true AND its actions pass the
    `invocation_sources` gate for the `"automation"` source. Managed by ADMIN/OWNER.
    """

    __tablename__ = "workspace_automations"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[Optional["Groups"]] = orm.relationship("Groups", back_populates="automations")

    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    # The rule minus its trigger: {conditions, actions, target?, on_failure?, …}. Validated by the
    # engine, not the DB. Column name kept as `definition` (it always held the rule).
    body: Mapped[dict | None] = mapped_column("definition", sa.JSON, nullable=True)
    # The trigger — see split_trigger / assemble_trigger. NULL trigger_type: the workflow has none.
    trigger_type: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    trigger_event: Mapped[str | None] = mapped_column(sa.String, nullable=True, index=True)
    trigger_ref: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    trigger_config: Mapped[dict | None] = mapped_column(sa.JSON(none_as_null=True), nullable=True)
    created_by: Mapped[GUID | None] = mapped_column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (sa.UniqueConstraint("group_id", "slug", name="uq_automations_group_slug"),)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        # Not a mapped column, so auto_init leaves it to us.
        if "definition" in kwargs:
            self.definition = kwargs["definition"]

    @property
    def trigger(self) -> dict | None:
        """The trigger in the API's shape (``definition.trigger``), or None when there is none."""
        return assemble_trigger(self.trigger_type, self.trigger_event, self.trigger_ref, self.trigger_config)

    @trigger.setter
    def trigger(self, value: dict | None) -> None:
        for column, stored in split_trigger(value).items():
            setattr(self, column, stored)

    @property
    def definition(self) -> dict | None:
        """The whole rule as the API reads and writes it: the stored body plus the trigger."""
        trigger, body = self.trigger, canonical_body(self.body)
        if trigger is None:
            return dict(body) if body is not None else None
        return {"trigger": trigger, **(body or {})}

    @definition.setter
    def definition(self, value: dict | None) -> None:
        if value is None:
            self.body, self.trigger = None, None
            return
        self.trigger = value.get("trigger")
        self.body = canonical_body({k: v for k, v in value.items() if k != "trigger"})
