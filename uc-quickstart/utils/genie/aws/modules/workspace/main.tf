terraform {
  required_providers {
    databricks = {
      source                = "databricks/databricks"
      version               = "~> 1.91.0"
      configuration_aliases = [databricks.account, databricks.workspace]
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

data "databricks_group" "existing" {
  for_each = var.groups

  provider     = databricks.account
  display_name = each.key
}

locals {
  group_ids = {
    for name, group in data.databricks_group.existing : name => group.id
  }

  effective_warehouse_id = (
    var.sql_warehouse_id != ""
    ? var.sql_warehouse_id
    : databricks_sql_endpoint.warehouse[0].id
  )

  genie_groups_csv = join(",", keys(var.groups))
}

resource "databricks_mws_permission_assignment" "group_assignments" {
  for_each = local.group_ids

  provider     = databricks.account
  workspace_id = var.databricks_workspace_id
  principal_id = each.value
  permissions  = ["USER"]
}

resource "databricks_entitlements" "group_entitlements" {
  for_each = local.group_ids

  provider = databricks.workspace
  group_id = each.value

  workspace_consume = true

  depends_on = [databricks_mws_permission_assignment.group_assignments]
}

resource "databricks_sql_endpoint" "warehouse" {
  count = var.sql_warehouse_id != "" ? 0 : 1

  provider         = databricks.workspace
  name             = var.warehouse_name
  cluster_size     = "Small"
  max_num_clusters = 1

  enable_serverless_compute = true
  warehouse_type            = "PRO"

  auto_stop_mins = 15
}

resource "null_resource" "genie_space_acls" {
  count = var.genie_space_id != "" ? 1 : 0

  triggers = {
    space_id = var.genie_space_id
    groups   = local.genie_groups_csv
  }

  provisioner "local-exec" {
    command = var.genie_script_path == "" ? "true" : "${var.genie_script_path} set-acls"

    environment = {
      DATABRICKS_HOST          = var.databricks_workspace_host
      DATABRICKS_CLIENT_ID     = var.databricks_client_id
      DATABRICKS_CLIENT_SECRET = var.databricks_client_secret
      GENIE_SPACE_OBJECT_ID    = var.genie_space_id
      GENIE_GROUPS_CSV         = local.genie_groups_csv
    }
  }

  depends_on = [databricks_mws_permission_assignment.group_assignments]
}

resource "null_resource" "genie_space_create" {
  count = var.genie_space_id == "" && length(var.uc_tables) > 0 ? 1 : 0

  triggers = {
    id_file       = var.genie_id_file
    script        = var.genie_script_path
    host          = var.databricks_workspace_host
    client_id     = var.databricks_client_id
    client_secret = var.databricks_client_secret
  }

  provisioner "local-exec" {
    command = "${self.triggers.script} create"

    environment = {
      DATABRICKS_HOST          = self.triggers.host
      DATABRICKS_CLIENT_ID     = self.triggers.client_id
      DATABRICKS_CLIENT_SECRET = self.triggers.client_secret
      GENIE_ID_FILE            = self.triggers.id_file
      GENIE_TABLES_CSV         = join(",", var.uc_tables)
      GENIE_WAREHOUSE_ID       = local.effective_warehouse_id
      GENIE_TITLE              = var.genie_space_title
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = "${self.triggers.script} trash"

    environment = {
      DATABRICKS_HOST          = self.triggers.host
      DATABRICKS_CLIENT_ID     = self.triggers.client_id
      DATABRICKS_CLIENT_SECRET = self.triggers.client_secret
      GENIE_ID_FILE            = self.triggers.id_file
    }
  }

  depends_on = [
    databricks_mws_permission_assignment.group_assignments,
    databricks_sql_endpoint.warehouse,
  ]
}

resource "null_resource" "genie_space_config" {
  count = var.genie_space_id == "" && length(var.uc_tables) > 0 ? 1 : 0

  triggers = {
    tables          = join(",", var.uc_tables)
    title           = var.genie_space_title
    description     = var.genie_space_description
    questions       = jsonencode(var.genie_sample_questions)
    instructions    = var.genie_instructions
    benchmarks      = jsonencode(var.genie_benchmarks)
    sql_filters     = jsonencode(var.genie_sql_filters)
    sql_measures    = jsonencode(var.genie_sql_measures)
    sql_expressions = jsonencode(var.genie_sql_expressions)
    join_specs      = jsonencode(var.genie_join_specs)
  }

  provisioner "local-exec" {
    command = "${var.genie_script_path} update-config"

    environment = {
      DATABRICKS_HOST          = var.databricks_workspace_host
      DATABRICKS_CLIENT_ID     = var.databricks_client_id
      DATABRICKS_CLIENT_SECRET = var.databricks_client_secret
      GENIE_ID_FILE            = var.genie_id_file
      GENIE_TABLES_CSV         = join(",", var.uc_tables)
      GENIE_WAREHOUSE_ID       = local.effective_warehouse_id
      GENIE_TITLE              = var.genie_space_title
      GENIE_DESCRIPTION        = var.genie_space_description
      GENIE_SAMPLE_QUESTIONS   = jsonencode(var.genie_sample_questions)
      GENIE_INSTRUCTIONS       = var.genie_instructions
      GENIE_BENCHMARKS         = jsonencode(var.genie_benchmarks)
      GENIE_SQL_FILTERS        = jsonencode(var.genie_sql_filters)
      GENIE_SQL_EXPRESSIONS    = jsonencode(var.genie_sql_expressions)
      GENIE_SQL_MEASURES       = jsonencode(var.genie_sql_measures)
      GENIE_JOIN_SPECS         = jsonencode(var.genie_join_specs)
    }
  }

  depends_on = [null_resource.genie_space_create]
}

resource "null_resource" "genie_space_acls_created" {
  count = var.genie_space_id == "" && length(var.uc_tables) > 0 ? 1 : 0

  triggers = {
    groups = local.genie_groups_csv
  }

  provisioner "local-exec" {
    command = "${var.genie_script_path} set-acls"

    environment = {
      DATABRICKS_HOST          = var.databricks_workspace_host
      DATABRICKS_CLIENT_ID     = var.databricks_client_id
      DATABRICKS_CLIENT_SECRET = var.databricks_client_secret
      GENIE_ID_FILE            = var.genie_id_file
      GENIE_GROUPS_CSV         = local.genie_groups_csv
    }
  }

  depends_on = [null_resource.genie_space_create]
}
