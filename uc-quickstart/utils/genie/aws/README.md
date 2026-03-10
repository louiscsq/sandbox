# GenieRails

Put Genie onboarding on rails — with built-in guardrails. An AI-powered Terraform quickstart that gets business users into Genie quickly and safely — ABAC governance, masking functions, and a fully configured Genie Space with AI-generated sample questions, instructions, benchmarks, SQL filters, measures, and join specs — all from three config files, no `.tf` editing required.

## What This Quickstart Automates

- **AI-generated ABAC config** — Point at your tables, and an LLM analyzes column sensitivity to generate groups, tag policies, tag assignments, FGAC policies, and masking functions automatically.
- **Business groups** — Create account-level groups (access tiers) and optionally manage group membership.
- **Workspace onboarding** — Assign groups to a target workspace with Databricks One consumer entitlements.
- **Data access grants** — Apply minimum Unity Catalog privileges (`USE_CATALOG`, `USE_SCHEMA`, `SELECT`) for data exposed through Genie.
- **ABAC governance** — Create governed tag policies, tag assignments on tables/columns, and FGAC policies (column masks + row filters).
- **Masking functions** — Auto-deploy SQL UDFs to enforce column-level data masking (e.g., mask SSN, redact PII, hash emails).
- **Genie Space** — Auto-create a new Genie Space from your tables, or bring an existing one. New spaces include AI-generated config:
  - **Sample questions** — Conversation starters tailored to your data domain
  - **Instructions** — Domain-specific LLM guidance with business defaults (e.g., "customer" means active by default)
  - **Benchmarks** — Unambiguous ground-truth question + SQL pairs for evaluating Genie accuracy
  - **SQL filters** — Default WHERE clauses (e.g., active customers, completed transactions) that guide Genie's SQL generation
  - **SQL measures & expressions** — Standard metrics (total revenue, avg risk score) and computed dimensions (transaction year)
  - **Join specs** — Table relationships with join conditions so Genie knows how to combine tables
  - **Title & description** — Contextual naming based on your tables and domain
  - For existing spaces, set `genie_space_id` in `env.auto.tfvars` to apply `CAN_RUN` ACLs for all configured business groups
- **SQL warehouse** — Auto-create a serverless warehouse or reuse an existing one.

## How It Works

