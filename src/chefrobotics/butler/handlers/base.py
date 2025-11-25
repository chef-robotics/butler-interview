from __future__ import annotations

import abc
import datetime  # Added import for datetime

import sqlalchemy

from chefrobotics.butler.models.job import ButlerJob
from chefrobotics.butler.models.job import JobStatus

# NOTE: Additional imports at bottom to resolve circular imports


class JobHandler(abc.ABC):
    """
    Handler to managing a single Butler job from start to finish.

    Should not be used directly, subclasses will need to implement their own
    runtime logic in the `start` method.
    """

    @abc.abstractmethod
    def __init__(self, **kwargs):
        pass

    @classmethod
    def from_job(
        cls,
        job: ButlerJob,
    ) -> JobHandler:
        new_handler = cls(**job.context)
        new_handler._job = job
        return new_handler

    def _get_job_from_db(self, db_session) -> ButlerJob:
        return (
            db_session.query(ButlerJob)
            .filter(ButlerJob.job_id == self._job.job_id)
            .one()
        )

    def sync(self, db_session: sqlalchemy.orm.Session):
        try:
            job_instance = self._get_job_from_db(db_session)

        # Create DB row if doesn't exist yet
        except sqlalchemy.exc.NoResultFound:
            db_session.add(self._job)
            db_session.commit()
            job_instance = self._get_job_from_db(db_session)

        job_instance.failure_reason = self._job.failure_reason
        job_instance.status = self._job.status
        job_instance.retry_attempts = self._job.retry_attempts
        job_instance.update_time = datetime.datetime.now(datetime.timezone.utc)
        db_session.commit()
        self._job = job_instance

    # TODO(Vinny): Implement `start` here and make `_start` the abstract method
    @abc.abstractmethod
    def start(self):
        """Begins executing this job and returns once complete"""

    def cancel(self):
        """Cancels a job - may not be implemented by all job types"""

    def get_status(self) -> JobStatus:
        return self._job.status

    def set_status(
        self,
        status: JobStatus,
    ) -> None:
        self._job.status = status.name

    def mark_as_completed(self) -> JobStatus:
        self.set_status(JobStatus.COMPLETED)
        self._job.failure_reason = None
        return self.get_status()

    def mark_as_failed(self, reason: str) -> JobStatus:
        self.set_status(JobStatus.FAILED)
        self._job.failure_reason = reason
        return self.get_status()

    def mark_as_retry(self, reason: str | None = None) -> JobStatus:
        self.set_status(JobStatus.PENDING)
        self._job.retry_attempts += 1
        self._job.failure_reason = reason
        return self.get_status()
