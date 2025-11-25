from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from pydantic import BaseModel
from pydantic import validator
from sqlalchemy.orm import Session as DbSession

from chefrobotics.butler import version
from chefrobotics.butler.models.job import ButlerJob
from chefrobotics.butler.models.job import JobStatus
from chefrobotics.butler.utils.db_manager import DatabaseManager
from chefrobotics.butler.utils.db_utils import get_sqlite_db_engine
from chefrobotics.butler.utils.sync_time_tracker import SyncTimeTracker

# Create router with prefix and tags for API documentation
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])

# Get db engine
db_engine = get_sqlite_db_engine()

# Initialize the database manager
db_manager = DatabaseManager(db_engine)

# Initialize the sync time tracker
sync_tracker = SyncTimeTracker()

# Global lock for the sync endpoint
sync_lock = asyncio.Lock()

CLOUD_API_URL = os.environ.get("CHEF_CONFIG_API_BASE_URI")
MODULE_TAG = os.environ.get("CHEF_MODULE_TAG")
API_SHARED_SECRET = os.environ.get("CHEF_API_SHARED_SECRET")

# Payload size configuration
# 33.55 MB is the maximum request payload size for HTTP requests to Cloud Run
# Reducing this to 10MB to limit the number of jobs that can be pushed at once
MAX_PAYLOAD_SIZE_BYTES = 10 * 1024 * 1024


class JobBase(BaseModel):
    """Base model for job-related operations."""

    job_type: str
    context: Dict[str, Any]
    source: str = "unknown"
    concurrency_locks: Optional[str] = None
    created_by_version: Optional[str] = None

    class Config:
        orm_mode = True
        from_attributes = True


class JobCreate(JobBase):
    """Model for creating new jobs."""


class JobResponse(JobBase):
    """Model for job response data."""

    job_id: str
    status: JobStatus
    failure_reason: Optional[str] = None
    retry_attempts: int
    create_time: datetime
    update_time: datetime
    cancel_requested: bool

    @validator("status", pre=True)
    def validate_status(cls, v: Any) -> JobStatus:
        """Validate and convert status field."""
        if isinstance(v, str):
            try:
                return JobStatus[v]  # Convert string to enum
            except KeyError:
                return JobStatus.PENDING
        elif isinstance(v, int):
            try:
                return JobStatus(v)  # Convert int to enum
            except ValueError:
                return JobStatus.PENDING
        return v  # Already an enum

    class Config:
        orm_mode = True
        from_attributes = True


class JobUpdate(BaseModel):
    """Model for updating job data."""

    # No need for job_id here since its already in the path
    status: Optional[JobStatus] = None
    failure_reason: Optional[str] = None
    retry_attempts: Optional[int] = None
    context: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    concurrency_locks: Optional[str] = None
    created_by_version: Optional[str] = None

    class Config:
        orm_mode = True
        from_attributes = True
        json_encoders = {
            JobStatus: lambda v: v.value  # Convert enum to integer value
        }


class BulkJobUpdate(BaseModel):
    """Model for bulk job update operations."""

    job_id: str
    updates: JobUpdate

    class Config:
        orm_mode = True
        from_attributes = True
        json_encoders = {JobStatus: lambda v: v.value}


def create_job_response(
    job: ButlerJob, include_context: bool = False
) -> JobResponse:
    """
    Create a standardized response using Pydantic model from a ButlerJob object.

    Args:
        job: The ButlerJob instance
        include_context: Whether to include the context field in the response

    Returns:
        JobResponse model containing formatted job data
    """
    # Change to model_validate when upgrading pydantic to v2
    response = JobResponse.from_orm(job)

    if not include_context:
        response.context = {}

    return response


@jobs_router.post("/")
def create_jobs(jobs: List[JobCreate]) -> List[JobResponse]:
    """
    Create one or more new jobs.

    Args:
        jobs: List of jobs to create, each with job_type and context.

    Returns:
        A list of created job records with their IDs and other fields.
    """

    def create_jobs_transaction(session: DbSession) -> List[JobResponse]:
        created_jobs_data = []
        for job_data in jobs:
            job = ButlerJob(
                job_type=job_data.job_type,
                context=job_data.context,
                source=job_data.source,
                concurrency_locks=job_data.concurrency_locks,
                created_by_version=job_data.created_by_version,
            )
            session.add(job)
            session.flush()  # Required to get the job_id
            created_jobs_data.append(
                create_job_response(job, include_context=True)
            )
        return created_jobs_data

    return db_manager.execute_transaction(create_jobs_transaction)