```
┌───────────────────────────────────────────────────────────────────────┐
│                    YOU PROVIDE (one-time setup)                       │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌───────────────────────────────┐ ┌───────────────────────────────┐  │
│  │  auth.auto.tfvars             │ │  env.auto.tfvars              │  │
│  │  (secrets — gitignored)       │ │  (environment — checked in)   │  │
│  │                               │ │                               │  │
│  │  databricks_account_id = "..."│ │  uc_catalog = "dev_catalog"   │  │
│  │  databricks_client_id  = "..."│ │  uc_tables  = ["schema.*"]    │  │
│  │  databricks_client_secret     │ │  sql_warehouse_id = ""        │  │
│  │  databricks_workspace_host    │ │  genie_space_id = ""          │  │
│  │                               │ │                               │  │
│  └───────────────┬───────────────┘ └───────────────┬───────────────┘  │
│                  └────────────────┬────────────────┘                  │
└───────────────────────────────────┼───────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│                make generate  (generate_abac.py)                      │
│                                                                       │
│  1. Fetches DDLs from Unity Catalog (via Databricks SDK)              │
│  2. Reads ABAC_PROMPT.md + DDLs  ──▶  LLM (Claude Sonnet)             │
│                                                                       │
│  Providers: Databricks FMAPI (default) | Anthropic | OpenAI           │
└──────────────────────────────────┬────────────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼                             ▼
┌───────────────────────────────────────────────────────────────────────┐
│                     generated/  (output folder)                       │
│                                                                       │
│  ┌─────────────────────────┐  ┌───────────────────────────────────┐   │
│  │  masking_functions.sql  │  │  abac.auto.tfvars                 │   │
│  │                         │  │  (ABAC + Genie — no credentials)  │   │
│  │  SQL UDFs:              │  │                                   │   │
│  │  • mask_pii_partial()   │  │  groups        ─ access tiers     │   │
│  │  • mask_ssn()           │  │  tag_policies  ─ sensitivity tags │   │
│  │  • mask_email()         │  │  tag_assignments ─ tags on cols   │   │
│  │  • filter_by_region()   │  │  fgac_policies ─ masks & filters  │   │
│  │  • ...                  │  │  genie_space_title / description  │   │
│  │                         │  │  genie_sample_questions (5–10)    │   │
│  │                         │  │  genie_instructions               │   │
│  │                         │  │  genie_benchmarks (3–5 w/ SQL)    │   │
│  │                         │  │  genie_sql_filters / measures     │   │
│  │                         │  │  genie_sql_expressions            │   │
│  │                         │  │  genie_join_specs                 │   │
│  └────────────┬────────────┘  └─────────────────┬─────────────────┘   │
└───────────────┼─────────────────────────────────┼─────────────────────┘
                │             ▲  TUNE & VALIDATE  │
                │             │  make validate-generated
                │             │  (repeat until PASS)
                ▼                                 ▼
┌───────────────────────────────────────────────────────────────────────┐
│  make apply  (validate → split promote → apply account + workspace)   │
│  Loads shared account state and the selected workspace state           │
│                                                                       │
│  Creates in Databricks:                                               │
│  ┌────────────────┐  ┌───────────────┐  ┌─────────────────────────┐   │
│  │ Account Groups │  │ Tag Policies  │  │ Tag Assignments         │   │
│  │ Analyst        │  │ pii_level     │  │ Customers.SSN           │   │
│  │ Manager        │  │ phi_level     │  │   → pii_level=masked    │   │
│  │ Compliance     │  │ data_region   │  │ Billing.Amount          │   │
│  │ Admin          │  │               │  │   → pii_level=masked    │   │
│  └────────────────┘  └───────────────┘  └─────────────────────────┘   │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ FGAC Policies (Column Masks + Row Filters)                     │   │
│  │                                                                │   │
│  │ "Analyst sees SSN as ***-**-1234"      ──▶ mask_ssn()          │   │
│  │ "Manager sees notes as [REDACTED]"     ──▶ mask_redact()       │   │
│  │ "US_Staff sees only US rows"           ──▶ filter_by_region()  │   │
│  └────────────────────────────────────────────────────────────────┘   │
│  ┌────────────────────┐  ┌────────────────┐  ┌────────────────────┐   │
│  │ Masking Functions  │  │ UC Grants      │  │ Genie Space        │   │
│  │ (auto-deploy UDFs) │  │ USE_CATALOG    │  │ • sample questions │   │
│  │                    │  │ USE_SCHEMA     │  │ • instructions     │   │
│  │ + SQL Warehouse    │  │ SELECT         │  │ • benchmarks       │   │
│  │ (auto-created if   │  │                │  │ • sql filters /    │   │
│  │  needed)           │  │                │  │   measures / joins │   │
│  │                    │  │                │  │ • CAN_RUN ACLs     │   │
│  │                    │  │                │  │   for all groups   │   │
│  └────────────────────┘  └────────────────┘  └────────────────────┘   │
└───────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Tables must exist in Unity Catalog before running `make generate`
- A Databricks **service principal** with the following roles:


| Role                | Why it's needed                                                                                                                                                                                                                                                                                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Account Admin**   | Create account-level groups, assign groups to workspace, manage group membership                                                                                                                                                                                                                                                                             |
| **Workspace Admin** | Grant entitlements (`workspace_consume`), create/manage Genie Spaces and permissions                                                                                                                                                                                                                                                                         |
| **Metastore Admin** | Create governed tag policies (`databricks_tag_policy`), and grant itself `USE_CATALOG`, `USE_SCHEMA`, `EXECUTE`, `MANAGE`, `CREATE_FUNCTION` on any catalog to create FGAC policies, assign tags, and deploy masking functions. Without this role, tag policies must be pre-created manually and catalog-level privileges must be granted by a catalog owner |


## Recommended Flows

Bare commands default to `ENV=dev`. Use `ENV=<name>` whenever you want a different workspace environment.

`make apply ENV=<workspace>` always works in this order:

1. `envs/account/` shared account layer
2. `envs/<workspace>/data_access/` env-scoped governance layer
3. `envs/<workspace>/` workspace-local layer

### 1. Quickstart your first environment (`dev`)

Use this when you are starting from scratch and want one working environment quickly.

```bash
make setup
vi envs/dev/auth.auto.tfvars
vi envs/dev/env.auto.tfvars
# Set:
#   uc_catalog = "dev_catalog"
#   uc_tables  = ["schema.*"]
# Optional: replace envs/account/auth.auto.tfvars or
# envs/dev/data_access/auth.auto.tfvars if shared layers need different credentials.

