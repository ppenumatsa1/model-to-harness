targetScope = 'resourceGroup'

@description('Verified existing MAF API configuration with secret values removed. Only its image may change.')
param backend object

@description('Verified existing MAF frontend configuration with secret values removed. Only its image may change.')
param frontend object

@description('Existing secret values, retained without rotation.')
@secure()
param secretValues object

var backendSecrets = [for secret in (backend.properties.configuration.?secrets ?? []): union(secret, contains(secret, 'keyVaultUrl') ? {} : {
  value: secretValues.backend[secret.name]
})]
var frontendSecrets = [for secret in (frontend.properties.configuration.?secrets ?? []): union(secret, contains(secret, 'keyVaultUrl') ? {} : {
  value: secretValues.frontend[secret.name]
})]

resource api 'Microsoft.App/containerApps@2025-07-01' = {
  name: backend.name
  location: backend.location
  tags: backend.tags
  identity: backend.identity
  properties: union(backend.properties, {
    configuration: union(backend.properties.configuration, contains(backend.properties.configuration, 'secrets') ? {
      secrets: backendSecrets
    } : {})
  })
}

resource web 'Microsoft.App/containerApps@2025-07-01' = {
  name: frontend.name
  location: frontend.location
  tags: frontend.tags
  identity: frontend.identity
  properties: union(frontend.properties, {
    configuration: union(frontend.properties.configuration, contains(frontend.properties.configuration, 'secrets') ? {
      secrets: frontendSecrets
    } : {})
  })
}
