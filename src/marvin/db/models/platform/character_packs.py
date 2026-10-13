"""The platform's character library: bubble-character packs a platform admin uploads once, for any
workspace or agent to pick (AI settings → Persona, Settings → Agents).

A pack is the same shape a workspace's own character has — {"states": {state: url}, "files": [{name,
key, url}]} — but its files live under a platform storage prefix rather than in any workspace's assets
(see services/ai/character_library.py). Workspaces and agents point at a pack by id, so renaming it or
re-picking its animations reaches everyone using it.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID


class CharacterPackModel(SqlAlchemyBase, BaseMixins):
    __tablename__ = "character_packs"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    slug: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    pack: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    """{"states": {state: url}, "files": [{name, key, url}]} — see services/ai/character.py."""
    created_by: Mapped[GUID | None] = mapped_column(GUID, nullable=True)

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
