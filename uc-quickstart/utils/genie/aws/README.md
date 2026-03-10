# GenieRails

Put Genie onboarding on rails — with built-in guardrails. This quickstart generates ABAC governance, masking functions, and an optional Genie Space from a small set of input files so you can get business users into Genie quickly without editing Terraform.

## What This Quickstart Automates

- AI-generated ABAC config from Unity Catalog table DDLs
- Account-level groups and optional group membership
- Workspace onboarding and Databricks One entitlements
- Unity Catalog access grants for exposed data
- Tag policies, tag assignments, and FGAC policies
- Masking functions for column masks and row filters
- Optional Genie Space creation, configuration, and ACLs
- Optional serverless SQL warehouse creation

## Prerequisites

- Tables must already exist in Unity Catalog before running `make generate`
- Use a Databricks service principal with these roles:

| Role | Why it's needed |
| ---- | --------------- |
| **Account Admin** | Create account-level groups, assign groups to workspaces, manage group membership |
| **Workspace Admin** | Grant entitlements, create or manage warehouses, Genie Spaces, and Genie permissions |
| **Metastore Admin** | Create tag policies, FGAC policies, grants, and masking functions |

## Quickstart

Start here. Bare commands default to `ENV=dev`.

```bash
make setup
vi envs/dev/auth.auto.tfvars
vi envs/dev/env.auto.tfvars

make generate
vi envs/dev/generated/abac.auto.tfvars
vi envs/dev/generated/masking_functions.sql
make validate-generated
make apply
```

What you do in each step:

- `auth.auto.tfvars`: enter the service principal credentials for the target workspace
- `env.auto.tfvars`: choose the catalog and schema-relative tables to govern
- `generated/abac.auto.tfvars`: review and iterate on generated groups, policies, and Genie config
- `generated/masking_functions.sql`: review and iterate on generated masking and row-filter functions
- `make apply`: split and apply the account, data-access, and workspace layers

## Next Step: Add Another Environment

After `dev` is working, choose one path:

### 1. Promote `dev` to `prod`

Use this when `prod` should reuse the same schema-relative tables and governance design as `dev`, but point at a different catalog.

```bash
make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog
vi envs/prod/auth.auto.tfvars
# Enter the prod workspace credentials.
#
make apply ENV=prod
```

### 2. Create a separate environment for another business unit

Use this when the next environment needs different tables, groups, Genie config, or governance.

```bash
make setup ENV=bu2
vi envs/bu2/auth.auto.tfvars
# Enter the BU workspace credentials.
#
vi envs/bu2/env.auto.tfvars
# Choose the BU catalog and tables to govern.
#

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

## Documentation

- [Flows](docs/flows.md): quickstart, promotion, separate BU environment, destroy/reset
- [Architecture](docs/architecture.md): layers, artifact ownership, config files, Genie Space behavior, make targets
- [Troubleshooting](docs/troubleshooting.md): imports, provider quirks, brownfield workflows
- [Advanced Usage](docs/advanced.md): generation options, IDP-synced groups, ABAC-only mode, masking UDF reuse, multi-environment layout, legacy migration

## Roadmap

- Unity Catalog metrics in Genie
- Multi Genie Space support
- Multi data steward / user support
- AI-assisted tuning and troubleshooting
- Auto-detect and import existing policies
