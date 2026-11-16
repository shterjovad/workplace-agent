param searchName string
param location string
param tags object

// Free tier: 1 replica / 1 partition only. aadOrApiKey enables Entra (RBAC) data-plane auth alongside keys.
resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchName
  location: location
  tags: tags
  sku: {
    name: 'free'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    publicNetworkAccess: 'enabled'
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
  }
}

output searchName string = search.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
