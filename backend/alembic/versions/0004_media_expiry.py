"""Expire each upload and its dependent clips, shares and jobs after 72 hours."""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # UTC timestamp arithmetic is immutable and avoids DST changing the 72-hour TTL.
    op.execute("ALTER TABLE videos ADD COLUMN expires_at timestamptz GENERATED ALWAYS AS "
        "((created_at AT TIME ZONE 'UTC' + interval '72 hours') AT TIME ZONE 'UTC') STORED")
    op.create_index("idx_videos_expiry", "videos", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_videos_expiry", table_name="videos")
    op.drop_column("videos", "expires_at")
