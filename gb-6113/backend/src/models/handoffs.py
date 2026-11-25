from sqlalchemy import JSON, BigInteger, Boolean, Column, ForeignKey, Integer, String, Table, UniqueConstraint

from .base import metadata

handoffs = Table(
    "handoffs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_run_id", ForeignKey("runs.id"), nullable=False, index=True),
    Column("continuation_run_id", ForeignKey("runs.id"), nullable=True, index=True),
    Column("replica", String(48), nullable=False),
    Column("idempotency_key", String(96), nullable=True),
    Column("request_digest", String(64), nullable=True),
    Column("official", Boolean, nullable=False, default=True, server_default="true"),
    Column("manifest", JSON(none_as_null=True), nullable=False),
    Column("actor", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=True),
    UniqueConstraint("source_run_id", name="uq_handoffs_official_source_run"),
    UniqueConstraint("continuation_run_id", name="uq_handoffs_continuation_run"),
    UniqueConstraint("idempotency_key", name="uq_handoffs_idempotency_key"),
)
