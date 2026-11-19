"""Alembic environment: runs migrations against DATABASE_URL."""

from logging.config import fileConfig

from alembic import context

from orderflow_common.connections import make_engine
from orderflow_common.settings import env_str

if context.config.config_file_name and not context.config.attributes.get("skip_logging"):
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)


def run_migrations_online() -> None:
    url = context.config.attributes.get("database_url") or env_str("DATABASE_URL")
    engine = make_engine(url, pool_size=1)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
