"""Freeze the original ten-table schema as the migration baseline."""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Static, versioned DDL; never read the mutable root reference schema here.
    for statement in Path(__file__).with_suffix(".sql").read_text().split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "processing_jobs", "shares", "clips", "videos", "kill_events", "rounds",
        "match_players", "matches", "riot_accounts", "users",
    ):
        op.drop_table(table)
