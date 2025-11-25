#!/usr/bin/env python3
import asyncio
import random
import subprocess
import sys
import threading
import time
import traceback

import httpx
from sqlalchemy import update
from sqlalchemy.orm import Session as DbSession

from chefrobotics.butler import handlers
from chefrobotics.butler.exceptions import InternetDisconnectedError
from chefrobotics.butler.exceptions import RetryableError
from chefrobotics.butler.models.job import ButlerJob
from chefrobotics.butler.models.job import JobStatus
from chefrobotics.butler.utils import db_utils

# Use both Cloudflare and Google for redundancy
INTERNET_CHECK_HOSTS = (
    "1.0.0.1",
    "1.1.1.1",
    "8.8.4.4",
    "8.8.8.8",
)

JOB_QUEUE_POLL_PERIOD_S = 10
JOB_SYNC_PERIOD_S = 60
JOB_SYNC_TIMEOUT_S = 600
MAX_JOB_QUEUE_SIZE = 1000

BUTLER_API_URL = "http://localhost:5042"

# Global state to track internet status
_g_connected_to_internet = False


def load_jobs_onto_queue() -> list:
    """
    Fetch all `PENDING` jobs from the database and repopulate queue in the order
    of when the jobs were created.
    """
    engine = db_utils.get_sqlite_db_engine()

    # Wipe and re-populate job queue
    with DbSession(engine) as dbs:
        job_queue = (
            dbs.query(ButlerJob)
            .filter(ButlerJob.status == JobStatus.PENDING.name)
            .order_by(ButlerJob.create_time)
            .limit(MAX_JOB_QUEUE_SIZE)
            .all()
        )

        # Preview the next three jobs to be run
        print(
            "Next 3 Jobs:",
            [
                f"{j.job_type} ({j.job_id[:8]})"
                for j in job_queue[: min(3, len(job_queue))]
            ],
        )
        return job_queue


def wait_for_internet_connection(retry_period_s: int = 1):
    """Block until module is connected to the internet"""
    global _g_connected_to_internet
    _g_connected_to_internet = False

    while not _g_connected_to_internet:
        exit_code = subprocess.call(
            ("ping", "-c1", "-t50", random.choice(INTERNET_CHECK_HOSTS)),
            stdout=subprocess.DEVNULL,
        )
        if exit_code == 0:
            _g_connected_to_internet = True
            print("Internet connection found, starting job queue")
            return
        time.sleep(retry_period_s)


def sync_jobs_periodically(stop_event):
    """Background thread that periodically syncs jobs with the cloud."""
    while not stop_event.is_set():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                response = loop.run_until_complete(
                    httpx.AsyncClient().post(
                        BUTLER_API_URL + "/jobs/sync",
                        headers={"Content-Type": "application/json"},
                        timeout=JOB_SYNC_TIMEOUT_S,
                    )
                )

                if response.status_code == 200:
                    print(f"Job sync successful: {response.json()}")
                else:
                    print(
                        f"Job sync failed with status {response.status_code}: {response.text}"
                    )
            finally:
                loop.close()

        except Exception as e:
            print(f"Error during job sync: {e}")
            traceback.print_exc()

        stop_event.wait(timeout=JOB_SYNC_PERIOD_S)

    print("Job sync thread shutting down gracefully")


# TODO(Vinny): Consider sharing this logic with Uploader or handling uploads
#              via Butler jobs once multiprocessing is in place
def main(*args):
    global _g_connected_to_internet
    job_queue = []
    last_fetch_time = 0

    job_sync_stop_event = threading.Event()
    sync_thread = threading.Thread(
        target=sync_jobs_periodically, args=(job_sync_stop_event,), daemon=False
    )
    sync_thread.start()
    print(f"Job sync thread started: {sync_thread.is_alive()}")

    try:
        # Always run dispatcher
        while True:

            wait_for_internet_connection()

            # Main loop to process jobs periodically as long as we're connected
            while _g_connected_to_internet:
                # Update queue if job polling period has passed
                if time.time() - last_fetch_time >= JOB_QUEUE_POLL_PERIOD_S:
                    job_queue = load_jobs_onto_queue()
                    last_fetch_time = time.time()

                # If no work to do, wait before polling for jobs agains
                if not job_queue:
                    time.sleep(
                        JOB_QUEUE_POLL_PERIOD_S
                        - (time.time() - last_fetch_time)
                    )
                    continue

                # Process the next job on queue
                try:
                    active_job = job_queue.pop(0)
                    job_handler_name = active_job.job_type + "Handler"

                    # TODO(Vinny/Luis): Use multiprocessing or threading here
                    # Run single job and block till completion or failure
                    with DbSession(db_utils.get_sqlite_db_engine()) as dbs:
                        if not hasattr(handlers, job_handler_name):
                            dbs.execute(
                                update(ButlerJob)
                                .where(ButlerJob.job_id == active_job.job_id)
                                .values(
                                    status=JobStatus.FAILED.name,
                                    failure_reason=f"Invalid job handler `{job_handler_name}`",
                                )
                            )
                            dbs.commit()
                            continue

                        # TODO(Vinny): Use a handler registry instead of `getattr()`

                        try:
                            job_handler = getattr(
                                handlers, job_handler_name
                            ).from_job(active_job)
                            job_handler.start()
                            job_handler.mark_as_completed()
                        except InternetDisconnectedError as e:
                            raise e
                        except RetryableError as e:
                            if (
                                job_handler._job.retry_attempts
                                > job_handler.max_attempts
                            ):
                                job_handler.mark_as_failed(
                                    f"Max retries for {job_handler.__class__.__name__}, "
                                    f"Traceback: {traceback.format_exc()}"
                                )
                            else:
                                job_handler.mark_as_retry(
                                    f"Retryable failure due to {e}. "
                                    f"Traceback: {traceback.format_exc()}"
                                )
                        except Exception as e:
                            job_handler.mark_as_failed(
                                f"Failed due to {e}. Traceback: {traceback.format_exc()}"
                            )
                        finally:
                            print(job_handler._job.job_id)
                            job_handler.sync(dbs)

                        print(
                            job_handler.get_status(),
                            active_job.job_type,
                            active_job.job_id,
                        )

                # Internet disconnected during handling of job, wait until connected
                # then resume processing
                # TODO(Vinny/Luis): Do not block all, allow offline jobs to proceed
                except InternetDisconnectedError as e:
                    print("Internet disconnect detected, stopping job queue")
                    _g_connected_to_internet = False
                    break

                # Uncaught exception, dump traceback
                # TODO(Vinny): Mark job as failed or bump retry count so one bad job
                #              does not create a blockage in the queue
                except Exception as e:
                    print(traceback.format_exc())

    except (KeyboardInterrupt, SystemExit):
        print("Shutdown requested - Stopping job sync thread")

    finally:
        job_sync_stop_event.set()
        sync_thread.join()
        print("Background thread terminated. Bye!")


if __name__ == "__main__":
    main(sys.argv[1:])
