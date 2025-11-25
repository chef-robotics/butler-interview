from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import traceback
from copy import deepcopy

import pexpect
from sqlalchemy.orm import Session as DbSession

from chefrobotics.butler.exceptions import RetryableError
from chefrobotics.butler.handlers import base
from chefrobotics.butler.handlers.base import ButlerJob
from chefrobotics.butler.models.job import JobStatus
from chefrobotics.butler.utils import db_utils


MODULE_TAG = os.environ["CHEF_MODULE_TAG"]
RECORDING_DIR = "/var/tmp/chef/recordings"


class LongCommandHandler(base.JobHandler):
    """Handler for executing long-running commands"""

    max_attempts = 2

    def __init__(
        self,
        command: list[str],
        source: str = "unknown",
        _job: ButlerJob | None = None,
        **context,
    ):
        # command is expected to be a list of string
        # e.g. ["ls", "-l", "/home/chef"]
        self._command = command
        self._context = context
        self._source = source
        self._job = _job or self._create_job()

    def _create_job(self) -> ButlerJob:
        return ButlerJob(
            job_type="LongCommand",
            context={
                "command": self._command,
                "output_file": None,
                **self._context,
            },
            source=self._source,
        )

    def _update_job_status(
        self, engine, status: JobStatus, failure_reason: str | None = None
    ):
        """Helper method to update the job status and failure_reason.

        Args:
            engine: SQLAlchemy engine instance
            status: JobStatus enum value to set
            failure_reason: Optional error message if job failed
        """
        if failure_reason:
            print(failure_reason)
        with DbSession(engine) as dbs:
            self._job.status = status.name
            self._job.failure_reason = failure_reason
            dbs.merge(self._job)
            dbs.commit()

    # TODO(vinny): Centralize this logic for shared use in Butler and use a
    #              helper function shared with autonomy for marking for upload
    def _mark_log_file_for_upload(self, log_file: str):
        """Upload the log file to the Butler server"""
        if not os.path.exists(log_file) or not os.path.isfile(log_file):
            return

        dest_file = os.path.join(RECORDING_DIR, os.path.basename(log_file))

        # Move the log file to recording dir + mark for upload
        shutil.move(src=log_file, dst=dest_file)
        upload_info = {
            "priority": 0,
            "moduleTag": MODULE_TAG,
            "category": "butler-job-log",
            "file_category": "butler-job-log",
            "createTime": time.time(),
        }
        with open(f"{dest_file}.to_upload.json", "w") as f:
            json.dump(upload_info, f, indent=2)

    def _start(self):
        """Execute the long-running command and pipe output to temp file"""
        job_id = str(self._job.job_id)
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f"butler_{job_id}.log")

        try:
            with open(output_file, mode="w") as tmp:
                self._context["log_file"] = output_file

                # Update job context with output file location
                engine = db_utils.get_sqlite_db_engine()
                self._update_job_status(engine, JobStatus.IN_PROGRESS)

                # Create a copy of the current environment
                # TODO(vinny): Consider limiting this env to what the job needs
                shell_env = os.environ.copy()

                # Spawn the process with TTY, logging to file, and block to
                # to completion without timing out
                # TODO(vinny): Add support for user-specified timeout
                child = pexpect.spawn(
                    command=self._command[0],
                    args=self._command[1:],
                    encoding="utf-8",
                    env=shell_env,
                    timeout=None,
                )
                child.logfile_read = tmp
                child.expect(pexpect.EOF)
                child.close()
                exit_status = child.exitstatus

                if exit_status != 0:
                    raise subprocess.CalledProcessError(
                        returncode=exit_status, cmd=self._command
                    )

                # Job has completed successfully, update status
                self._update_job_status(engine, JobStatus.COMPLETED)

        except subprocess.CalledProcessError as e:
            try:
                # Attempt to read tail of log file to pass error context
                output = subprocess.check_output(
                    ["tail", "-50", output_file], text=True
                )
            except Exception as read_error:
                output = f"<Error reading output file: {str(read_error)}>"

            error_msg = (
                f"Command failed with exit code {e.returncode}: {output}"
            )
            self._update_job_status(engine, JobStatus.FAILED, error_msg)
            raise RetryableError(error_msg)

        except Exception as e:
            error_msg = f"Unexpected error during command execution: {str(e)}\n{traceback.format_exc()}"
            self._update_job_status(engine, JobStatus.FAILED, error_msg)
            raise RuntimeError(error_msg)

        finally:
            try:
                self._mark_log_file_for_upload(output_file)
            except Exception as e:
                print(f"Failed to mark log file for upload: {e}")

    def start(self) -> None:
        self._start()

    @classmethod
    def from_job(cls, job_instance: ButlerJob):
        context = deepcopy(job_instance.context)
        command = context.pop("command", ["false"])
        handler = cls(command=command, _job=job_instance, **context)
        return handler
