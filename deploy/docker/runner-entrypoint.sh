#!/bin/sh
# Convert purpose-specific inline credentials to one-shot files before the
# runner starts. This limits inheritance into the runner's child processes;
# provider-level secret delivery remains responsible for container metadata.
. /usr/local/lib/joysafeter/runtime-credentials.sh
prepare_runtime_credentials

exec joysafeter-runner "$@"
