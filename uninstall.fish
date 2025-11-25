#!/usr/bin/env fish
# Installs Chef Butler

source (dirname (status -f))/../lib/utils.fish

set -g failed_steps
function helper
  # All helper output should go to stderr
  if not call $CHEF_EDGE/butler/helpers/$argv[1] $argv[2..-1] >&2
    set failed_steps $failed_steps "$argv[1]"
  end
end

helper install_butler_service.fish --uninstall

log "Finished installing chef butler"
set -l exit_code (count $failed_steps)
and echo "Failed steps $failed_steps!"
exit $exit_code
