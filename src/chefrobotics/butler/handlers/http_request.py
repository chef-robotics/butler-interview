from __future__ import annotations

import inspect

import requests
from sqlalchemy.orm import Session as DbSession

from chefrobotics.butler.exceptions import InternetDisconnectedError
from chefrobotics.butler.exceptions import RetryableError
from chefrobotics.butler.handlers import base
from chefrobotics.butler.handlers.base import ButlerJob
from chefrobotics.butler.models.job import JobStatus
from chefrobotics.butler.utils import db_utils


class HttpRequestHandler(base.JobHandler):

    max_attempts = 5
    request_timeout_s = 10

    def __init__(
        self,
        url: str,
        http_method: str,
        _job: ButlerJob | None = None,
        **context,
    ):
        self._url = url
        self._http_method = http_method
        self._request_kwargs = context
        self._job = _job or self._create_job()

    def _create_job(self) -> ButlerJob:
        return ButlerJob(
            job_type="HttpRequest",
            context={
                "http_method": self._http_method,
                "url": self._url,
                **self._request_kwargs,
            },
        )

    def queue(self):
        job_row = self._create_job()
        engine = db_utils.get_sqlite_db_engine()
        with DbSession(engine) as dbs:
            dbs.add(job_row)
            dbs.commit()

    @classmethod
    def from_job(cls, job_instance: ButlerJob):
        context = job_instance.context
        url = context.pop("url")
        method = context.pop("http_method")
        handler = cls(url=url, http_method=method, _job=job_instance, **context)
        return handler

    def _start(self):
        request_kwargs = {
            arg: self._request_kwargs.get(arg)
            for arg in ("data", "headers", "json")
        }

        # Get HTTP method-specific requests function
        req_callable = getattr(requests, self._http_method.lower())
        filtered_kwargs = {
            k: v
            for k, v in request_kwargs.items()
            if k in inspect.signature(req_callable).parameters
        }

        # Make the actual API request
        try:
            response = req_callable(
                url=self._url, timeout=self.request_timeout_s, **filtered_kwargs
            )
        except requests.ConnectionError as e:
            raise InternetDisconnectedError(e)
        except (
            requests.HTTPError,
            requests.Timeout,
            requests.TooManyRedirects,
        ) as e:
            # Retry the request later if failed due to possibly intermittent issue
            raise RetryableError(e)

    def start(self) -> None:
        """Make single HTTP(S) request and handle exceptions"""
        self._start()
