#!/usr/bin/env bash
# Delete the resource group and purge soft-deleted Cognitive Services / Key Vault.
set -euo pipefail

RG="${RG:-rg-workplace-agent-dev}"

if [[ "$(az group exists -n "$RG")" != "true" ]]; then
  echo "Resource group $RG does not exist; nothing to delete."
  exit 0
fi

echo "Resources in $RG:"
az resource list -g "$RG" --query '[].{name:name,type:type}' -o table

read -r -p "Type the resource group name ($RG) to delete it: " answer
if [[ "$answer" != "$RG" ]]; then
  echo "Name did not match. Aborted."
  exit 1
fi

SUB="$(az account show --query id -o tsv)"
# Record soft-delete candidates before the group disappears.
kv_names="$(az keyvault list -g "$RG" --query '[].name' -o tsv)"

az group delete -n "$RG" --yes
echo "Resource group deleted."

# Cognitive Services accounts: deleted-account ids contain /resourceGroups/<rg>/.
az cognitiveservices account list-deleted \
  --query "[?contains(id, '/resourceGroups/$RG/')].[name,location]" -o tsv |
while IFS=$'\t' read -r name location; do
  [[ -z "$name" ]] && continue
  echo "Purging Cognitive Services account $name ($location)"
  az cognitiveservices account purge --name "$name" --location "$location" \
    --resource-group "$RG" -o none
done

for kv in $kv_names; do
  if az keyvault list-deleted --query "[?name=='$kv'] | length(@)" -o tsv | grep -qx 1; then
    echo "Purging Key Vault $kv"
    az keyvault purge --name "$kv" -o none
  fi
done

echo "Teardown complete (subscription $SUB)."
