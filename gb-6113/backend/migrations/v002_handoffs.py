from src.models.handoffs import handoffs


def upgrade(connection):
    # Version 2 adds the official continuation hand-off ledger.  v001's
    # declarative create_all also knows about this table for fresh databases;
    # checkfirst keeps this migration safe on both fresh and existing volumes.
    handoffs.create(bind=connection, checkfirst=True)
