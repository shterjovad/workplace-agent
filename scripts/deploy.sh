#!/usr/bin/env bash
# Deploy infra/main.bicep: what-if, confirm, create, then write .env.
# Usage: scripts/deploy.sh [extra az deployment parameters, e.g. --parameters chatModelName=gpt-5-mini]
set -euo pipefail

RG="${RG:-rg-workplace-agent-dev}"
LOCATION="${LOCATION:-swedencentral}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-workplace-agent}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! az account show >/dev/null 2>&1; then
  echo "Not logged in. Run: az login --tenant <your-tenant>" >&2
  exit 1
fi
echo "Subscription: $(az account show --query name -o tsv) ($(az account show --query id -o tsv))"

if [[ -z "${PRINCIPAL_ID:-}" ]]; then
  PRINCIPAL_ID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"
fi
if [[ -z "$PRINCIPAL_ID" ]]; then
  echo "Could not resolve PRINCIPAL_ID. Set it to your Entra object ID and retry." >&2
  exit 1
fi
export PRINCIPAL_ID
echo "Principal: $PRINCIPAL_ID"

if [[ "$(az group exists -n "$RG")" != "true" ]]; then
  read -r -p "Create resource group $RG in $LOCATION? (yes/no) " answer
  if [[ "$answer" != "yes" ]]; then
    echo "Aborted."
    exit 1
  fi
  az group create -n "$RG" -l "$LOCATION" -o none
fi

COMMON=(-g "$RG" -n "$DEPLOYMENT_NAME" -f "$ROOT/infra/main.bicep" -p "$ROOT/infra/main.bicepparam")

echo "Running what-if..."
az deployment group what-if "${COMMON[@]}" "$@"

read -r -p "Type yes to deploy: " answer
if [[ "$answer" != "yes" ]]; then
  echo "Aborted."
  exit 1
fi

az deployment group create "${COMMON[@]}" "$@" -o none
echo "Deployment complete."

RG="$RG" DEPLOYMENT_NAME="$DEPLOYMENT_NAME" "$ROOT/scripts/env.sh"