@jobs_router.get("/{job_id}")
def get_job(job_id: str) -> JobResponse:
    """
    Get a specific job by its ID

    Args:
        job_id: The unique identifier of the job

    Raises:
        HTTPException(404): If job is not found
    """

    def get_job_query(session: DbSession) -> JobResponse:
        job = (
            session.query(ButlerJob).filter(ButlerJob.job_id == job_id).first()
        )
        if job is None:
            raise HTTPException(
                status_code=404, detail=f"Job {job_id} not found"
            )
        return create_job_response(job, include_context=True)

    return db_manager.execute_query(get_job_query)


@jobs_router.put("/{job_id}/cancel")
def cancel_job(job_id: str) -> JobResponse:
    """
    Cancel a specific job by its ID

    Args:
        job_id: The unique identifier of the job

    Raises:
        HTTPException(404): If job is not found
    """

    def get_job_query(session: DbSession) -> JobResponse:
        job = (
            session.query(ButlerJob).filter(ButlerJob.job_id == job_id).first()
        )
        if job is None:
            raise HTTPException(
                status_code=404, detail=f"Job {job_id} not found"
            )

        job.cancel_requested = True

        return create_job_response(job, include_context=True)

    return db_manager.execute_query(get_job_query)


@jobs_router.get("")
def get_jobs(
    since: Optional[float] = Query(
        None, description="Unix timestamp to filter jobs updated since"
    ),
) -> List[JobResponse]:
    """
    Get jobs, optionally filtered by update time

    Args:
        since: Optional Unix timestamp (seconds since epoch). If provided,
               only returns jobs updated after this time.
    """

    def get_jobs_query(session: DbSession) -> List[JobResponse]:
        query = session.query(ButlerJob).order_by(ButlerJob.update_time.desc())

        if since is not None:
            since_dt = datetime.fromtimestamp(since)
            query = query.filter(ButlerJob.update_time >= since_dt)

        jobs = query.all()
        # not including context for now to keep the response manageable
        return [create_job_response(job, include_context=False) for job in jobs]

    return db_manager.execute_query(get_jobs_query)


@jobs_router.patch("/{job_id}")
def update_job(job_id: str, job_update: JobUpdate) -> JobResponse:
    """
    Update a specific job by its ID

    Args:
        job_id: The unique identifier of the job
        job_update: The fields to update

    Raises:
        HTTPException(404): If job is not found
    """

    def update_job_transaction(session: DbSession) -> JobResponse:
        job = (
            session.query(ButlerJob).filter(ButlerJob.job_id == job_id).first()
        )
        if job is None:
            raise HTTPException(
                status_code=404, detail=f"Job {job_id} not found"
            )

        update_data = job_update.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(job, key, value)

        return create_job_response(job, include_context=True)

    return db_manager.execute_transaction(update_job_transaction)


@jobs_router.patch("")
def update_jobs(updates: List[BulkJobUpdate]) -> List[JobResponse]:
    """
    Update multiple jobs in bulk

    Args:
        updates: List of job updates, each containing job_id and fields to update

    Returns:
        List of updated job records

    """

    def update_jobs_transaction(session: DbSession) -> List[JobResponse]:
        updated_jobs = []
        for job_update in updates:
            job = (
                session.query(ButlerJob)
                .filter(ButlerJob.job_id == job_update.job_id)
                .first()
            )

            if job is not None:
                update_data = job_update.updates.dict(exclude_unset=True)
                for key, value in update_data.items():
                    setattr(job, key, value)
                updated_jobs.append(
                    create_job_response(job, include_context=True)
                )

        return updated_jobs

    return db_manager.execute_transaction(update_jobs_transaction)


