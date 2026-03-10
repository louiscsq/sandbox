terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.91.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
  required_version = ">= 1.0"

  backend "local" {}
}

provider "databricks" {
  alias         = "account"
  host          = "https://accounts.cloud.databricks.com"
  account_id    = var.databricks_account_id
  client_id     = var.databricks_client_id
  client_secret = var.databricks_client_secret
}

provider "databricks" {
  alias         = "workspace"
  host          = var.databricks_workspace_host
  client_id     = var.databricks_client_id
  client_secret = var.databricks_client_secret
}

locals {
  project_root   = abspath("${path.root}/../..")
  full_uc_tables = [for t in var.uc_tables : var.uc_catalog != "" ? "${var.uc_catalog}.${t}" : t]
}

variable "env_dir" {
  type = string
}

variable "databricks_account_id" {
  type = string
}

variable "databricks_client_id" {
  type = string
}

variable "databricks_client_secret" {
  type      = string
  sensitive = true
}

variable "databricks_workspace_id" {
  type = string
}

variable "databricks_workspace_host" {
  type = string
}

variable "uc_catalog" {
  type    = string
  default = ""
}

variable "uc_tables" {
  type    = list(string)
  default = []
}

variable "manage_groups" {
  type    = bool
  default = false
}
variable "groups" {
  type = map(object({
    description = optional(string, "")
  }))
  default = {}
}
variable "group_members" {
  type    = map(list(string))
  default = {}
}
variable "tag_policies" {
  type = list(object({
    key         = string
    description = optional(string, "")
    values      = list(string)
  }))
  default = []
}
variable "tag_assignments" {
  type = list(object({
    entity_type = string
    entity_name = string
    tag_key     = string
    tag_value   = string
  }))
  default = []
}
variable "fgac_policies" {
  type = list(object({
    name              = string
    policy_type       = string
    catalog           = string
    to_principals     = list(string)
    except_principals = optional(list(string), [])
    comment           = optional(string, "")
    match_condition   = optional(string)
    match_alias       = optional(string)
    function_name     = string
    function_catalog  = string
    function_schema   = string
    when_condition    = optional(string)
  }))
  default = []
}
variable "sql_warehouse_id" {
  type    = string
  default = ""
}

variable "warehouse_name" {
  type    = string
  default = "ABAC Serverless Warehouse"
}

variable "genie_space_id" {
  type    = string
  default = ""
}

variable "genie_space_title" {
  type    = string
  default = "Genie Space"
}

variable "genie_space_description" {
  type    = string
  default = ""
}

variable "genie_sample_questions" {
  type    = list(string)
  default = []
}

variable "genie_instructions" {
  type    = string
  default = ""
}
variable "genie_benchmarks" {
  type = list(object({
    question = string
    sql      = string
  }))
  default = []
}
variable "genie_sql_filters" {
  type = list(object({
    sql          = string
    display_name = string
    comment      = string
    instruction  = string
  }))
  default = []
}
variable "genie_sql_expressions" {
  type = list(object({
    alias        = string
    sql          = string
    display_name = string
    comment      = string
    instruction  = string
  }))
  default = []
}
variable "genie_sql_measures" {
  type = list(object({
    alias        = string
    sql          = string
    display_name = string
    comment      = string
    instruction  = string
  }))
  default = []
}
variable "genie_join_specs" {
  type = list(object({
    left_table  = string
    left_alias  = string
    right_table = string
    right_alias = string
    sql         = string
    comment     = string
    instruction = string
  }))
  default = []
}

module "workspace" {
  source = "../../modules/workspace"

  providers = {
    databricks.account   = databricks.account
    databricks.workspace = databricks.workspace
  }

  databricks_account_id     = var.databricks_account_id
  databricks_client_id      = var.databricks_client_id
  databricks_client_secret  = var.databricks_client_secret
  databricks_workspace_id   = var.databricks_workspace_id
  databricks_workspace_host = var.databricks_workspace_host
  uc_tables                 = local.full_uc_tables
  manage_groups             = var.manage_groups
  groups                    = var.groups
  sql_warehouse_id          = var.sql_warehouse_id
  warehouse_name            = var.warehouse_name
  genie_space_id            = var.genie_space_id
  genie_space_title         = var.genie_space_title
  genie_space_description   = var.genie_space_description
  genie_sample_questions    = var.genie_sample_questions
  genie_instructions        = var.genie_instructions
  genie_benchmarks          = var.genie_benchmarks
  genie_sql_filters         = var.genie_sql_filters
  genie_sql_expressions     = var.genie_sql_expressions
  genie_sql_measures        = var.genie_sql_measures
  genie_join_specs          = var.genie_join_specs
  genie_id_file             = "${var.env_dir}/.genie_space_id"
  genie_script_path         = "${local.project_root}/scripts/genie_space.sh"
}

output "group_ids" {
  value = module.workspace.group_ids
}

output "group_names" {
  value = module.workspace.group_names
}

output "workspace_assignments" {
  value = module.workspace.workspace_assignments
}

output "group_entitlements" {
  value = module.workspace.group_entitlements
}

output "sql_warehouse_id" {
  value = module.workspace.sql_warehouse_id
}

output "genie_space_acls_applied" {
  value = module.workspace.genie_space_acls_applied
}

output "genie_space_acls_groups" {
  value = module.workspace.genie_space_acls_groups
}

output "genie_space_created" {
  value = module.workspace.genie_space_created
}

output "genie_groups_csv" {
  value = module.workspace.genie_groups_csv
}
