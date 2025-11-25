#!/usr/bin/env python3
import sys
import traceback
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from chefrobotics import butler
from chefrobotics.butler.utils import db_utils


def _generate_alembic_config() -> Config:
    config = Config()

    # Get the migrations directory from the package
    package_dir = Path(butler.__file__).parent
    migration_dir = (package_dir / "migrations").resolve()

    config.set_main_option("script_location", str(migration_dir))
    config.set_main_option(
        "sqlalchemy.url", f"sqlite:///{db_utils.CHEF_BUTLER_DB_PATH}"
    )
    return config


def main():
    try:
        # Find or provision the DB
        engine = db_utils.get_or_create_butler_db()

        # Auto-run upgrade migrations if necessary
        # TODO(vinny): Consolidate with alembic.ini + other utils that run Alembic
        alembic_config = _generate_alembic_config()
        command.upgrade(alembic_config, "head")

        # Verify the DB is working with all columns
        with engine.connect() as conn:
            conn.execute(text("SELECT * FROM butler_job LIMIT 1")).all()

    except Exception as e:
        print(traceback.format_exc())
        print(f"❌ Failed to connect to Chef Butler DB")
        sys.exit(1)

    print("✅ Successfully connected to Chef Butler DB")


if __name__ == "__main__":
    main()
