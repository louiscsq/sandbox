# Telemetry Configuration
# This resource sends anonymous usage data to help improve the uc-quickstart project

locals {
  # RFC 9110 compliant User-Agent format: product/version [product/version ...] [(comments)]
  # Similar to Python SDK's with_product() and with_extra() methods
  telemetry_string = "uc-quickstart/${var.uc_quickstart_version} terraform-provider-databricks/${var.databricks_provider_version} (terraform; aws)"
}

resource "null_resource" "telemetry_ping" {
  count = var.enable_telemetry ? 1 : 0

  triggers = {
    telemetry = local.telemetry_string
    timestamp = timestamp()
  }

  provisioner "local-exec" {
    command = <<-EOT
      # Get OAuth token using client credentials
      TOKEN=$(curl -s -X POST "${var.databricks_host}/oidc/v1/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=client_credentials&client_id=${var.databricks_client_id}&client_secret=${var.databricks_client_secret}&scope=all-apis" \
        2>/dev/null | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
      
      # Make API call with telemetry in User-Agent
      if [ -n "$TOKEN" ]; then
        curl -s -f -X GET "${var.databricks_host}/api/2.0/clusters/spark-versions" \
          -H "Authorization: Bearer $TOKEN" \
          -H "User-Agent: ${local.telemetry_string}" \
          -o /dev/null 2>&1 || echo "Telemetry ping completed"
      else
        echo "Telemetry ping completed"
      fi
    EOT
  }
}

