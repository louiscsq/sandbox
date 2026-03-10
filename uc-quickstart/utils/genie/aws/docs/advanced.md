# Advanced Usage

This document covers optional and advanced workflows that most first-time users can skip.

## Generation Options

```bash
make generate GENERATE_ARGS='--tables a.b.* c.d.e'
make generate GENERATE_ARGS='--dry-run'
```

If you want to run the script directly, do it from inside the env workspace and call the root-owned script:

```bash
cd envs/dev
python ../../generate_abac.py --tables "a.b.*" "c.d.e"
python ../../generate_abac.py --dry-run
```

Pass group names through Make:

```bash
make generate GENERATE_ARGS='--groups "Finance_Analyst,Clinical_Staff"'
```

## IDP-Synced Groups

When groups are managed by an identity provider such as Okta or Azure AD, keep group ownership out of workspace and `data_access` envs entirely. Those layers already look groups up by name. The only place that mentions `manage_groups` is `envs/account/env.auto.tfvars`, where it remains `true` if Terraform should own account-level group creation.

This changes behavior:

- Groups are looked up by name instead of created
- Workspace assignment and entitlements still run
- Any account-level `group_members` should stay empty in `envs/account/abac.auto.tfvars`

Use `--groups` to tell the LLM your exact IDP group names:

```bash
make generate GENERATE_ARGS='--groups "acme-finance-readers,acme-clinical-staff,acme-compliance"'
```

The LLM uses these exact names in generated FGAC policies, tag assignments, and Genie Space ACLs.

## ABAC-Only Mode (No Genie Space)

To use the tool for ABAC governance without creating a Genie Space:

```bash
# 1. Set up credentials
make setup
vi envs/dev/auth.auto.tfvars
vi envs/dev/env.auto.tfvars

# 2. Generate ABAC config
make generate GENERATE_ARGS='--tables catalog.schema.*'

# 3. Review and tune
vi envs/dev/generated/abac.auto.tfvars
vi envs/dev/generated/masking_functions.sql

# 4. Keep Genie disabled in envs/dev/env.auto.tfvars
# genie_space_id = ""
# uc_tables = []    # workspace layer skips Genie when uc_tables is empty
# uc_catalog = ""   # clear catalog too when skipping workspace Genie

# 5. Promote + apply shared governance and workspace entitlements
make promote
make apply
```

Overall ABAC-only flow:

1. `make generate` creates a full draft in `envs/<env>/generated/`
2. You tune tags, FGAC policies, and masking SQL there
3. `make promote` moves governance into `envs/<env>/data_access/` and leaves only workspace or Genie config in `envs/<env>/`
4. `make apply` deploys account identities, shared data-access resources, and workspace entitlements

With `uc_tables = []`, `uc_catalog = ""`, and `genie_space_id = ""`, the workspace layer skips Genie creation while the account layer still creates tag policies and the env-scoped `data_access` layer deploys masking UDFs, assigns tags, and creates FGAC policies.

## Existing Masking Functions

If you have pre-existing masking SQL UDFs, the tool can incorporate them:

1. Run `make generate` so the AI creates `masking_functions.sql` and `abac.auto.tfvars` in `envs/dev/generated/`
2. Edit `envs/dev/generated/masking_functions.sql` and replace generated UDF definitions with your existing functions
3. Update `function_name`, `function_catalog`, and `function_schema` in `envs/dev/generated/abac.auto.tfvars` to match your existing UDFs
4. Run `make apply`

## Multi-Environment Setup

Use the flows in `../README.md` and `flows.md` for the day-to-day workflow. This section is only the mental model for how files are laid out across multiple environments.

Workspace environment names can be anything: `dev`, `staging`, `prod`, `bu2`, or something business-unit-specific. `account` and `data_access` are reserved names.

Under the hood:

- `envs/account/` is shared
- every workspace env gets its own `envs/<env>/data_access/`
- every workspace env also gets its own `envs/<env>/`
- Terraform code stays in the module root under `roots/` and `modules/`
- helper scripts stay in the module root under `scripts/`

Resulting layout:

```text
envs/
  account/
    auth.auto.tfvars
    env.auto.tfvars
    abac.auto.tfvars
    terraform.tfstate

  dev/
    auth.auto.tfvars
    env.auto.tfvars
    data_access/
      auth.auto.tfvars
      env.auto.tfvars
      abac.auto.tfvars
      masking_functions.sql
      terraform.tfstate
    abac.auto.tfvars
    ddl/
    generated/
    .genie_space_id
    terraform.tfstate

  prod/
    auth.auto.tfvars
    env.auto.tfvars
    data_access/
      auth.auto.tfvars
      env.auto.tfvars
      abac.auto.tfvars
      masking_functions.sql
      terraform.tfstate
    abac.auto.tfvars
    ddl/
    generated/
    .genie_space_id
    terraform.tfstate

roots/
  account/
  data_access/
  workspace/
```

Each env keeps its own Terraform state and local artifacts. `account` is the only shared layer; governance and workspace files are isolated per environment under `envs/<env>/data_access/` and `envs/<env>/`.

Catalog-boundary assumption:

- `uc_catalog` in `env.auto.tfvars` holds the environment-specific catalog name
- `uc_tables` holds schema-relative refs (`schema.table`) that are the same in every environment
- `make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog` swaps `dev_catalog` for `prod_catalog` throughout the generated config in one step

Governance promotion across environments:

- `make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog` creates `envs/prod/env.auto.tfvars`, remaps catalog references, and splits the config into account + data_access + workspace layers
- `make promote` with no `DEST_ENV` re-splits the current environment's `generated/` after hand edits
- `make sync-tags` runs against the shared account layer because tag policy definitions are account-scoped
- `make generate ENV=<env>` is still the right choice for a fully independent environment such as a second business unit

## Migrating an Existing Root-Based Workspace

If you already used the old root-local workflow, migrate it once before using the new default env dispatch:

```bash
make migrate-root-to-env ENV=dev
make migrate-state ENV=dev
```

That moves root working files into `envs/dev/` and rewrites any legacy top-level Terraform addresses into the new layered module addresses so future `make generate` and `make apply` commands continue from the same environment layout without forced recreation.

## Examples

A pre-built finance demo is available in `examples/finance/` if you want to try the flow without AI generation. Sample healthcare DDLs are in `examples/healthcare/ddl/` for testing `make generate`.
