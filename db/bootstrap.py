"""Create tables on first run. Idempotent; safe to call every start.

For schema *changes* later, use Alembic:
    alembic revision --autogenerate -m "describe change"
    alembic upgrade head
"""

from __future__ import annotations

import logging

from .models import Base
from .session import engine

log = logging.getLogger(__name__)


def init_db() -> None:
    Base.metadata.create_all(engine)
    log.info("DB ready at %s", engine.url)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("ok")