def pull_jobs_from_cloud_transaction(
    session: DbSession, cloud_jobs: List[dict]
) -> List[JobResponse]:
    """
    Process jobs pulled from cloud and update local butler_db.

    Args:
        session: Database session
        cloud_jobs: List of job data from cloud

    Returns:
        List of processed job responses
    """
    synced_jobs = []
    updated_count = 0
    created_count = 0

    # Get the valid column names from ButlerJob model
    valid_columns = ButlerJob.__table__.columns.keys()

    for cloud_job in cloud_jobs:
        # Filter out any fields that don't exist in ButlerJob model
        filtered_job_data = {
            k: v for k, v in cloud_job.items() if k in valid_columns
        }

        # Handle status as numeric enum value
        if "status" in filtered_job_data:
            if isinstance(filtered_job_data["status"], int):
                try:
                    filtered_job_data["status"] = JobStatus(
                        filtered_job_data["status"]
                    ).name
                except ValueError:
                    filtered_job_data["status"] = JobStatus.FAILED.name
            elif isinstance(filtered_job_data["status"], str):
                try:
                    filtered_job_data["status"] = JobStatus[
                        filtered_job_data["status"]
                    ].name
                except KeyError:
                    filtered_job_data["status"] = JobStatus.PENDING.name

        # Convert datetime strings to datetime objects
        if "create_time" in filtered_job_data:
            filtered_job_data["create_time"] = datetime.fromisoformat(
                filtered_job_data["create_time"].replace("Z", "+00:00")
            )
        if "update_time" in filtered_job_data:
            filtered_job_data["update_time"] = datetime.fromisoformat(
                filtered_job_data["update_time"].replace("Z", "+00:00")
            )

        # Check if job already exists
        local_job = (
            session.query(ButlerJob)
            .filter(ButlerJob.job_id == cloud_job["job_id"])
            .first()
        )

        if local_job:
            # Update existing job
            if local_job.status == JobStatus.COMPLETED.name:
                print("Ignoring completed job: ", local_job.job_id)
                print("Completed job update_time: ", local_job.update_time)
                continue

            # TODO(vinny): Implement job cancellation here
            # TODO(kyle): how would one implement cancellation here - is the intent that the row is removed?
            print("local_job.update_time: ", local_job.update_time)
            print(
                "filtered_job_data['update_time']: ",
                filtered_job_data["update_time"],
            )

            # Convert local_job.update_time to UTC aware datetime if it's naive
            local_update_time = local_job.update_time
            if local_update_time.tzinfo is None:
                local_update_time = local_update_time.replace(
                    tzinfo=timezone.utc
                )

            # Ensure filtered_job_data's update_time is timezone aware
            cloud_update_time = filtered_job_data["update_time"]
            if cloud_update_time.tzinfo is None:
                cloud_update_time = cloud_update_time.replace(
                    tzinfo=timezone.utc
                )

            if local_update_time >= cloud_update_time:
                print(
                    "Ignoring job with older or equal update time: ",
                    local_job.job_id,
                )
                continue

            for key, value in filtered_job_data.items():
                if key != "job_id":
                    setattr(local_job, key, value)
            job = local_job
            updated_count += 1
        else:
            # Create new job
            job = ButlerJob(**filtered_job_data)
            session.add(job)
            created_count += 1

        synced_jobs.append(create_job_response(job, include_context=True))

    # Use the global sync_tracker here instead of passing it in
    sync_tracker.update_pull_sync_time(int(time.time()))

    return synced_jobs


def get_jobs_to_push_transaction(
    session: DbSession, last_push: int
) -> List[ButlerJob]:
    """
    Get jobs that have been updated since the last push sync.

    Args:
        session: Database session
        last_push: Unix timestamp of last push sync

    Returns:
        List of jobs that need to be pushed to the cloud
    """
    last_push_dt = datetime.fromtimestamp(last_push, tz=timezone.utc)
    print("Using last push time: ", last_push_dt, type(last_push_dt))
    return (
        session.query(ButlerJob)
        .filter(ButlerJob.update_time >= last_push_dt)
        .order_by(ButlerJob.update_time.asc())
        .all()
    )


def estimate_json_size(data: Any) -> int:
    """Estimate the JSON size of data in bytes."""
    return len(json.dumps(data, separators=(",", ":")).encode("utf-8"))


