from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from chefrobotics.butler.models import job
from chefrobotics.butler.models.base import ChefDbBase
from chefrobotics.butler.utils import db_utils

# Setup logging if provided
if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

BUTLER_DB_METADATA = ChefDbBase.metadata


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": str(db_utils.get_sqlite_db_engine().url)},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=BUTLER_DB_METADATA
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline migrations are not supported for Chef Butler DB."
    )
else:
    run_migrations_online()
