param keyVaultName string
param location string
param tags object
@description('Search service name; only read when storeSearchKey is true.')
param searchName string
@description('Store the Search admin key as a secret (fallback if Entra access to Free tier is refused).')
param storeSearchKey bool
param searchKeySecretName string

// Purge protection is off on purpose so teardown can purge the vault.
resource vault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}

resource searchKeySecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = if (storeSearchKey) {
  parent: vault
  name: searchKeySecretName
  properties: {
    value: search.listAdminKeys().primaryKey
  }
}

output keyVaultName string = vault.name
output keyVaultUri string = vault.properties.vaultUri
