"""Create tables on first run. Idempotent; safe to call every start.

For schema *changes* later, use Alembic:
    alembic revision --autogenerate -m "describe change"
    alembic upgrade head
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from .models import Base
from .session import engine

log = logging.getLogger(__name__)


# Idempotent ALTERs run after create_all so existing tables pick up new columns
# without requiring a full Alembic round-trip. Postgres-only (ADD COLUMN IF NOT
# EXISTS); each statement must be a no-op on an already-migrated DB.
_POST_CREATE_ALTERS: tuple[str, ...] = (
    "ALTER TABLE scored_results ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
)


def init_db() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in _POST_CREATE_ALTERS:
            conn.execute(text(stmt))
    log.info("DB ready at %s", engine.url)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("ok")
