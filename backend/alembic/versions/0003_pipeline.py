"""Track durable upload offsets and prevent duplicate clip/job planning."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("upload_offset_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_video_upload_offset", "videos", "upload_offset_bytes >= 0 AND upload_offset_bytes <= size_bytes")
    op.create_unique_constraint("uq_clip_window", "clips", ["video_id", "kill_event_id", "start_ms", "end_ms", "encode_mode"])
    op.create_unique_constraint("uq_job_clip", "processing_jobs", ["clip_id"])
    op.create_check_constraint("ck_job_status", "processing_jobs", "status IN ('queued','processing','ready','failed')")
    op.create_check_constraint("ck_job_encode", "processing_jobs", "encode_mode IN ('copy','reencode')")


def downgrade() -> None:
    op.drop_constraint("ck_job_encode", "processing_jobs")
    op.drop_constraint("ck_job_status", "processing_jobs")
    op.drop_constraint("uq_job_clip", "processing_jobs")
    op.drop_constraint("uq_clip_window", "clips")
    op.drop_constraint("ck_video_upload_offset", "videos")
    op.drop_column("videos", "upload_offset_bytes")
