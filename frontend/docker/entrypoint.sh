#!/bin/bash
set -e

# JoySafeter Frontend Entrypoint
# Uses pm2 for process management in JDOS production environment

if [ -z "${PM2_INSTANCES}" ]; then
  PM2_INSTANCES=2
fi

# Update pm2 instances from env
if command -v pm2 >/dev/null 2>&1 && [ -f pm2.json ]; then
  # Use sed to update instances count in pm2.json
  sed -i "s/\"instances\": [0-9]*/\"instances\": ${PM2_INSTANCES}/" pm2.json
  exec pm2-runtime start pm2.json
else
  # Fallback: run node directly
  exec node server.js
fi
