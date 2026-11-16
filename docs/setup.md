# Azure setup and deployment

Everything lives in one resource group (`rg-workplace-agent-dev`, Sweden Central) and is removed with `scripts/teardown.sh`.

## 1. Tooling and login

```bash
brew install azure-cli
az login --tenant <your-tenant>
az account set -s "Azure for Students"
az bicep install
```

## 2. Register resource providers (once per subscription)

```bash
for p in Microsoft.CognitiveServices Microsoft.Search Microsoft.Storage \
         Microsoft.KeyVault Microsoft.OperationalInsights Microsoft.Insights; do
  az provider register --namespace "$p"
done
az provider list --query "[?namespace=='Microsoft.Search'].registrationState" -o tsv   # wait for Registered
```

## 3. Read-only pre-checks

```bash
# Model availability and remaining quota in the region
az cognitiveservices model list -l swedencentral --query "[?model.name=='gpt-4o-mini' || model.name=='text-embedding-3-small'].{n:model.name,v:model.version}" -o table
az cognitiveservices usage list -l swedencentral -o table

# Policies that could block deployment
az policy assignment list --query "[].{name:name,scope:scope}" -o table

# An existing Free-tier search service (only one per subscription is allowed)
az search service list --query "[].{name:name,sku:sku.name,rg:resourceGroup}" -o table

# Can you create role assignments? (Owner or User Access Administrator needed)
az role assignment list --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --all --query "[].roleDefinitionName" -o tsv
```

## 4. Deploy

```bash
scripts/deploy.sh            # what-if, confirm, create, write .env
```

It asks before creating the resource group and again before deploying. Extra parameters pass through, which is the fallback when a model or the Search RBAC path is unavailable:

```bash
scripts/deploy.sh --parameters searchUseKeyFallback=true \
  chatModelName=gpt-5-mini chatModelVersion=2025-08-07
```

`scripts/env.sh` regenerates `.env` from the deployment outputs (mode 600, refuses if `.env` is not git-ignored).

## 5. Upload sample documents

```bash
scripts/upload-samples.sh [dir]     # default: samples/documents
```

## 6. Teardown

```bash
scripts/teardown.sh
```

You must type the resource group name. It deletes the group, then purges soft-deleted Cognitive Services accounts and Key Vaults so names and quota are freed.

The Azure for Students credit expires 2026-11-27. Run teardown before then (and whenever the project is idle) to avoid leftover charges.
