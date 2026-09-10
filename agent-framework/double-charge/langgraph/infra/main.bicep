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

@description('Existing ACR login server, resolved and checked by read-only release discovery.')
param registryEndpoint string

@description('Existing backend managed identity client ID, verified against the deployed app.')
param backendClientId string

@description('Existing private backend ingress FQDN, verified against the same-origin proxy.')
param backendHost string

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

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: insightsName
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

resource backendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: backendIdentityName
}

resource frontendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: frontendIdentityName
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = {
  name: postgresName
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' existing = {
  parent: postgres
  name: postgresDatabaseName
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
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: registryEndpoint
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
              value: backendClientId
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
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: registryEndpoint
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
              value: backendHost
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
output registryEndpoint string = registryEndpoint
output backendName string = backend.name
output frontendName string = frontend.name
output frontendUrl string = 'https://${frontend.properties.configuration.ingress.fqdn}'
output postgresHost string = postgresHost
output postgresDatabaseName string = database.name
output applicationInsightsName string = insights.name
output langgraphSchema string = langgraphSchema
output langgraphCheckpointSchema string = langgraphCheckpointSchema
