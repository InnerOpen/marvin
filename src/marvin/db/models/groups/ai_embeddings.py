"""SQLAlchemy model for AI embeddings (semantic search / RAG)."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import BaseMixins, SqlAlchemyBase
from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID


class AIEmbeddingModel(SqlAlchemyBase, BaseMixins):
    """
    One embedded text chunk for an entity (entry, resource, asset).

    Embeddings are stored as a JSON float array for cross-database portability
    (SQLite dev, Postgres prod). On Postgres at scale this can migrate to a
    pgvector column; cosine similarity is computed in Python for the JSON form.
    """

    __tablename__ = "ai_embeddings"

    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID] = mapped_column(GUID, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)

    entity_type: Mapped[str] = mapped_column(sa.String, nullable=False)  # entry | resource | asset
    entity_id: Mapped[GUID] = mapped_column(GUID, nullable=False)

    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    chunk_text: Mapped[str] = mapped_column(sa.Text, nullable=False)

    embedding: Mapped[list] = mapped_column(sa.JSON, nullable=False)  # float array
    model_id: Mapped[str] = mapped_column(sa.String, nullable=False)  # embedding model used
    dimensions: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "chunk_index",
            "model_id",
            name="uq_ai_embeddings_entity_chunk_model",
        ),
        sa.Index("ix_ai_embeddings_entity", "entity_type", "entity_id"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        pass
