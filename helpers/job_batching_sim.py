#!/usr/bin/env python3
"""
Simple test script for Butler job batching.

Usage examples:
  # Normal batching test
  python3 test_job_batching.py -c 100 -s 50

"""

import argparse
import json
import time
from typing import List
from typing import TypedDict

import requests


class CreatedJob(TypedDict):
    job_id: str


def create_jobs(
    count: int, size_kb: int, url: str = "http://localhost:5042"
) -> List[CreatedJob]:
    """Create test jobs with specified count and size."""
    padding = "x" * (size_kb * 1024 - 100)
    jobs = [
        {
            "job_type": "test_noop",
            "context": {
                "test_id": f"test_{time.time()}_{i}",
                "padding": padding,
                "index": i,
            },
            "source": "batch_test",
        }
        for i in range(count)
    ]

    response = requests.post(f"{url}/jobs/", json=jobs)
    response.raise_for_status()

    total_size = len(json.dumps(jobs).encode())
    print(f"Created {count} jobs, {total_size/1024/1024:.1f}MB total")
    return response.json()


def trigger_sync(url: str = "http://localhost:5042") -> dict:
    """Trigger job sync."""
    response = requests.post(f"{url}/jobs/sync")
    response.raise_for_status()
    result = response.json()
    print(
        f"Sync: {result['pushed_jobs']} pushed, {result['pulled_jobs']} pulled"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--count", type=int, default=10, help="Job count")
    parser.add_argument(
        "-s", "--size", type=int, default=1, help="Job size in KB"
    )
    parser.add_argument("--no-sync", action="store_true", help="Skip sync")
    args = parser.parse_args()

    print(f"Creating {args.count} jobs ({args.size}KB each)")
    create_jobs(args.count, args.size)

    if not args.no_sync:
        trigger_sync()
