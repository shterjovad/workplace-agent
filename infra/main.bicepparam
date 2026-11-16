using 'main.bicep'

// principalId (the developer's Entra object ID) is not committed. scripts/deploy.sh exports
// PRINCIPAL_ID (from `az ad signed-in-user show`) before deploying. Empty default lets the file build in CI.
param principalId = readEnvironmentVariable('PRINCIPAL_ID', '')
param principalType = 'User'
