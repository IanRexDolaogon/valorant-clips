from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings


if context.is_offline_mode():
    context.configure(url=settings.database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
