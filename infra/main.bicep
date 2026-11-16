targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = 'swedencentral'
@description('Prefix for resource names.')
param namePrefix string = 'wpagent'
@description('Suffix that makes globally unique names unique.')
param uniqueSuffix string = uniqueString(resourceGroup().id)
@description('Object ID of the developer (or managed identity) that gets data-plane roles. Supplied at deploy time.')
param principalId string
@allowed(['User', 'ServicePrincipal', 'Group'])
param principalType string = 'User'
param tags object = {
  project: 'workplace-agent'
  environment: 'dev'
}

param blobContainerName string = 'documents'
param searchIndexName string = 'workplace-docs'
@description('API version the app uses for Azure OpenAI; must support structured outputs.')
param openAiApiVersion string = 'v1'

param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param embeddingDeploymentName string = 'text-embedding-3-small'
param embeddingSkuName string = 'GlobalStandard'
param embeddingCapacity int = 50

@description('Escape hatch: set false to skip the chat deployment (e.g. no quota).')
param deployChatModel bool = true
// gpt-4o-mini 2024-07-18 is deprecated (ServiceModelDeprecated since 2026-03-31); gpt-5-mini 2025-08-07 is the default.
param chatModelName string = 'gpt-5-mini'
param chatModelVersion string = '2025-08-07'
param chatDeploymentName string = 'gpt-5-mini'
param chatSkuName string = 'GlobalStandard'
param chatCapacity int = 30

@description('Store the Search admin key in Key Vault (fallback if Entra access to Search Free is refused).')
param searchUseKeyFallback bool = false
param searchKeySecretName string = 'search-admin-key'

var suffix = take(uniqueSuffix, 6)
var storageAccountName = take('st${namePrefix}${suffix}', 24)
var docIntelName = '${namePrefix}-di-${suffix}'
var aiServicesName = '${namePrefix}-ai-${suffix}'
var searchName = '${namePrefix}-search-${suffix}'
var keyVaultName = take('kv-${namePrefix}-${suffix}', 24)

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    logAnalyticsName: 'log-${namePrefix}-${suffix}'
    appInsightsName: 'appi-${namePrefix}-${suffix}'
    location: location
    tags: tags
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    storageAccountName: storageAccountName
    containerName: blobContainerName
    location: location
    tags: tags
  }
}

module ai 'modules/ai.bicep' = {
  name: 'ai'
  params: {
    docIntelName: docIntelName
    aiServicesName: aiServicesName
    location: location
    tags: tags
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    embeddingDeploymentName: embeddingDeploymentName
    embeddingSkuName: embeddingSkuName
    embeddingCapacity: embeddingCapacity
    deployChatModel: deployChatModel
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    chatDeploymentName: chatDeploymentName
    chatSkuName: chatSkuName
    chatCapacity: chatCapacity
  }
}

module search 'modules/search.bicep' = {
  name: 'search'
  params: {
    searchName: searchName
    location: location
    tags: tags
  }
}

module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    keyVaultName: keyVaultName
    location: location
    tags: tags
    searchName: search.outputs.searchName
    storeSearchKey: searchUseKeyFallback
    searchKeySecretName: searchKeySecretName
  }
}

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  params: {
    principalId: principalId
    principalType: principalType
    storageAccountName: storage.outputs.storageAccountName
    aiServicesName: ai.outputs.aiServicesName
    docIntelName: ai.outputs.docIntelName
    searchName: search.outputs.searchName
    keyVaultName: keyvault.outputs.keyVaultName
  }
}

output RESOURCE_GROUP string = resourceGroup().name
output SUBSCRIPTION_ID string = subscription().subscriptionId
output STORAGE_ACCOUNT_URL string = storage.outputs.blobEndpoint
output BLOB_CONTAINER string = blobContainerName
output DOCINTEL_ENDPOINT string = ai.outputs.docIntelEndpoint
output AZURE_OPENAI_ENDPOINT string = ai.outputs.aiServicesEndpoint
output AZURE_OPENAI_API_VERSION string = openAiApiVersion
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = ai.outputs.embeddingDeploymentName
output AZURE_OPENAI_CHAT_DEPLOYMENT string = ai.outputs.chatDeploymentName
output SEARCH_ENDPOINT string = search.outputs.searchEndpoint
output SEARCH_INDEX_NAME string = searchIndexName
output KEY_VAULT_URI string = keyvault.outputs.keyVaultUri
output SEARCH_KEY_SECRET_NAME string = searchUseKeyFallback ? searchKeySecretName : ''
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.connectionString
