# Environment Config — tables, warehouse, and Genie Space settings.
# Make loads this file into the correct Terraform root for you.
# This file is safe to check into Git (no secrets).
#
#   cp env.auto.tfvars.example env.auto.tfvars

# The environment-specific catalog. Only this changes between dev, staging, and prod.
# Schema and table names are assumed stable across environments (Databricks best practice).
uc_catalog = "louis_sydney"

# Schema-relative table references (no catalog prefix). Same across all environments.
# Use schema.* to include all tables in a schema.
uc_tables = ["clinical.encounters", "finance.*"]

# SQL warehouse ID.
# - In envs/<workspace>/data_access/env.auto.tfvars this controls the warehouse
#   used for masking function deployment.
# - In envs/<workspace>/env.auto.tfvars this controls the warehouse used by the
#   workspace layer / Genie Space.
# Leave empty to auto-create a serverless warehouse.
# Find warehouse IDs: Databricks workspace > SQL Warehouses > select warehouse > copy ID
sql_warehouse_id = ""

# Genie Space ID. Set to apply ACLs to an existing space.
# Leave empty to auto-create a new Genie Space from uc_tables on apply.
# Find space ID: open the Genie Space in Databricks UI > copy ID from the URL.
genie_space_id = ""

# ─── Multi-Environment Layout ───
#
# For multi-env deployments on the same Databricks account, the quickstart
# keeps one shared account state plus one env-scoped data_access + workspace
# state per environment:
#
#   envs/
#     account/                    # shared state — account module only
#       auth.auto.tfvars          # defaults to workspace auth symlink; replace if needed
#       env.auto.tfvars           # account-specific settings
#       abac.auto.tfvars          # groups + optional group_members only
#
#     dev/                        # dev workspace module state
#       auth.auto.tfvars          # workspace SP credentials
#       env.auto.tfvars           # workspace settings: uc_catalog = "dev_catalog", uc_tables = ["schema.*"]
#       data_access/
#         auth.auto.tfvars        # defaults to ../auth.auto.tfvars; replace if needed
#         env.auto.tfvars         # defaults to ../env.auto.tfvars
#         abac.auto.tfvars        # env-scoped governance config
#         masking_functions.sql   # env-scoped masking SQL
#       abac.auto.tfvars          # groups lookup + Genie config only
#
#     prod/                       # prod workspace module state
#       auth.auto.tfvars
#       env.auto.tfvars           # workspace settings: uc_catalog = "prod_catalog", uc_tables = ["schema.*"]
#       data_access/
#         auth.auto.tfvars
#         env.auto.tfvars
#         abac.auto.tfvars
#         masking_functions.sql
#       abac.auto.tfvars          # groups lookup + Genie config only
#
# Account layer: groups + optional group_members.
# Data-access layer: env-scoped governance + masking SQL.
# Workspace layers: groups looked up by name, workspace assignments/
# entitlements, warehouse, and optional Genie lifecycle only.
# `make destroy` only tears down the selected layer state.