make generate
vi envs/dev/generated/abac.auto.tfvars
vi envs/dev/generated/masking_functions.sql
make validate-generated
make apply
```

What happens:

1. `make setup` creates `envs/account/`, `envs/dev/data_access/`, and `envs/dev/`.
2. `make generate` creates a draft in `envs/dev/generated/`.
3. You tune the generated governance and Genie config.
4. `make apply` splits the generated draft into account, data-access, and workspace artifacts, then applies all three layers.

### 2. Promote `dev` to `prod`

Use this when `prod` should reuse the same schema-relative table set, groups, and governance design as `dev`, but point at a different catalog.

```bash
make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog
vi envs/prod/auth.auto.tfvars
make apply ENV=prod
```

What happens:

1. `make promote` remaps catalog references from `dev_catalog` to `prod_catalog`.
2. It writes `envs/prod/env.auto.tfvars`.
3. It splits the promoted config into:
   - `envs/account/abac.auto.tfvars`
   - `envs/prod/data_access/abac.auto.tfvars`
   - `envs/prod/data_access/masking_functions.sql`
   - `envs/prod/abac.auto.tfvars`
4. `make apply ENV=prod` applies the shared account layer, then the prod governance layer, then the prod workspace layer.

Use `make generate ENV=prod` instead of `make promote` only when prod needs a fully separate LLM-generated design.

### 3. Create a second independent environment for another business unit

Use this when a second business unit needs its own groups, governance, Genie space, and possibly its own tables, rather than a promotion of `dev`.

Example with a new environment named `bu2`:

```bash
make setup ENV=bu2
vi envs/bu2/auth.auto.tfvars
vi envs/bu2/env.auto.tfvars
# Example:
#   uc_catalog = "bu2_catalog"
#   uc_tables  = ["finance.*", "ops.*"]