def create_size_based_batches(
    job_updates: List[dict],
    max_size_bytes: int,
    job_update_times: List[datetime],
) -> tuple[List[List[dict]], List[datetime]]:
    """
    Create batches of job updates based on max payload size.

    Args:
        job_updates: List of job update dictionaries to be batched. Each dict should
            contain job data in the format expected by the cloud PATCH endpoint.
        max_size_bytes: Maximum allowed size in bytes for each batch payload.
        job_update_times: List of datetime objects corresponding to each job's
            update_time, used for tracking batch timestamps.

    Returns:
        A tuple containing:
            - batches (List[List[dict]]): List of job update batches, where each batch
              is a list of job update dictionaries that fit within the size limit.
            - batch_update_times (List[datetime]): List of datetime objects representing
              the latest update_time for each corresponding batch.
    """
    if not job_updates:
        return [], []

    batches = []
    current_batch = []
    current_size_bytes = 0
    batch_update_time = []

    # Account for JSON array overhead: [] brackets
    base_overhead_bytes = 2

    for i, job_update in enumerate(job_updates):
        job_size_bytes = estimate_json_size(job_update)

        # Skip jobs that are individually larger than max size limit
        if job_size_bytes + base_overhead_bytes > max_size_bytes:
            print(
                f"Job {job_update.get('job_id', '<unknown>')} exceeds max batch size "
                f"({job_size_bytes} bytes) and will not be synced with cloud"
            )
            continue

        # Calculate size with comma separator if not first item
        separator_size_bytes = 1 if current_batch else 0
        total_size_bytes_with_job = (
            current_size_bytes
            + job_size_bytes
            + separator_size_bytes
            + base_overhead_bytes
        )

        if current_batch and total_size_bytes_with_job > max_size_bytes:
            batches.append(current_batch)
            batch_update_time.append(job_update_times[i - 1])
            current_batch = [job_update]
            current_size_bytes = job_size_bytes
        else:
            current_batch.append(job_update)
            current_size_bytes += job_size_bytes + separator_size_bytes

    # case for the last batch
    if current_batch:
        batches.append(current_batch)
        batch_update_time.append(job_update_times[-1])

    return batches, batch_update_time


async def push_job_updates_in_batches(
    job_updates: List[dict], sync_tracker: Any, job_update_times: List[datetime]
) -> List[str]:
    """
    Push job updates to cloud in size-based batches.

    Args:
        job_updates: List of job update dictionaries to push to the cloud API.
            Each dictionary should contain the following schema:

        sync_tracker: Sync tracker instance used to update push sync timestamps
            after successful batch operations.
        job_update_times: List of datetime objects corresponding to each job's
            update_time, used for tracking batch progression.

    Returns:
        List of successfully pushed job IDs as strings. Each ID corresponds to
        a job that was successfully synchronized to the cloud.

    Raises:
        HTTPException: If any batch fails during the push operation. The exception
            will contain details about which batch failed and the specific error.
    """
    if not job_updates:
        return []

    # Calculate total payload size
    total_payload_size_bytes = estimate_json_size(job_updates)
    total_payload_size_mb = total_payload_size_bytes / 1024 / 1024
    print(
        f"Total payload size: {total_payload_size_bytes:,} bytes "
        f"({total_payload_size_mb:.2f} MB)"
    )

    # Create size-based batches
    batches, batch_update_time = create_size_based_batches(
        job_updates, MAX_PAYLOAD_SIZE_BYTES, job_update_times
    )
    print(
        f"Split {len(job_updates)} job updates into {len(batches)} size-based batches"
    )

    pushed_job_ids = []

    async with httpx.AsyncClient() as client:
        for batch_num, batch in enumerate(batches, 1):
            batch_size_bytes = estimate_json_size(batch)
            batch_size_mb = batch_size_bytes / 1024 / 1024
            print(
                f"Pushing batch {batch_num}/{len(batches)}: {len(batch)} jobs, "
                f"{batch_size_bytes:,} bytes ({batch_size_mb:.2f} MB)"
            )

            try:
                response = await client.patch(
                    f"{CLOUD_API_URL}/jobs",
                    json=batch,
                    headers={"X-ChefSharedSecret": API_SHARED_SECRET},
                    timeout=10.0,
                )
                response.raise_for_status()

                batch_pushed_ids = response.json()
                pushed_job_ids.extend(batch_pushed_ids)
                print(
                    f"Batch {batch_num} success: {len(batch_pushed_ids)} jobs pushed"
                )

                # Update sync time after each successful batch
                batch_datetime = batch_update_time[batch_num - 1]
                # Ensure datetime is treated as UTC for timestamp conversion
                if batch_datetime.tzinfo is None:
                    batch_datetime = batch_datetime.replace(tzinfo=timezone.utc)
                batch_timestamp = int(batch_datetime.timestamp())
                print("Updating push sync time to: ", batch_timestamp)
                sync_tracker.update_push_sync_time(batch_timestamp)
                print(f"Push sync time updated after batch {batch_num}")

            except Exception as batch_error:
                error_msg = (
                    f"Batch {batch_num}/{len(batches)} failed: {batch_error}"
                )
                print(f"ERROR: {error_msg}")
                traceback.print_exc()
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to push job updates - {error_msg}",
                )

    print(
        f"Successfully pushed all {len(pushed_job_ids)} jobs in {len(batches)} batches"
    )
    return pushed_job_ids


