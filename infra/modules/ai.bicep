param docIntelName string
param aiServicesName string
param location string
param tags object

param embeddingModelName string
param embeddingModelVersion string
param embeddingDeploymentName string
param embeddingSkuName string
param embeddingCapacity int

param deployChatModel bool
param chatModelName string
param chatModelVersion string
param chatDeploymentName string
param chatSkuName string
param chatCapacity int

// S0, never F0: F0 only parses the first 2 pages of each document.
resource docIntel 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: docIntelName
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: docIntelName
    publicNetworkAccess: 'Enabled'
  }
}

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: aiServicesName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: aiServicesName
    publicNetworkAccess: 'Enabled'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiServices
  name: embeddingDeploymentName
  sku: {
    name: embeddingSkuName
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
}

// Deployments on one account must be created serially, hence dependsOn.
resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployChatModel) {
  parent: aiServices
  name: chatDeploymentName
  sku: {
    name: chatSkuName
    capacity: chatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
  dependsOn: [
    embeddingDeployment
  ]
}

output docIntelName string = docIntel.name
output docIntelEndpoint string = docIntel.properties.endpoint
output aiServicesName string = aiServices.name
output aiServicesEndpoint string = aiServices.properties.endpoint
output embeddingDeploymentName string = embeddingDeployment.name
output chatDeploymentName string = chatDeploymentName