make generate ENV=bu2
vi envs/bu2/generated/abac.auto.tfvars
vi envs/bu2/generated/masking_functions.sql
make validate-generated ENV=bu2
make apply ENV=bu2
```

When to use this flow instead of promotion:

- The business unit has different tables or schemas
- The business unit needs different groups
- The Genie prompts, measures, or benchmarks should be generated independently
- The governance design should evolve separately from `dev`

### 4. Destroy and reset

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

- `make destroy ENV=<workspace>` destroys only that environment's workspace and `data_access` layers.
- `make destroy ENV=account` destroys shared account resources such as groups and tag policy definitions.
- Destroying one environment does not destroy other environments.
- `make clean` removes local state and generated artifacts but keeps your checked-in config files.
- `make clean-all` removes the full `envs/` tree, including environment configs and local state.

## Artifact Ownership

The quickstart edits files in `envs/<env>/`, while Terraform itself runs from fixed roots in `roots/account`, `roots/data_access`, and `roots/workspace`. Make passes the correct `-var-file` inputs for you and keeps the split config synchronized.

### Layer model

| Layer | Path | Owns | Does not own |
| ----- | ---- | ---- | ------------ |
| Account | `envs/account/` | Account groups, optional group membership, tag policy definitions | Masking functions, FGAC policies, Genie resources |
| Data access | `envs/<env>/data_access/` | Env-scoped tag assignments, masking functions, FGAC policies, catalog grants | Account tag policy definitions, workspace entitlements, Genie lifecycle |
| Workspace | `envs/<env>/` | Workspace assignment, entitlements, optional warehouse, optional Genie space + ACLs | Account groups, tag policies, FGAC policies |

### Directory contract

- `envs/account/` is the only shared layer across all environments.
- `envs/<workspace>/data_access/` is isolated per environment.
- `envs/<workspace>/` is also isolated per environment and owns generation-time workspace artifacts.
- Root `scripts/`, root `*.py`, `roots/`, and `modules/` are shared implementation code and should not be copied into `envs/`.

| File | What goes here | Tracked in git? |
| ---- | -------------- | --------------- |
| `roots/account/main.tf` | Stable Terraform root for account identities | **Yes** |
| `roots/data_access/main.tf` | Stable Terraform root for env-scoped governance | **Yes** |
| `roots/workspace/main.tf` | Stable Terraform root for workspace-local resources | **Yes** |
| `envs/<env>/auth.auto.tfvars` | Workspace credentials only (account ID, client ID/secret, workspace) | No (secrets) |
| `envs/<env>/env.auto.tfvars` | `uc_catalog`, `uc_tables`, `sql_warehouse_id`, `genie_space_id` | **Yes** |
| `envs/<env>/generated/` | Workspace-only generated draft outputs from `make generate` | No |
| `envs/<env>/ddl/` | Workspace-only local or fetched DDL snapshots used during generation | No |
| `envs/account/abac.auto.tfvars` | Shared account-owned config: `groups`, optional `group_members`, `tag_policies` | **Yes** |
| `envs/<env>/data_access/abac.auto.tfvars` | Env-scoped governance config: `groups`, tag assignments, FGAC policies | **Yes** |
| `envs/<env>/data_access/masking_functions.sql` | Env-scoped masking SQL deployed by the governance layer | **Yes** |
| `envs/<env>/abac.auto.tfvars` | Workspace-owned config: group lookups and Genie config only | **Yes** |

Examples:

- `envs/dev/auth.auto.tfvars`
- `envs/dev/env.auto.tfvars`
- `envs/dev/abac.auto.tfvars`


### `auth.auto.tfvars` — credentials (gitignored)

```hcl
databricks_account_id    = "..."
databricks_client_id     = "..."
databricks_client_secret = "..."
databricks_workspace_id  = "..."
databricks_workspace_host = "https://..."
```

Configure these values in `envs/<env>/auth.auto.tfvars`. By default, `make setup` also creates `envs/account/auth.auto.tfvars` and `envs/<env>/data_access/auth.auto.tfvars` as links to the same workspace auth file, so one service principal can drive all three layers. Replace either shared-layer file only if account or governance resources need different credentials.

Where to find each field:

| Field | What it is | Where to find it |
| ----- | ---------- | ---------------- |
| `databricks_account_id` | Databricks account ID | Account Console. You can also copy it from the account selector or account URL. |
| `databricks_client_id` | Service principal application/client ID | Account Console -> User management -> Service principals -> choose your service principal. |
| `databricks_client_secret` | OAuth secret for that service principal | Same service principal record. Create a new OAuth secret / client secret and copy it once when shown. |
| `databricks_workspace_id` | Numeric target workspace ID | Account Console -> Workspaces -> choose the workspace, or copy the `o=<workspace_id>` value from the workspace URL. |
| `databricks_workspace_host` | Workspace browser/API base URL | Open the target workspace in your browser and copy the base URL, e.g. `https://dbc-....cloud.databricks.com/`. |

Service principal requirements:
- `Account Admin` to create account groups and assign them to the workspace
- `Workspace Admin` to configure workspace entitlements, warehouses, and Genie resources
- `Metastore Admin` to create tag policies, FGAC policies, grants, and masking functions

If you already use the Databricks CLI, the same service principal details are often visible in the account console pages you used to create the CLI credentials. This quickstart intentionally stores them in `auth.auto.tfvars` instead of reading `~/.databrickscfg`.

### `env.auto.tfvars` — environment config (checked in)

```hcl
# Only the catalog name changes between dev, staging, and prod.
# Schema and table names are assumed stable (Databricks best practice).
uc_catalog = "dev_catalog"

# Schema-relative references — no catalog prefix, same across all environments.
# Use schema.* to include all tables in a schema.
uc_tables = ["sales.customers", "sales.orders", "finance.*"]

sql_warehouse_id = ""   # set to reuse existing, or leave empty to auto-create
genie_space_id   = ""   # set for existing space, or leave empty to auto-create
```

> **Migration note for existing users:** The old single `uc_tables = ["catalog.schema.table"]` format is retired. Split existing entries into `uc_catalog = "catalog"` and schema-relative `uc_tables = ["schema.table"]`.

Only `envs/account/env.auto.tfvars` should include `manage_groups = true`. Workspace and `data_access` env files should omit that field and rely on their built-in lookup-only defaults.

### `abac.auto.tfvars` — ABAC + Genie config (auto-generated)

