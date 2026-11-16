@description('Name of the Log Analytics workspace.')
param logAnalyticsName string
@description('Name of the Application Insights component.')
param appInsightsName string
param location string
param tags object

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: json('0.1') // cost guard: 0.1 GB/day (minimum allowed is 0.023)
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

output appInsightsName string = appInsights.name
output connectionString string = appInsights.properties.ConnectionString
