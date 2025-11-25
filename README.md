# Butler

Daemon for handling requests for a robot.

## Installation

### On Robot

It's automatic, through `pantry`

### Local Testing

```
uv venv --python 3.8
source .venv/bin/activate
uv pip install -e src

export CHEF_BUTLER_DB_DIR=/tmp
export CHEF_MODULE_TAG=test
# Setup butler
.venv/bin/butler-db-migrate
# Run the HTTP server in the background
# TODO(kyle): use the uvicorn command that allows for autoreload
.venv/bin/butler-server&
# Run the job dispatcher in the foreground
.venv/bin/butler-dispatcher

# A test command
curl -X POST localhost:5042/jobs/ \
  -H "Content-Type: application/json" \
  --data '[{
    "job_type": "LongCommand",
    "context": { "command": ["sleep", "60"] },
    "output_file": "/tmp/cmd.log"
  }]'

# List all jobs
curl -X GET localhost:5042/jobs

# An example of getting the status of one job
curl -X GET localhost:5042/jobs/862a1146-57b1-43f0-8593-28333ffe78cb

# Cancel a job
# TODO: implemented in the db but not on the job dispatcher
curl -X POST localhost:5042/0b450193-bde1-4eca-9d79-e982ef59a358/cancel
```
