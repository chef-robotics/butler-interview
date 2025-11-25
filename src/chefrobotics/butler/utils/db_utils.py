import os
import pathlib

import sqlalchemy

from chefrobotics.butler.models import base

CHEF_BUTLER_DB_DIR = os.environ.get("CHEF_BUTLER_DB_DIR", "/var/lib/chef")
CHEF_BUTLER_DB_PATH = CHEF_BUTLER_DB_DIR + "/butler.db"


def get_butler_db_dir():
    return CHEF_BUTLER_DB_DIR


def get_sqlite_db_engine(debug: bool = False):
    return sqlalchemy.engine.create_engine(
        f"sqlite:///{CHEF_BUTLER_DB_PATH}", echo=debug
    )


def get_or_create_butler_db() -> sqlalchemy.engine.Engine:
    pathlib.Path(CHEF_BUTLER_DB_PATH).touch(exist_ok=True)
    engine = get_sqlite_db_engine()
    base.ChefDbBase.metadata.create_all(bind=engine, checkfirst=True)
    return engine
