# Telemetry Configuration
# This resource sends anonymous usage data to help improve the uc-quickstart project

locals {
  # RFC 9110 compliant User-Agent format: product/version [product/version ...] [(comments)]
  # Similar to Python SDK's with_product() and with_extra() methods
  telemetry_string = "uc-quickstart/${var.uc_quickstart_version} terraform-provider-databricks/${var.databricks_provider_version} (terraform; azure)"
}

resource "null_resource" "telemetry_ping" {
  count = var.enable_telemetry ? 1 : 0

  triggers = {
    telemetry = local.telemetry_string
    timestamp = timestamp()
  }

  provisioner "local-exec" {
    command = <<-EOT
      # Get Azure AD token for Databricks
      AZURE_TOKEN=$(curl -s -X POST "https://login.microsoftonline.com/${var.azure_tenant_id}/oauth2/v2.0/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=client_credentials&client_id=${var.azure_client_id}&client_secret=${var.azure_client_secret}&scope=2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default" \
        2>/dev/null | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
      
      # Get Databricks management token
      DB_TOKEN=$(curl -s -X GET "${var.databricks_host}/api/2.0/token/create" \
        -H "Authorization: Bearer $AZURE_TOKEN" \
        -H "X-Databricks-Azure-SP-Management-Token: $AZURE_TOKEN" \
        -H "X-Databricks-Azure-Workspace-Resource-Id: ${var.databricks_resource_id}" \
        2>/dev/null | grep -o '"token_value":"[^"]*' | cut -d'"' -f4)
      
      # Make API call with telemetry in User-Agent
      if [ -n "$DB_TOKEN" ]; then
        curl -s -f -X GET "${var.databricks_host}/api/2.0/clusters/spark-versions" \
          -H "Authorization: Bearer $DB_TOKEN" \
          -H "User-Agent: ${local.telemetry_string}" \
          -o /dev/null 2>&1 || echo "Telemetry ping completed"
      else
        echo "Telemetry ping completed"
      fi
    EOT
  }
}

