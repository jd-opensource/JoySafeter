#!/bin/sh
# Sandbox entrypoint: run given command or drop to shell
if [ $# -gt 0 ]; then
  exec "$@"
else
  exec /bin/zsh
fi
