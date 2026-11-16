#!/usr/bin/env bash
# Upload sample documents to the blob container using Entra ID auth.
# Usage: scripts/upload-samples.sh [source-dir]   (default: samples/documents)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo ".env not found. Run scripts/env.sh first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

SRC="${1:-samples/documents}"
ACCOUNT="${STORAGE_ACCOUNT_URL#https://}"
ACCOUNT="${ACCOUNT%%.*}"

az storage blob upload-batch --auth-mode login --account-name "$ACCOUNT" \
  -d "$BLOB_CONTAINER" -s "$SRC" --overwrite -o none

echo "Blobs in $BLOB_CONTAINER:"
az storage blob list --auth-mode login --account-name "$ACCOUNT" \
  -c "$BLOB_CONTAINER" --query '[].name' -o tsv
