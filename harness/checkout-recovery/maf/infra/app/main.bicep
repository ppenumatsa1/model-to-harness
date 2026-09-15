targetScope = 'resourceGroup'

@description('Azure region for the isolated checkout-recovery lane.')
param location string = resourceGroup().location

@minLength(3)
@maxLength(20)
@description('Lowercase naming prefix. A deterministic suffix makes resources isolated per resource group.')
param namePrefix string = 'crmaf'

@description('Image reference, including immutable tag or digest, for the private FastAPI API.')
param backendImage string = ''

@description('Image reference, including immutable tag or digest, for the public React/nginx UI.')
param frontendImage string = ''

param deployApps bool = false

@secure()
param apiToken string

@secure()
param uiHtpasswd string

param foundryAccountName string
param foundryProjectName string

@description('Container port exposed by the FastAPI image.')
param backendTargetPort int = 8000

@description('Foundry project endpoint resolved from the selected azd environment; never infer or construct it.')
param foundryProjectEndpoint string

@description('Model deployment name resolved from the selected azd environment.')
param foundryModelDeployment string

@secure()
@description('Administrator password supplied by the operator through a secure deployment parameter.')
param postgresAdministratorPassword string

@description('PostgreSQL administrator login name.')
param postgresAdministratorLogin string = 'checkoutadmin'

@description('Name of the lane-owned database. Migration is deliberately a separate operator command.')
param postgresDatabaseName string = 'checkout_recovery'

@minValue(1)
@description('Maximum inventory quantity eligible for automatic reservation recovery.')
param maxAutoInventoryQuantity int = 1

@description('Optional operator IPv4 address for migration access. Omit to avoid creating an operator rule.')
param operatorIp string = ''

var suffix = uniqueString(subscription().subscriptionId, resourceGroup().id, namePrefix)
var registryName = take('${replace(namePrefix, '-', '')}${suffix}acr', 50)
var workspaceName = take('${namePrefix}-${suffix}-logs', 63)
var insightsName = take('${namePrefix}-${suffix}-appi', 64)
var environmentName = take('${namePrefix}-${suffix}-env', 32)
var postgresName = take('${namePrefix}-${suffix}-pg', 63)
var backendName = take('${namePrefix}-${suffix}-api', 32)
var frontendName = take('${namePrefix}-${suffix}-web', 32)
var backendIdentityName = take('${namePrefix}-${suffix}-api-id', 128)
var frontendIdentityName = take('${namePrefix}-${suffix}-web-id', 128)
var databaseUrl = 'postgresql://${uriComponent(postgresAdministratorLogin)}:${uriComponent(postgresAdministratorPassword)}@${postgresName}.postgres.database.azure.com:5432/${postgresDatabaseName}?sslmode=require'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: insightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
  }
}

resource backendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: backendIdentityName
  location: location
}

resource frontendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: frontendIdentityName
  location: location
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: postgresName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: postgresAdministratorLogin
    administratorLoginPassword: postgresAdministratorPassword
    version: '16'
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
  }
}

resource azureServicesFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource operatorFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = if (!empty(operatorIp)) {
  parent: postgres
  name: 'ReleaseOperator'
  properties: {
    startIpAddress: operatorIp
    endIpAddress: operatorIp
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgres
  name: postgresDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource acrPullRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}

resource backendAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, backendIdentity.id, acrPullRole.id)
  scope: registry
  properties: {
    roleDefinitionId: acrPullRole.id
    principalId: backendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource frontendAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, frontendIdentity.id, acrPullRole.id)
  scope: registry
  properties: {
    roleDefinitionId: acrPullRole.id
    principalId: frontendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource backend 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: backendName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${backendIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: backendTargetPort
        transport: 'auto'
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: backendIdentity.id
        }
      ]
      secrets: [
        {
          name: 'api-token'
          value: apiToken
        }
        {
          name: 'database-url'
          value: databaseUrl
        }
        {
          name: 'appinsights-connection'
          value: insights.properties.ConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: backendImage
          env: [
            { name: 'CHECKOUT_RECOVERY_API_TOKEN', secretRef: 'api-token' }
            { name: 'CHECKOUT_RECOVERY_EXECUTION_MODE', value: 'maf' }
            { name: 'CHECKOUT_RECOVERY_ENVIRONMENT', value: 'production' }
            { name: 'ENABLE_SENSITIVE_DATA', value: 'false' }
            {
              name: 'CHECKOUT_RECOVERY_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'CHECKOUT_RECOVERY_FOUNDRY_PROJECT_ENDPOINT'
              value: foundryProjectEndpoint
            }
            {
              name: 'CHECKOUT_RECOVERY_FOUNDRY_MODEL_DEPLOYMENT'
              value: foundryModelDeployment
            }
            {
              name: 'CHECKOUT_RECOVERY_MAX_AUTO_INVENTORY_QUANTITY'
              value: string(maxAutoInventoryQuantity)
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: backendIdentity.properties.clientId
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-connection'
            }
            {
              name: 'OTEL_SERVICE_NAME'
              value: 'checkout-recovery-maf-api'
            }
            {
              name: 'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT'
              value: 'false'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/api/health/live'
                port: backendTargetPort
              }
              initialDelaySeconds: 15
              periodSeconds: 20
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/health/ready'
                port: backendTargetPort
              }
              initialDelaySeconds: 10
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
      }
    }
  }
}

resource frontend 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: frontendName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${frontendIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        { name: 'api-token', value: apiToken }
        { name: 'ui-htpasswd', value: uiHtpasswd }
      ]
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: frontendIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'frontend'
          image: frontendImage
          env: [
            { name: 'CHECKOUT_API_TOKEN', secretRef: 'api-token' }
            { name: 'CHECKOUT_UI_HTPASSWD', secretRef: 'ui-htpasswd' }
            {
              name: 'BACKEND_HOST'
              value: backend!.properties.configuration.ingress.fqdn
            }
            {
              name: 'NGINX_ENVSUBST_FILTER'
              value: 'BACKEND_HOST|CHECKOUT_API_TOKEN'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/healthz'
                port: 8080
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
      }
    }
  }
}

output registryName string = registry.name
output registryLoginServer string = registry.properties.loginServer
output backendAppName string = backendName
output frontendAppName string = frontendName
output frontendUrl string = deployApps ? 'https://${frontend!.properties.configuration.ingress.fqdn}' : ''
output postgresHost string = '${postgres.name}.postgres.database.azure.com'
output postgresDatabaseName string = database.name
output applicationInsightsName string = insights.name
output backendManagedIdentityClientId string = backendIdentity.properties.clientId

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundry
  name: foundryProjectName
}

resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: project
  name: 'checkout-telemetry'
  properties: {
    category: 'AppInsights'
    target: insights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: insights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: insights.id
    }
  }
}

resource backendProjectAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, backendIdentity.id, 'checkout-project')
  scope: project
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
    principalId: backendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource inferenceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, backendIdentity.id, 'checkout-inference')
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
    principalId: backendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
