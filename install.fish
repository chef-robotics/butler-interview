#!/usr/bin/env fish
# Installs Chef Butler

source (dirname (status -f))/../lib/utils.fish

argparse --name=install_butler \
    v/version= \
    -- $argv
and set -q _flag_version
or begin
  logerr "Usage: install.fish --version <version>"
  exit 1
end

is-nix; and logerr 'TODO(kyle): install butler on nix'; and exit 0

set -g failed_steps
function helper
  # All helper output should go to stderr
  if not call $CHEF_EDGE/butler/helpers/$argv[1] $argv[2..-1] >&2
    set failed_steps $failed_steps "$argv[1]"
  end
end

helper install_dependencies.fish --version=$_flag_version
helper install_butler_service.fish --no-restart

log "Finished installing chef butler"
set -l exit_code (count $failed_steps)
and echo "Failed steps $failed_steps!"
exit $exit_code
