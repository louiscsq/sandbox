variable "databricks_account_id" {
  type        = string
  description = "The Databricks account ID."
}

variable "databricks_client_id" {
  type        = string
  description = "The Databricks service principal client ID."
}

variable "databricks_client_secret" {
  type        = string
  description = "The Databricks service principal client secret."
  sensitive   = true
}

variable "databricks_workspace_id" {
  type        = string
  description = "The Databricks workspace ID."
}

variable "databricks_workspace_host" {
  type        = string
  description = "The Databricks workspace URL."
}

variable "uc_tables" {
  type        = list(string)
  default     = []
  description = "Tables to generate ABAC policies for and to include in Genie."
}

variable "manage_groups" {
  type        = bool
  default     = false
  description = "Workspace state only supports lookup/onboarding for pre-existing groups."

  validation {
    condition     = !var.manage_groups
    error_message = "Workspace state requires manage_groups = false. Manage groups in envs/account instead."
  }
}

variable "groups" {
  type = map(object({
    description = optional(string, "")
  }))
  description = "Map of group name -> config. Workspace state looks these groups up by name."
}

variable "sql_warehouse_id" {
  type        = string
  default     = ""
  description = "Existing SQL warehouse ID to reuse."
}

variable "warehouse_name" {
  type        = string
  default     = "ABAC Serverless Warehouse"
  description = "Name of the auto-created serverless warehouse."
}

variable "genie_space_id" {
  type        = string
  default     = ""
  description = "Existing Genie Space ID. When empty and uc_tables is non-empty, a new space is created."
}

variable "genie_space_title" {
  type        = string
  default     = "Genie Space"
  description = "Title for an auto-created Genie Space."
}

variable "genie_space_description" {
  type        = string
  default     = ""
  description = "Description for an auto-created Genie Space."
}

variable "genie_sample_questions" {
  type        = list(string)
  default     = []
  description = "Sample questions shown in the Genie UI."
}

variable "genie_instructions" {
  type        = string
  default     = ""
  description = "Instructions for the Genie LLM."
}

variable "genie_benchmarks" {
  type = list(object({
    question = string
    sql      = string
  }))
  default     = []
  description = "Benchmark questions plus ground-truth SQL."
}

variable "genie_sql_filters" {
  type = list(object({
    sql          = string
    display_name = string
    comment      = string
    instruction  = string
  }))
  default     = []
  description = "SQL filters exposed to Genie."
}

variable "genie_sql_expressions" {
  type = list(object({
    alias        = string
    sql          = string
    display_name = string
    comment      = string
    instruction  = string
  }))
  default     = []
  description = "SQL expressions exposed to Genie."
}

variable "genie_sql_measures" {
  type = list(object({
    alias        = string
    sql          = string
    display_name = string
    comment      = string
    instruction  = string
  }))
  default     = []
  description = "SQL measures exposed to Genie."
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
  default     = []
  description = "Join specs exposed to Genie."
}

variable "genie_id_file" {
  type        = string
  description = "Path to the per-environment Genie ID file."
}

variable "genie_script_path" {
  type        = string
  description = "Path to scripts/genie_space.sh."
}
