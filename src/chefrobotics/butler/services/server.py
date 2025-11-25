#!/usr/bin/env python3
"""
POST request for new pantry
curl -X PUT http://localhost:5000/pantry/install/r23.14.1
GET install status:
curl -X GET http://localhost:5000/pantry/install

"""
import subprocess
import traceback

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DbSession

from chefrobotics.butler.handlers import HttpRequestHandler
from chefrobotics.butler.routes import jobs_router
from chefrobotics.butler.routes import machine_router
from chefrobotics.butler.utils import db_utils

CLOUD_ALERT_MANAGER_ENDPOINT = (
    "https://alert-manager-prod-mkvp54uf3a-uw.a.run.app"
)
SERVER_PORT = 5042
_pantry_status = {"status": "NEVER_REQUESTED"}

api = FastAPI()
db_engine = db_utils.get_sqlite_db_engine()

origins = [
    "http://localhost:3000",
    "http://localhost:4000",
    "localhost:3000",
    "localhost:4000",
]

api.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def setup_routes():
    api.include_router(jobs_router)
    api.include_router(machine_router)


# DEPRECATED: Use Butler jobs to run pantry commands
def handle_pantry(version, option):
    global _pantry_status
    try:
        # TODO(kyle): fix this for nix
        command = ["/home/chef/.local/bin/pantry", "install", version]
        if option == "dry-run":
            command.append("--dry-run")

        _pantry_status = {"status": "REQUESTED", "version": version}
        subprocess.check_call(command)
        _pantry_status = {"status": "COMPLETED", "version": version}
        return True
    except:
        traceback.print_exc()
        _pantry_status = {"status": "FAILED", "version": version}
        return False


@api.get("/health-check")
@api.head("/health-check")
def health_check():
    return 200


# TODO(Vinny): Implement alert forwarding logic
@api.post("/external-alerts")
async def forward_alert(req: Request):
    """
    Receive information about alerts from the stack and forward to cloud service
    for further processing and forwarding to 3rd party integrations.
    """

    body = await req.json()

    try:
        # Create and buffer HTTP(S) request to cloud alert manager
        job = HttpRequestHandler(
            url=CLOUD_ALERT_MANAGER_ENDPOINT,
            http_method="POST",
            json={
                "alert_message": body["alert_message"],
                "extra_info": body["extra_info"],
            },
        )

        # TODO(Vinny): First attempt then buffer on failure to lower latency
        with DbSession(db_engine) as dbs:
            job.sync(dbs)
        return 200

    except KeyError as e:
        print(f"Received invalid payload, {e}")
        return 422


# DEPRECATED: Use Butler jobs to run pantry commands
@api.put("/pantry/install/{version}")
@api.put("/pantry/install/{version}/{option}")
def pantry_install(version: str, option: str = None):
    _ = handle_pantry(version, option)
    return JSONResponse(_pantry_status)


# DEPRECATED: Use Butler jobs to run pantry commands
@api.get("/pantry/install")
def pantry_status():
    return JSONResponse(_pantry_status)


def main():
    setup_routes()
    uvicorn.run(app=api, host="0.0.0.0", port=SERVER_PORT)


if __name__ == "__main__":
    main()
