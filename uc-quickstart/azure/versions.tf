terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    # azapi = {
    #   source = "azure/azapi"
    # }
    databricks = {
      source = "databricks/databricks"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}
