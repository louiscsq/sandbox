# Flows

This document covers the main day-to-day workflows:

- quickstart your first `dev` environment
- promote `dev` to `prod`
- create a second independent environment for another business unit
- destroy or reset an environment

Bare commands default to `ENV=dev`. Use `ENV=<name>` whenever you want a different workspace environment.

`make apply ENV=<workspace>` always works in this order:

1. `envs/account/` shared account layer
2. `envs/<workspace>/data_access/` env-scoped governance layer
3. `envs/<workspace>/` workspace-local layer

## 1. Quickstart your first environment (`dev`)

Use this when you are starting from scratch and want one working environment quickly.

```bash
make setup
vi envs/dev/auth.auto.tfvars
# Enter workspace credentials for the service principal.
#
# This file is your input credentials file.
#
vi envs/dev/env.auto.tfvars
# Choose the environment inputs:
# - which catalog this environment should use
# - which schema-relative tables Genie and ABAC should target
#
# Set:
#   uc_catalog = "dev_catalog"
#   uc_tables  = ["schema.*"]
# Optional: replace envs/account/auth.auto.tfvars or
# envs/dev/data_access/auth.auto.tfvars if shared layers need different credentials.

make generate
vi envs/dev/generated/abac.auto.tfvars
# Review and iterate on the generated governance and Genie config:
# - groups
# - tag policies
# - tag assignments
# - FGAC policies
# - Genie instructions, questions, benchmarks, filters, and measures
#
vi envs/dev/generated/masking_functions.sql
# Review and iterate on the generated masking and row-filter functions
# before applying them.
#
make validate-generated
make apply
```

What happens:

1. `make setup` creates `envs/account/`, `envs/dev/data_access/`, and `envs/dev/`
2. `make generate` creates a draft in `envs/dev/generated/`
3. You tune the generated governance and Genie config
4. `make apply` splits the generated draft into account, data-access, and workspace artifacts, then applies all three layers

## 2. Add the next environment

After `dev` is working, most teams choose one of these two paths.

### 2a. Promote `dev` to `prod`

Use this when `prod` should reuse the same schema-relative table set, groups, and governance design as `dev`, but point at a different catalog.

```bash
make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog
vi envs/prod/auth.auto.tfvars
# Enter the prod workspace credentials.
#
make apply ENV=prod
```

What happens:

1. `make promote` remaps catalog references from `dev_catalog` to `prod_catalog`
2. It writes `envs/prod/env.auto.tfvars`
3. It splits the promoted config into:
   - `envs/account/abac.auto.tfvars`
   - `envs/prod/data_access/abac.auto.tfvars`
   - `envs/prod/data_access/masking_functions.sql`
   - `envs/prod/abac.auto.tfvars`
4. `make apply ENV=prod` applies the shared account layer, then the prod governance layer, then the prod workspace layer

Use `make generate ENV=prod` instead of `make promote` only when prod needs a fully separate LLM-generated design.

### 2b. Create a second independent environment for another business unit

Use this when a second business unit needs its own groups, governance, Genie space, and possibly its own tables, rather than a promotion of `dev`.

Example with a new environment named `bu2`:

```bash
make setup ENV=bu2
vi envs/bu2/auth.auto.tfvars
# Enter the BU workspace credentials.
#
vi envs/bu2/env.auto.tfvars
# Choose the BU catalog and tables to govern.
#
# Example:
#   uc_catalog = "bu2_catalog"
#   uc_tables  = ["finance.*", "ops.*"]

make generate ENV=bu2
vi envs/bu2/generated/abac.auto.tfvars
# Review and iterate on generated policies, groups, and Genie config.
#
vi envs/bu2/generated/masking_functions.sql
# Review and iterate on generated masking functions.
#
make validate-generated ENV=bu2
make apply ENV=bu2
```

When to use this flow instead of promotion:

- The business unit has different tables or schemas
- The business unit needs different groups
- The Genie prompts, measures, or benchmarks should be generated independently
- The governance design should evolve separately from `dev`

## 3. Destroy and reset

Destroy commands are layer-aware:

```bash
# Destroy one workspace environment (workspace first, then data_access)
make destroy ENV=dev
make destroy ENV=prod
make destroy ENV=bu2

# Destroy only the shared account layer
make destroy ENV=account

# Remove local generated files and Terraform state for one environment
make clean ENV=dev

# Remove all env directories under envs/
make clean-all
```

Rules to remember:

- `make destroy ENV=<workspace>` destroys only that environment's workspace and `data_access` layers
- `make destroy ENV=account` destroys shared account resources such as groups and tag policy definitions
- Destroying one environment does not destroy other environments
- `make clean` removes local state and generated artifacts but keeps your checked-in config files
- `make clean-all` removes the full `envs/` tree, including environment configs and local state

## How It Works

The quickstart is a three-step loop:

1. **You provide inputs**

   - `auth.auto.tfvars`: secrets and workspace connection details
   - `env.auto.tfvars`: environment-specific catalog, tables, optional warehouse, and optional Genie Space ID

2. **`make generate` creates a draft**

   - fetches DDLs from Unity Catalog
   - sends the prompt plus DDLs to the configured LLM
   - writes draft outputs into `envs/<env>/generated/`

3. **You review, then `make apply` deploys**

   - tune `generated/abac.auto.tfvars`
   - tune `generated/masking_functions.sql`
   - run `make validate-generated`
   - run `make apply`, which splits the draft into layered configs and applies them

### Generated Draft Outputs

| File | What it contains |
| ---- | ---------------- |
| `envs/<env>/generated/abac.auto.tfvars` | Groups, tag policies, tag assignments, FGAC policies, and Genie configuration |
| `envs/<env>/generated/masking_functions.sql` | SQL masking and row-filter functions referenced by FGAC policies |

### What `make apply` creates

| Layer | Creates in Databricks |
| ----- | --------------------- |
| Account | Account groups, optional group membership, tag policy definitions |
| Data access | Tag assignments, masking functions, FGAC policies, catalog grants |
| Workspace | Workspace assignment, entitlements, optional warehouse, optional Genie Space and ACLs |

In practice, the flow is:

```text
inputs -> make generate -> review generated/ -> make validate-generated -> make apply
```
