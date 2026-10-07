import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://vclips:change_me@localhost:5432/vclips"
)
os.environ.setdefault("JWT_SECRET", "test-secret")