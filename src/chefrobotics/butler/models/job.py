import enum
import uuid

from sqlalchemy import Column
from sqlalchemy import engine
from sqlalchemy import orm
from sqlalchemy import sql
from sqlalchemy import text
from sqlalchemy.dialects.sqlite import BOOLEAN
from sqlalchemy.dialects.sqlite import INTEGER
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.dialects.sqlite import TEXT
from sqlalchemy.dialects.sqlite import TIMESTAMP
from sqlalchemy.orm import Session as DbSession

from chefrobotics.butler.models.base import ChefDbBase


class JobStatus(enum.Enum):
    PENDING = 0
    IN_PROGRESS = 1
    COMPLETED = 2
    FAILED = 3
    CANCELLED = 4


class ButlerJob(ChefDbBase):
    __tablename__ = "butler_job"

    job_id = Column(TEXT, primary_key=True, default=lambda _: str(uuid.uuid4()))
    job_type = Column(TEXT, nullable=False)
    context = Column(JSON, nullable=False)
    status = Column(TEXT, nullable=False, default=JobStatus.PENDING.name)
    failure_reason = Column(TEXT)
    retry_attempts = Column(INTEGER, nullable=False, default=0)
    create_time = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=sql.func.now()
    )
    update_time = Column(
        TIMESTAMP(timezone=True),
        server_default=sql.func.now(),
        onupdate=sql.func.current_timestamp(),
    )
    source = Column(TEXT, nullable=False, default="unknown")
    concurrency_locks = Column(TEXT, nullable=True)
    created_by_version = Column(TEXT, nullable=True)
    cancel_requested = Column(BOOLEAN, nullable=False, default=False)