Generated by `make generate` in `envs/<env>/generated/`. `make promote` then splits it into:
- `envs/account/abac.auto.tfvars` for shared groups, optional group membership, and **tag policy definitions** (account-scoped, shared across all environments)
- `envs/<env>/data_access/abac.auto.tfvars` for env-scoped tag assignments, FGAC policies, and group lookup names
- `envs/<env>/data_access/masking_functions.sql` for env-scoped masking UDF deployment
- `envs/<env>/abac.auto.tfvars` for workspace group lookup names and Genie config

Tune the generated draft before applying. See `generated/TUNING.md` for guidance.

## Genie Space

Managed automatically based on `genie_space_id` in `env.auto.tfvars`:


| `genie_space_id` | `uc_catalog` + `uc_tables` | What happens on `make apply`                                                              |
| ---------------- | -------------------------- | ----------------------------------------------------------------------------------------- |
| Empty            | Both non-empty             | Auto-creates a Genie Space from the resolved tables, sets CAN_RUN ACLs, trashes on `make destroy` |
| Set              | Any                        | Applies CAN_RUN ACLs to the existing space                                                |
| Empty            | Either empty               | No Genie Space action                                                                     |


When `make generate` creates the ABAC config, it also generates Genie Space config in `abac.auto.tfvars`:


| Variable                  | Purpose                                                                                                  |
| ------------------------- | -------------------------------------------------------------------------------------------------------- |
| `genie_space_title`       | AI-generated title for the Genie Space (e.g., "Financial Compliance Analytics")                          |
| `genie_space_description` | 1–2 sentence summary of the space's scope and audience                                                   |
| `genie_sample_questions`  | Natural-language questions shown as conversation starters in the Genie UI                                |
| `genie_instructions`      | Domain-specific guidance including business defaults (e.g., "customer" = active by default)              |
| `genie_benchmarks`        | Unambiguous ground-truth question + SQL pairs for evaluating Genie accuracy                              |
| `genie_sql_filters`       | Default WHERE clauses (e.g., active customers, completed transactions) that guide Genie's SQL generation |
| `genie_sql_measures`      | Standard aggregate metrics (e.g., total revenue, average risk score)                                     |
| `genie_sql_expressions`   | Computed dimensions (e.g., transaction year, age bucket)                                                 |
| `genie_join_specs`        | Table relationships with join conditions (e.g., accounts to customers on CustomerID)                     |


All nine fields are included in the `serialized_space` when a new Genie Space is created. Review and tune them in `generated/abac.auto.tfvars` alongside the ABAC policies before applying.

## Make Targets


| Target                    | Description                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------ |
| `make setup`              | Prepare `envs/account`, `envs/<env>/data_access`, and the selected `envs/<env>`           |
| `make init-env`           | Explicitly bootstrap env directories and default config files                              |
| `make generate`           | Run `generate_abac.py` in the selected workspace environment                               |
| `make validate-generated` | Validate `envs/<env>/generated/` files after tuning                                        |
| `make validate`           | Validate the selected split config (`account`, `data_access`, or `workspace`)              |
| `make promote`            | Split `generated/` into account + data_access + workspace configs (same-env)               |
| `make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog` | Cross-env promote: remap catalog references from dev to prod, then split |
| `make plan`               | Run `terraform plan` in the selected layer root                                            |
| `make apply`              | For `ENV=<workspace>`: promote, then apply account -> data_access -> workspace             |
| `make import`             | Import resources into the selected layer state (`account`, `data_access`, or workspace)    |
| `make migrate-state`      | Move legacy state into the new module/layer addresses                                      |
| `make destroy`            | Destroy only the selected layer state                                                      |
| `make clean`              | Remove generated files and Terraform state for one env directory                           |
| `make clean-all`          | Remove all `envs/` workspaces                                                              |
| `make migrate-root-to-env`| Move an old root-based workspace into `envs/<env>/`                                        |

Notes:
- `make plan ENV=<workspace>` assumes the referenced groups already exist, either because `make apply ENV=account` has run or because those groups were imported / are IDP-synced already.


## Importing Existing Resources (Brownfield)

If groups, tag policies, tag assignments, or FGAC policies already exist in Databricks, import them so Terraform can manage them without "already exists" errors:

