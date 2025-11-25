#!/usr/bin/env bash

# Build and Push `chefrobotics-butler`
# ===================================
#
# REQUIREMENTS:
#   - Python 3.8 or higher (required by build dependencies)
#   - gcloud CLI authenticated for artifact registry access
#
# DESCRIPTION:
#   Builds a Python wheel using setuptools and uploads it to Chef Robotics
#   artifact registry. Automatically creates and manages a virtual environment.
#
# USAGE:
#   ./build_and_push_wheel.sh

set -e

BASE_DIR="$(dirname $0)"
VENV_DIR="$BASE_DIR/venv"

PYTHON_CMD=$(python3 -c "import sys; print('python%d.%d' % (sys.version_info[:2]))")

# Check if butler venv exists, offer to create it if not
if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found at $VENV_DIR"
    read -p "Would you like to create a new virtual environment? (y/N): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborting. Please create a virtual environment manually."
        exit 1
    fi

    # Check if python3 -m venv is available
    if ! python3 -m venv --help >/dev/null 2>&1; then
        echo "$PYTHON_CMD-venv not found."

        # Check if we're on Linux to use apt-get
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            echo "Installing $PYTHON_CMD-venv..."
            sudo apt-get update
            sudo apt-get install -y $PYTHON_CMD-venv
        else
            echo "Error: $PYTHON_CMD -m venv is not available on this system."
            exit 1
        fi
    fi

    # Create venv with custom prompt
    echo "Creating virtual environment with 'butler' prompt..."
    python3 -m venv --prompt="butler" "$VENV_DIR"
    echo "Virtual environment created at $VENV_DIR"
fi

source $BASE_DIR/venv/bin/activate
rm -rf \
    $BASE_DIR/src/dist/ \
    $BASE_DIR/src/build/ \
    $BASE_DIR/src/*.egg-info/

# Versions of build + twine are pinned for compat with lowest non-EOL Python 3
python3 -m pip install --upgrade pip
python3 -m pip install --upgrade \
    setuptools==68.2.2 \
    twine==5.1.1 \
    wheel==0.42.0

cd $BASE_DIR/src
python3 setup.py bdist_wheel --universal
python3 -m twine upload \
    --username oauth2accesstoken \
    --password $(gcloud auth print-access-token) \
    --repository-url https://us-python.pkg.dev/chef-robotics-infra/releases-prod-python-us/ \
    --verbose \
    dist/*.whl
deactivate
