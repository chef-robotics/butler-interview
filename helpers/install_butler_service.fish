#!/usr/bin/env fish
# Installs chef butler as a service.

source $CHEF_EDGE/lib/utils.fish

set -l base $CHEF_EDGE/butler
set -l butler_services chef_butler_dispatcher chef_butler_restapi

argparse 'u/uninstall' 'n/no-restart' -- $argv

if set -q _flag_uninstall
  echo "Uninstall Chef Butler"

  sudo systemctl stop $butler_services
  sudo systemctl disable $butler_services
  sudo systemctl daemon-reload

  chef-uninstall bin/butler/
else
  chef-install $base/ bin/
  # Symlink the Butler entrypoints to /opt/chef/bin/butler/
  # this is required for version >=0.1.0
  sudo ln -fs (which butler-server) /opt/chef/bin/butler/server.py
  sudo ln -fs (which butler-dispatcher) /opt/chef/bin/butler/dispatcher.py
  for service in $butler_services
    chef-install-ext --as-root $base/$service.service /etc/systemd/system/
  end

  sudo systemctl daemon-reload
  sudo systemctl enable $butler_services

  if not set -q _flag_no_restart
    sudo systemctl restart $butler_services
  else
    echo "Skipping Butler restart, will need a reboot or to restart manually with:"
    echo "sudo systemctl restart $butler_services"
  end
end
