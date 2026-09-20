using './main.bicep'

param namePrefix = 'crcopilot'
param backendTargetPort = 8030
param postgresDatabaseName = 'checkout_recovery'
param maxAutoInventoryQuantity = 1
