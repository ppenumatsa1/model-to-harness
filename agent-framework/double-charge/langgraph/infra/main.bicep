targetScope = 'resourceGroup'

@description('Azure region for all lane-owned resources.')
param location string = 'northcentralus'

@description('Short prefix used to derive globally unique resource names.')
param namePrefix string = 'mth-lg'

@description('Optional explicit Foundry account name. Leave empty to derive a unique name.')
param foundryAccountName string = ''

@description('Foundry project name.')
param foundryProjectName string = 'model-harness-langgraph'

@description('Azure OpenAI deployment resource name.')
param modelDeploymentName string = 'model-harness-gpt-5-6-sol'

@description('Model catalog name.')
param modelName string = 'gpt-5.6-sol'

@description('Pinned model version.')
param modelVersion string = '2026-07-09'

@minValue(1)
@description('GlobalStandard deployment capacity. Confirm regional quota before deployment.')
param modelCapacity int = 100

@description('PostgreSQL administrator login.')
param postgresAdministratorLogin string = 'mthadmin'

@secure()
@description('PostgreSQL administrator password. Supply from the azd environment.')
param postgresAdministratorPassword string

@description('PostgreSQL database name dedicated to the LangGraph lane.')
param postgresDatabaseName string = 'model_harness_langgraph'

@description('Optional release-operator IPv4 address for database migration access.')
param operatorIp string = ''

@description('Backend image. The deploy script replaces the bootstrap image after ACR build.')
param backendImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Backend target port.')
param backendTargetPort int = 80

@description('Frontend image. The deploy script replaces the bootstrap image after ACR build.')
param frontendImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Enable FastAPI health probes after the real backend image is deployed.')
param enableBackendProbes bool = false

@description('Optional resource tags.')
param tags object = {}

var suffix = uniqueString(subscription().id, resourceGroup().id, namePrefix)
var effectiveFoundryAccountName = empty(foundryAccountName)
  ? take('${replace(namePrefix, '-', '')}${suffix}ai', 64)
  : foundryAccountName
var registryName = take('${replace(namePrefix, '-', '')}${suffix}acr', 50)
var logName = take('${namePrefix}-${suffix}-log', 63)
var insightsName = take('${namePrefix}-${suffix}-appi', 64)
var environmentName = take('${namePrefix}-${suffix}-cae', 32)
var backendName = take('${namePrefix}-${suffix}-api', 32)
var frontendName = take('${namePrefix}-${suffix}-web', 32)
var backendIdentityName = take('${namePrefix}-${suffix}-api-mi', 128)
var frontendIdentityName = take('${namePrefix}-${suffix}-web-mi', 128)
var postgresName = take('${replace(namePrefix, '-', '')}${suffix}pg', 63)
var postgresHost = '${postgresName}.postgres.database.azure.com'
var databaseUrl = 'postgresql://${postgresAdministratorLogin}:${postgresAdministratorPassword}@${postgresHost}:5432/${postgresDatabaseName}?sslmode=require'
var foundryProjectEndpoint = 'https://${effectiveFoundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'
var azureOpenAiEndpoint = 'https://${effectiveFoundryAccountName}.openai.azure.com/'

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: effectiveFoundryAccountName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: effectiveFoundryAccountName
    disableLocalAuth: true
    dynamicThrottlingEnabled: false
    publicNetworkAccess: 'Enabled'
    restrictOutboundNetworkAccess: false
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundryAccount
  name: foundryProjectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: foundryProjectName
    description: 'Independent LangGraph double-charge workflow project.'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundryAccount
  name: modelDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
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
              value: 'langgraph_app'
            }
            {
              name: 'LANGGRAPH_CHECKPOINT_SCHEMA'
              value: 'langgraph_checkpoints'
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
