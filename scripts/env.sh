#!/usr/bin/env bash
# Write deployment outputs to .env (git-ignored, mode 600).
set -euo pipefail

RG="${RG:-rg-workplace-agent-dev}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-workplace-agent}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! git check-ignore -q .env; then
  echo "Refusing to write .env: it is not git-ignored. Add '.env' to .gitignore first." >&2
  exit 1
fi

outputs="$(az deployment group show -g "$RG" -n "$DEPLOYMENT_NAME" --query properties.outputs -o json)"

umask 077
printf '%s' "$outputs" | python3 -c '
import json, sys
for k, v in json.load(sys.stdin).items():
    print("%s=%s" % (k.upper(), v["value"]))
' > .env
chmod 600 .env

echo "Wrote .env with:"
cut -d= -f1 .env | sed 's/^/  /'
