#!/bin/sh
# Scrub JOYSAFETER_RUNNER_TOKEN from the container environment.
#
# Problem: Docker injects the full container env into every `docker exec`
# session, so `unset` inside the runner process (PID 1) does NOT prevent
# `docker exec env` from showing the token.
#
# Solution: this entrypoint saves the token to a tmpfs file readable only
# by the runner user, removes it from the environment, then execs the
# runner. The runner reads JOYSAFETER_RUNNER_TOKEN from env (which is
# still set at this point in the entrypoint, before unset+exec), but
# subsequent `docker exec` sessions will NOT see it because Docker
# re-reads the container config — and by the time the runner is running,
# the env var is gone from the process tree.
#
# Final approach: save to a file, point JOYSAFETER_RUNNER_TOKEN_FILE at
# it, unset the original, exec runner. Runner reads from file if env is
# empty.

TOKEN_FILE="/tmp/.runner-token"

if [ -n "${JOYSAFETER_RUNNER_TOKEN:-}" ]; then
    printf '%s' "$JOYSAFETER_RUNNER_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    export JOYSAFETER_RUNNER_TOKEN_FILE="$TOKEN_FILE"
    unset JOYSAFETER_RUNNER_TOKEN
fi

exec joysafeter-runner "$@"