```bash
make import ENV=account      # import account groups + tag policies into module.account
make import                  # import env-scoped governance + workspace-local resources for ENV=dev
make import ENV=prod         # import env-scoped governance + workspace-local resources for ENV=prod

cd envs/account && ../../scripts/import_existing.sh --groups-only --dry-run
cd envs/account && ../../scripts/import_existing.sh --tags-only --dry-run   # tag policies live in account
cd envs/dev/data_access && ../../../scripts/import_existing.sh --fgac-only
cd envs/dev/data_access && ../../../scripts/import_existing.sh --tag-assignments-only
```

### Brownfield workflow

For environments with existing ABAC infrastructure:

```bash
make generate
vi envs/dev/generated/masking_functions.sql
vi envs/dev/generated/abac.auto.tfvars
make promote
make import ENV=account
make import
make migrate-state           # only needed if this env already has old mixed state
make plan
make apply
```

## Troubleshooting

### "Provider produced inconsistent result after apply" (tag policies)

A known Databricks provider bug: the API can reorder tag policy values after creation, causing a Terraform state mismatch. **The tag policies themselves are usually created correctly**; the failure is in provider/state reconciliation.

`make apply` reduces this significantly by:
- running `make sync-tags` through the Databricks SDK against the shared **account** layer before applying it
- keeping `ignore_changes = [values]` on `databricks_tag_policy`

That said, you may still occasionally see this error during the account apply, especially when creating or adopting policies for the first time. In that case:
1. Re-run `make apply`
2. If it still fails, import the affected policies into the account state and retry

Manual recovery:

```bash
cd envs/account

python3 -c "import hcl2; d=hcl2.load(open('abac.auto.tfvars')); [print(tp['key']) for tp in d.get('tag_policies',[])]" | \
  while read key; do
    ../../scripts/terraform_layer.sh account account state-rm "module.account.databricks_tag_policy.policies[\"$key\"]" 2>/dev/null || true
    ../../scripts/terraform_layer.sh account account import "module.account.databricks_tag_policy.policies[\"$key\"]" "$key" || true
  done

make apply
```

### "already exists"

Resources (groups, tag policies) already exist in Databricks. Import them so Terraform can manage them:

```bash
make import ENV=dev
```

## Advanced Usage

### Generation options

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

Pass arguments via Make:

```bash
make generate GENERATE_ARGS='--groups "Finance_Analyst,Clinical_Staff"'
```

### IDP-synced groups

When groups are managed by an Identity Provider (e.g., Okta, Azure AD), keep group ownership out of workspace and `data_access` envs entirely. Those layers already look groups up by name. The only place that mentions `manage_groups` is `envs/account/env.auto.tfvars`, where it remains `true` if Terraform should own account-level group creation.

This changes behavior:
- Groups are **looked up by name** instead of created
- Workspace assignment and entitlements still run (idempotent)
- Any account-level `group_members` should stay empty in `envs/account/abac.auto.tfvars` (IDP manages membership)

Use `--groups` to tell the LLM your exact IDP group names:

```bash
make generate GENERATE_ARGS='--groups "acme-finance-readers,acme-clinical-staff,acme-compliance"'
```

The LLM uses these exact names in generated FGAC policies, tag assignments, and Genie Space ACLs — no manual renaming needed.

### ABAC-only mode (no Genie Space)

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
# uc_catalog = ""   # (clear catalog too when skipping workspace Genie)

