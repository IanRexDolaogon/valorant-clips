"""Enforce case-insensitive account uniqueness at the database boundary."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX idx_users_email_lower ON users (lower(email))")


def downgrade() -> None:
    op.drop_index("idx_users_email_lower", table_name="users")
