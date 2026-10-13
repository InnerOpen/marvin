from datetime import datetime

from sqlalchemy import Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from text_unidecode import unidecode

from ._model_utils.datetime import NaiveDateTime, get_utc_now


class SqlAlchemyBase(DeclarativeBase):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, default=get_utc_now, index=True)
    update_at: Mapped[datetime | None] = mapped_column(NaiveDateTime, default=get_utc_now, onupdate=get_utc_now)

    @classmethod
    def normalize(cls, val: str) -> str:
        return unidecode(val).lower().strip()


class BaseMixins:
    """
    `self.update` method which directly passing arguments to the `__init__`
    """

    def update(self, *args, **kwargs):
        self.__init__(*args, **kwargs)

        for k, v in kwargs.items():
            if hasattr(self, k) and v == []:
                setattr(self, k, v)


from .groups import *  # noqa: E402, F401, F403
from .platform import APIClients, Collections, Entries, EntryCollections, EntryTypes  # noqa: E402, F401
from .users import *  # noqa: E402, F401, F403