# 5. Promote + apply shared governance and workspace entitlements
make promote
make apply
```

Overall ABAC-only flow:
1. `make generate` creates a full draft in `envs/<env>/generated/`
2. You tune tags, FGAC policies, and masking SQL there
3. `make promote` moves governance into `envs/<env>/data_access/` and leaves only workspace/Genie config in `envs/<env>/`
4. `make apply` deploys account identities, shared data-access resources, and workspace entitlements

With `uc_tables = []` (and `uc_catalog = ""`) and `genie_space_id = ""`, the workspace layer skips Genie creation while the account layer still creates tag policies and the env-scoped `data_access` layer deploys masking UDFs, assigns tags, and creates FGAC policies.

### Existing masking functions

If you have pre-existing masking SQL UDFs, the tool can incorporate them:

1. Run `make generate` — the AI generates `masking_functions.sql` and `abac.auto.tfvars` in `envs/dev/generated/`
2. Edit `envs/dev/generated/masking_functions.sql` — replace generated UDF definitions with your existing functions (keep the `CREATE OR REPLACE FUNCTION` syntax, update the fully-qualified names)
3. The FGAC policies in `envs/dev/generated/abac.auto.tfvars` reference functions by name — update `function_name`, `function_catalog`, and `function_schema` to match your existing UDFs
4. Run `make apply`

### Multi-Environment Setup

Use the flows in `Recommended Flows` for the day-to-day workflow. This section is only the mental model for how files are laid out across multiple environments.

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
  account/                    # shared state — account module only
    auth.auto.tfvars          # defaults to workspace auth symlink; replace if needed
    env.auto.tfvars           # account-specific settings; includes manage_groups = true
    abac.auto.tfvars          # groups, optional group_members, and tag_policies
    terraform.tfstate         # local account-layer state, lock, fingerprints

  dev/                        # dev workspace module state
    auth.auto.tfvars          # workspace SP credentials
    env.auto.tfvars           # uc_catalog = "dev_catalog", uc_tables = ["schema.*"]
    data_access/              # dev governance state
      auth.auto.tfvars        # defaults to ../auth.auto.tfvars; replace if needed
      env.auto.tfvars         # defaults to ../env.auto.tfvars
      abac.auto.tfvars        # env-scoped governance config
      masking_functions.sql   # env-scoped masking SQL
      terraform.tfstate       # local governance-layer state, lock, fingerprints
    abac.auto.tfvars          # groups lookup + Genie config only
    ddl/                      # workspace-local manual or fetched DDL snapshots
    generated/                # workspace-local generated draft outputs
    .genie_space_id           # workspace-local Genie lifecycle marker
    terraform.tfstate         # local workspace-layer state, lock, fingerprints

  prod/                       # prod workspace module state
    auth.auto.tfvars
    env.auto.tfvars           # uc_catalog = "prod_catalog", uc_tables = ["schema.*"]
    data_access/
      auth.auto.tfvars
      env.auto.tfvars
      abac.auto.tfvars
      masking_functions.sql
      terraform.tfstate
    abac.auto.tfvars          # groups lookup + Genie config only
    ddl/
    generated/
    .genie_space_id
    terraform.tfstate

roots/
  account/                    # Terraform root that calls modules/account
  data_access/                # Terraform root that calls modules/data_access
  workspace/                  # Terraform root that calls modules/workspace
```

Each env keeps its own Terraform state and local artifacts. `account` is the only shared layer; governance and workspace files are isolated per environment under `envs/<env>/data_access/` and `envs/<env>/`.

**Catalog-boundary assumption:**

Databricks best practice: the catalog name is the environment boundary, while schema and table names stay stable across dev/staging/prod. The quickstart encodes this directly:

- `uc_catalog` in `env.auto.tfvars` holds the environment-specific catalog name
- `uc_tables` holds schema-relative refs (`schema.table`) that are the same in every environment
- `make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog` swaps `dev_catalog` for `prod_catalog` everywhere in the generated config in one step — no per-table mapping needed

**Governance promotion across environments:**

- `make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog` creates `envs/prod/env.auto.tfvars`, remaps catalog references throughout the generated config, and splits it into account + data_access + workspace layers
- `make promote` with no `DEST_ENV` re-splits the current environment's `generated/` after hand edits
- `make sync-tags` runs against the shared account layer because tag policy definitions are account-scoped
- `make generate ENV=<env>` is still the right choice for a fully independent environment such as a second business unit

**Migrating an existing root-based workspace:**

If you already used the old root-local workflow, migrate it once before using the new default env dispatch:

```bash
make migrate-root-to-env ENV=dev
make migrate-state ENV=dev
```

That moves your root working files into `envs/dev/` and rewrites any legacy top-level Terraform addresses into the new layered module addresses so future `make generate` / `make apply` commands continue from the same environment layout without forced recreation.

### Examples

A pre-built finance demo is available in `examples/finance/` — copy the tfvars and SQL files to try without AI generation. Sample healthcare DDLs are in `examples/healthcare/ddl/` for testing `make generate`.

## Roadmap

- Unity Catalog metrics in Genie
- Multi Genie Space support
- Multi data steward / user support
- AI-assisted tuning and troubleshooting
- Auto-detect and import existing policies