@jobs_router.post("/sync")
async def sync_jobs() -> Dict[str, Any]:
    """
    Synchronize jobs between local butler database and cloud API.

    This endpoint performs bidirectional synchronization:
    1. PULL: Fetches new jobs from cloud API since last pull sync
    2. PUSH: Uploads local job updates to cloud API using size-based batching

    The sync operation is protected by a lock to prevent concurrent executions.
    Job updates are sent in intelligent batches to avoid payload size limits.

    Returns:
        A dictionary containing sync operation results with the following schema:
        {
            "pulled_jobs": int,        # Number of jobs pulled from cloud
            "pushed_jobs": int,        # Number of jobs pushed to cloud
            "sync_time": str          # ISO timestamp of sync completion
        }

    """
    if sync_lock.locked():
        raise HTTPException(
            status_code=423,
            detail="Sync operation already in progress. Please try again later.",
        )

    async with sync_lock:
        try:
            # PULL: Get the latest jobs from the cloud and add to edge db
            last_pull = sync_tracker.get_pull_sync_time()
            pulled_jobs = []
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{CLOUD_API_URL}/jobs",
                    params={
                        "m": MODULE_TAG,
                        "since": int(last_pull) if int(last_pull) > 0 else 0,
                    },
                    headers={"X-ChefSharedSecret": API_SHARED_SECRET},
                    timeout=60.0,
                )
                response.raise_for_status()
                cloud_jobs = response.json()

            pulled_jobs = db_manager.execute_transaction(
                lambda session: pull_jobs_from_cloud_transaction(
                    session, cloud_jobs
                )
            )

            # PUSH: Get local job updates since last push and send to cloud
            last_push = sync_tracker.get_push_sync_time()
            jobs_to_push = db_manager.execute_query(
                lambda session: get_jobs_to_push_transaction(session, last_push)
            )

            job_update_times = []
            pushed_job_ids = []

            if jobs_to_push:
                job_updates = []
                for job in jobs_to_push:
                    # Format according to JobUpdateRequest model
                    job_update = {
                        "job_id": job.job_id,
                        "module_tag": MODULE_TAG,
                        "job_type": job.job_type,
                        "source": job.source,
                        "status": JobStatus[job.status].value,
                        "retry_attempts": job.retry_attempts,
                        "context": job.context,
                        "updated_by": f"[M] {MODULE_TAG}",
                    }
                    job_update_times.append(job.update_time)
                    # TODO(vinny): Remove this once we no longer have jobs that
                    # don't have a created_by
                    # if job:
                    # job_update["created_by"] = f"[M] {MODULE_TAG}"
                    if job.created_by_version is None:
                        job_update["created_by_version"] = version.__version__
                    job_updates.append(job_update)
                # Push job updates to cloud using size-based batching
                pushed_job_ids = await push_job_updates_in_batches(
                    job_updates, sync_tracker, job_update_times
                )

            return {
                "pulled_jobs": len(pulled_jobs),
                "pushed_jobs": len(pushed_job_ids),
                "sync_time": datetime.now().isoformat(),
            }
        except httpx.RequestError as e:
            error_msg = f"Failed to connect to cloud jobs API: {str(e)}"
            raise HTTPException(status_code=503, detail=error_msg)
        except Exception as e:
            error_msg = (
                f"Failed to sync jobs: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            raise HTTPException(status_code=500, detail=error_msg)
