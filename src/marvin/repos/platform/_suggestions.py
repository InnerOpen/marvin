"""Shared AI write-back staging for entity repositories.

Any repo whose model has a `suggestion_json` column (entries, assets, resources) mixes this in to
get the stage / apply / clear trio. `apply_fields` — how a proposed {target: value} map is written
onto the entity — stays per-repo, since targets differ (a tag junction, a JSON path, a column).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class SuggestionWritebackMixin:
    """stage / apply / clear the entity's pending `suggestion_json`.

    Requires the host repo to provide `self.session`, `self.model` (with a `suggestion_json`
    column), `self.get_one`, and an `apply_fields(entity_id, {target: value})` method.
    """

    # Provided by the host repository (declared here so the mixin type-checks in isolation).
    if TYPE_CHECKING:
        session: Session
        model: type[Any]

        # Signature mirrors RepositoryGeneric.get_one so the two base classes stay
        # compatible when a repo mixes both in.
        def get_one(self, value: Any, key: str | None = None, any_case: bool = False, override_schema: Any = None) -> Any: ...
        def apply_fields(self, entity_id: Any, fields: dict) -> None: ...

    def stage_suggestion(self, entity_id: Any, fields: dict) -> None:
        """Merge proposed fields into the entity's pending suggestion_json (for later review)."""
        obj = self.session.get(self.model, entity_id)
        if not obj:
            return
        staged = dict(obj.suggestion_json or {})
        staged.update(fields)
        obj.suggestion_json = staged
        self.session.commit()

    def apply_suggestion(self, entity_id: Any):
        """Apply the staged suggestion_json onto the entity and clear it."""
        obj = self.session.get(self.model, entity_id)
        if not obj:
            return None
        if obj.suggestion_json:
            self.apply_fields(entity_id, {k: v for k, v in obj.suggestion_json.items() if k != "_meta"})
            obj.suggestion_json = None
            self.session.commit()
        return self.get_one(entity_id)

    def clear_suggestion(self, entity_id: Any):
        """Discard the staged suggestion_json without applying it."""
        obj = self.session.get(self.model, entity_id)
        if obj and obj.suggestion_json is not None:
            obj.suggestion_json = None
            self.session.commit()
        return self.get_one(entity_id)
