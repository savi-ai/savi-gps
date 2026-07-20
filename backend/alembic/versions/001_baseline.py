"""Baseline schema via SQLAlchemy metadata.

Fresh installs get all tables from ORM models. Existing SQLite dev DBs may
still rely on legacy boot-time ALTER paths until USE_LEGACY_SQLITE_MIGRATIONS=false.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.core.database import Base, engine

    Base.metadata.create_all(bind=engine)


def downgrade() -> None:
    pass
