#!/usr/bin/env python3
"""
A script to autogenerate a new migration with a *live DB connection* using
the Alembic env.py that forces online mode.

Usage:
  ./create_migration.py --message "Add new column to butler_job table"
"""
import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config


def main():
    parser = argparse.ArgumentParser(
        description="Autogenerate a new migration with a live DB connection"
    )
    parser.add_argument(
        "--message", "-m", required=True, help="Description of the migration"
    )

    args = parser.parse_args()
    revision_message = args.message

    # Point Alembic to the migrations directory
    # TODO(vinny): Consolidate with alembic.ini + other utils that run Alembic
    base_dir = Path(__file__).resolve().parent
    migrations_dir = (
        base_dir.parent / "src" / "chefrobotics" / "butler" / "migrations"
    )

    # Create fresh Alembic config pointing to the migrations directory
    alembic_cfg = Config()
    alembic_cfg.set_main_option(
        "file_template", "%%(year)d-%%(month).2d-%%(day).2d_%%(rev)s_%%(slug)s"
    )
    alembic_cfg.set_main_option("script_location", str(migrations_dir))

    # Upgrade the DB to the latest revision
    command.upgrade(alembic_cfg, "head")

    # Autogenerate the new revision
    command.revision(alembic_cfg, message=revision_message, autogenerate=True)


if __name__ == "__main__":
    main()
