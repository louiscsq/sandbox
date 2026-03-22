# GenieRails

Put Genie onboarding on rails — with built-in guardrails. GenieRails generates ABAC governance, masking functions, and Genie Spaces from a small set of input files so you can get business users into Genie quickly without editing Terraform.

## Prerequisites

- Tables must already exist in Unity Catalog before running `make generate`
- A Databricks service principal with these roles:


| Mode | Role | Why it's needed |
| ---- | ---- | --------------- |
| Full (default) | **Account Admin** | Create groups, assign groups to workspaces, manage group membership |
| Full (default) | **Workspace Admin** | Grant entitlements, create warehouses, manage Genie Spaces and permissions |
| Full (default) | **Metastore Admin** | Create tag policies, FGAC policies, grants, and masking functions |
| Genie-only | **Workspace USER** + **Databricks SQL access** entitlement | Create Genie Spaces only — set `genie_only = true` and provide `sql_warehouse_id` in `env.auto.tfvars`. Also requires `CAN USE` on the warehouse and UC table access (`USE CATALOG`, `USE SCHEMA`, `SELECT`) granted by the governance team. No admin roles needed. |


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

All table names must be fully qualified (`catalog.schema.table` or `catalog.schema.*`). The `name` becomes the Genie Space title in the UI. A serverless SQL warehouse is created automatically — see [Playbook](docs/playbook.md) for warehouse and multi-space options.

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

See [Integration Testing](docs/integration-testing.md) for setup, credentials, scenarios, and troubleshooting.

## Documentation

- [Playbook](docs/playbook.md) — all use cases: quickstart, ABAC-only, multi-space, existing spaces, promotion, decentralized governance, destroy
- [Architecture](docs/architecture.md) — layers, artifact ownership, config files, Genie Space lifecycle
- [Decentralized Governance](docs/decentralized.md) — central ABAC team + independent BU Genie teams
- [CI/CD Integration](docs/cicd.md) — validate and deploy from a pipeline
- [Troubleshooting](docs/troubleshooting.md) — imports, provider quirks, brownfield workflows
- [Advanced Usage](docs/advanced.md) — IDP-synced groups, ABAC-only mode, masking UDF reuse, legacy migration
- [Integration Testing](docs/integration-testing.md) — unit tests, integration scenarios, test data

## Roadmap

- Genie Workbench integration
- Azure support
- Telemetry enablement
- Full schema evolution support

