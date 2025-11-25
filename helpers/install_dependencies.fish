#!/usr/bin/env fish
# Installs chef butler dependencies

source (dirname (status -f))/../../lib/utils.fish
set -l base $CHEF_EDGE/butler

argparse --name=install_butler_dependencies \
    v/version= \
    -- $argv
and set -q _flag_version
or begin
  logerr "Usage: install_dependencies.fish --version <version>"
  exit 1
end

checked wait-for-dpkg-lock

# TODO(vinny): Consolidate all edge apt installs into singular step
checked apt-install sqlite3

# TODO(kyle): switch to uv, properly pin our repos using gcp keys
set -l pip_args --upgrade-strategy=only-if-needed \
                "chefrobotics-butler==$_flag_version"

if not python3.7 -m pip install $pip_args
    # Fall back to full reinstall if first attempt fails
    logerr "Initial install failed, retrying without cache..."
    checked python3.7 -m pip install \
        --force-reinstall \
        --no-cache-dir \
        --verbose \
        $pip_args
end

# Setup Butler DB in the case does not exist
checked sudo mkdir -p /var/lib/chef/
checked sudo chmod g+w /var/lib/chef/
checked sudo chgrp chef /var/lib/chef/
checked butler-db-migrate
