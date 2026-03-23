# GenieRails — Azure

Put Genie onboarding on rails — with built-in guardrails. GenieRails generates ABAC governance, masking functions, and Genie Spaces from a small set of input files so you can get business users into Genie quickly without editing Terraform.

## Prerequisites

- Tables must already exist in Unity Catalog before running `make generate`
- An Azure Databricks workspace with Unity Catalog enabled
- A Databricks service principal with these roles:


| Mode | Role | Why it's needed |
| ---- | ---- | --------------- |
| Full (default) | **Account Admin** | Create groups, assign groups to workspaces, manage group membership |
| Full (default) | **Workspace Admin** | Grant entitlements, create warehouses, manage Genie Spaces and permissions |
| Full (default) | **Metastore Admin** | Create tag policies, FGAC policies, grants, and masking functions |
| Genie-only | **Workspace USER** + **Databricks SQL access** entitlement | Create Genie Spaces only — set `genie_only = true` and provide `sql_warehouse_id` in `env.auto.tfvars`. Also requires `CAN USE` on the warehouse and UC table access (`USE CATALOG`, `USE SCHEMA`, `SELECT`) granted by the governance team. No admin roles needed. |

For Azure-specific resource setup (Azure AD App Registration, RBAC roles, storage accounts), see [Azure Prerequisites](docs/azure-prerequisites.md).

## Quickstart

```bash
make setup
vi envs/dev/auth.auto.tfvars      # service principal credentials
vi envs/dev/env.auto.tfvars       # your tables and Genie Space name

make generate
vi envs/dev/generated/abac.auto.tfvars       # review AI-generated groups, policies, Genie config
vi envs/dev/generated/masking_functions.sql  # review AI-generated masking and row-filter functions
make validate-generated
make apply
```

### `auth.auto.tfvars` — Azure format

```hcl
databricks_account_id     = "your-account-id"
databricks_account_host   = "https://accounts.azuredatabricks.net"
databricks_client_id      = "your-sp-client-id"
databricks_client_secret  = "your-sp-secret"
databricks_workspace_id   = "your-workspace-id"
databricks_workspace_host = "https://adb-1234567890.12.azuredatabricks.net"
```

Note: Two URLs differ from AWS and must be set explicitly:
- `databricks_account_host` — required for Azure (`accounts.azuredatabricks.net`); the Terraform default is the AWS URL
- `databricks_workspace_host` — Azure uses `adb-<workspace-id>.<region-id>.azuredatabricks.net`

### `env.auto.tfvars` — minimal example

```hcl
genie_spaces = [
  {
    name      = "Sales Analytics"
    uc_tables = [
      "dev_catalog.sales.orders",
      "dev_catalog.sales.customers",
      "dev_catalog.finance.*",   # wildcard expands all tables in the schema
    ]
  },
]
```

All table names must be fully qualified (`catalog.schema.table` or `catalog.schema.*`). The `name` becomes the Genie Space title in the UI. A serverless SQL warehouse is created automatically — see [Playbook](../shared/docs/playbook.md) for warehouse and multi-space options.

### What `make apply` does

1. Applies account-level groups and optional group membership
2. Applies UC grants, tag policies, FGAC policies, and masking functions
3. Creates the Genie Space, configures it, and sets group permissions

## Next Steps

**Promote `dev` to `prod`:**

```bash
make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG_MAP="dev_catalog=prod_catalog"
vi envs/prod/auth.auto.tfvars
make apply ENV=prod
```

**Add a separate environment (different BU, different tables):**

```bash
make setup ENV=bu2 && vi envs/bu2/auth.auto.tfvars && vi envs/bu2/env.auto.tfvars
make generate ENV=bu2 && make apply ENV=bu2
```

## Testing

```bash
make test-unit   # unit tests — ~1 second, no credentials required
make test-ci     # full CI pipeline: provision → integration tests → teardown
```

For integration tests, configure Azure credentials:

```bash
cp ../shared/scripts/account-admin.env.example ../shared/scripts/account-admin.env
# Edit: set CLOUD_PROVIDER=azure and fill in Azure + Databricks credentials
```

See [Integration Testing](../shared/docs/integration-testing.md) for setup, credentials, scenarios, and troubleshooting.

## Multi-Cloud Architecture

GenieRails uses a shared module architecture. All Terraform modules, scripts, and Python tools live in `../shared/`. This `azure/` directory is a thin cloud-specific wrapper containing only:
- `Makefile` — sets `CLOUD=azure` and includes `../shared/Makefile.shared`
- `envs/` — Azure environment configs
- `.github/workflows/` — Azure-specific CI (Azure Blob Storage state backend)
- `docs/` — Azure-specific prerequisites and setup

For AWS, see [`../aws/`](../aws/README.md).

## Documentation

- [Azure Prerequisites](docs/azure-prerequisites.md) — Azure-specific resource setup, RBAC roles, storage accounts
- [Playbook](../shared/docs/playbook.md) — all use cases: quickstart, ABAC-only, multi-space, existing spaces, promotion, self-service Genie, destroy
- [Architecture](../shared/docs/architecture.md) — layers, artifact ownership, config files, Genie Space lifecycle
- [Central Governance, Self-Service Genie](../shared/docs/self-service-genie.md) — central ABAC team + BU teams self-serve Genie spaces
- [CI/CD Integration](../shared/docs/cicd.md) — validate and deploy from a pipeline
- [Troubleshooting](../shared/docs/troubleshooting.md) — imports, provider quirks, brownfield workflows
- [Advanced Usage](../shared/docs/advanced.md) — IDP-synced groups, ABAC-only mode, masking UDF reuse, legacy migration
- [Integration Testing](../shared/docs/integration-testing.md) — unit tests, integration scenarios, test data

## Roadmap

- Genie Workbench integration
- Telemetry enablement
- Full schema evolution support
