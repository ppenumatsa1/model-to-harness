targetScope = 'resourceGroup'

@description('Azure region for all lane-owned resources.')
param location string

@description('Short prefix used to derive globally unique resource names.')
param namePrefix string = 'mth-lg'

@description('Existing LangGraph Foundry account; this template never creates an account.')
param foundryAccountName string

@description('Foundry project name.')
param foundryProjectName string = 'model-harness-langgraph'

@description('Azure OpenAI deployment resource name.')
param modelDeploymentName string = 'model-harness-gpt-5-6-sol'

@description('PostgreSQL administrator login.')
param postgresAdministratorLogin string = 'mthadmin'

@secure()
@description('PostgreSQL administrator password. Supply from the azd environment.')
param postgresAdministratorPassword string

@description('PostgreSQL database name dedicated to the LangGraph lane.')
param postgresDatabaseName string = 'model_harness_langgraph'

@description('Existing PostgreSQL server name; empty preserves the original naming formula.')
param postgresServerName string = ''

@minLength(1)
@maxLength(63)
param langgraphSchema string = 'langgraph_app_cutover'

@minLength(1)
@maxLength(63)
param langgraphCheckpointSchema string = 'langgraph_checkpoints_cutover'

@description('Optional release-operator IPv4 address for database migration access.')
param operatorIp string = ''

@description('Verified immutable backend image reference (registry/repository@sha256:digest).')
param backendImage string

@description('Backend target port.')
param backendTargetPort int = 8000

@description('Verified immutable frontend image reference (registry/repository@sha256:digest).')
param frontendImage string

@description('Enable FastAPI health probes after the real backend image is deployed.')
param enableBackendProbes bool = true

@description('Optional resource tags.')
param tags object = {}

var suffix = uniqueString(subscription().id, resourceGroup().id, namePrefix)
var effectiveFoundryAccountName = foundryAccountName
var registryName = take('${replace(namePrefix, '-', '')}${suffix}acr', 50)
var logName = take('${namePrefix}-${suffix}-log', 63)
var insightsName = take('${namePrefix}-${suffix}-appi', 64)
var environmentName = take('${namePrefix}-${suffix}-cae', 32)
var backendName = take('${namePrefix}-${suffix}-api', 32)
var frontendName = take('${namePrefix}-${suffix}-web', 32)
var backendIdentityName = take('${namePrefix}-${suffix}-api-mi', 128)
var frontendIdentityName = take('${namePrefix}-${suffix}-web-mi', 128)
var postgresName = empty(postgresServerName)
  ? take('${replace(namePrefix, '-', '')}${suffix}pg', 63)
  : postgresServerName
var postgresHost = '${postgresName}.postgres.database.azure.com'
var databaseUrl = 'postgresql://${uriComponent(postgresAdministratorLogin)}:${uriComponent(postgresAdministratorPassword)}@${postgresHost}:5432/${postgresDatabaseName}?sslmode=require'
var foundryProjectEndpoint = 'https://${effectiveFoundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'
var azureOpenAiEndpoint = 'https://${effectiveFoundryAccountName}.openai.azure.com/'

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: effectiveFoundryAccountName
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundryAccount
  name: foundryProjectName
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' existing = {
  parent: foundryAccount
  name: modelDeploymentName
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  tags: tags
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
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource backendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: backendIdentityName
  location: location
  tags: tags
}

resource frontendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: frontendIdentityName
  location: location
  tags: tags
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresName
  location: location
  tags: tags
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

resource azureServicesFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource operatorFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!empty(operatorIp)) {
  parent: postgres
  name: 'ReleaseOperator'
  properties: {
    startIpAddress: operatorIp
    endIpAddress: operatorIp
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
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

resource openAiUserRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
}

resource logAnalyticsReaderRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '73c42c96-874c-492b-b04d-ab87d138a893'
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

resource backendOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, backendIdentity.id, openAiUserRole.id)
  scope: foundryAccount
  properties: {
    roleDefinitionId: openAiUserRole.id
    principalId: backendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, foundryProject.id, openAiUserRole.id)
  scope: foundryAccount
  properties: {
    roleDefinitionId: openAiUserRole.id
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectApplicationInsightsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(insights.id, foundryProject.id, logAnalyticsReaderRole.id)
  scope: insights
  properties: {
    roleDefinitionId: logAnalyticsReaderRole.id
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectLogAnalyticsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(logs.id, foundryProject.id, logAnalyticsReaderRole.id)
  scope: logs
  properties: {
    roleDefinitionId: logAnalyticsReaderRole.id
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectApplicationInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundryProject
  name: 'ApplicationInsights'
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
  dependsOn: [
    projectApplicationInsightsReader
    projectLogAnalyticsReader
  ]
}

resource backend 'Microsoft.App/containerApps@2024-03-01' = {
  name: backendName
  location: location
  tags: tags
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
          name: 'database-url'
          #disable-next-line use-secure-value-for-secure-inputs
          value: databaseUrl
        }
        {
          name: 'appinsights'
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
            {
              name: 'APP_ENV'
              value: 'production'
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'LANGGRAPH_SCHEMA'
              value: langgraphSchema
            }
            {
              name: 'LANGGRAPH_CHECKPOINT_SCHEMA'
              value: langgraphCheckpointSchema
            }
            {
              name: 'CORS_ORIGINS'
              value: ''
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT'
              value: modelDeployment.name
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: backendIdentity.properties.clientId
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights'
            }
            {
              name: 'OTEL_SERVICE_NAME'
              value: 'model-harness-langgraph-api'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: enableBackendProbes ? [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: backendTargetPort
              }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/ready'
                port: backendTargetPort
              }
              initialDelaySeconds: 15
              periodSeconds: 15
            }
          ] : []
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
      }
    }
  }
}

resource frontend 'Microsoft.App/containerApps@2024-03-01' = {
  name: frontendName
  location: location
  tags: tags
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
      ingress: {
        external: true
        targetPort: 80
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
            {
              name: 'BACKEND_HOST'
              value: backend.properties.configuration.ingress.fqdn
            }
            {
              name: 'NGINX_ENVSUBST_FILTER'
              value: 'BACKEND_HOST'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
      }
    }
  }
}

output foundryAccountName string = foundryAccount.name
output foundryProjectName string = foundryProject.name
output foundryProjectId string = foundryProject.id
output foundryProjectEndpoint string = foundryProjectEndpoint
output openAiEndpoint string = azureOpenAiEndpoint
output modelDeploymentName string = modelDeployment.name
output registryName string = registry.name
output registryEndpoint string = registry.properties.loginServer
output backendName string = backend.name
output frontendName string = frontend.name
output frontendUrl string = 'https://${frontend.properties.configuration.ingress.fqdn}'
output postgresHost string = postgresHost
output postgresDatabaseName string = database.name
output applicationInsightsName string = insights.name
output langgraphSchema string = langgraphSchema
output langgraphCheckpointSchema string = langgraphCheckpointSchema
