# Flows

This document covers the main day-to-day workflows:

- quickstart your first `dev` environment
- add a new Genie Space without touching existing tuned configs (incremental generation)
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

vi envs/dev/env.auto.tfvars
# Define your Genie Spaces. All table names must be fully qualified (catalog.schema.table).
#
# Example:
#   genie_spaces = [
#     {
#       name     = "Finance & Clinical Analytics"
#       uc_tables = [
#         "dev_catalog.finance.transactions",
#         "dev_catalog.clinical.encounters",
#       ]
#     },
#   ]
#
# Optional: replace envs/account/auth.auto.tfvars or
# envs/dev/data_access/auth.auto.tfvars if shared layers need different credentials.

make generate
vi envs/dev/generated/abac.auto.tfvars
# Review and iterate on the generated governance and Genie config:
# - groups
# - tag policies
# - tag assignments
# - FGAC policies
# - genie_space_configs (title, instructions, benchmarks, filters, measures per space)

vi envs/dev/generated/masking_functions.sql
# Review and iterate on the generated masking and row-filter functions.

make validate-generated
make apply
```

What happens:

1. `make setup` creates `envs/account/`, `envs/dev/data_access/`, and `envs/dev/`
2. `make generate` fetches DDLs from Unity Catalog, calls the LLM, and writes a draft into `envs/dev/generated/`
3. You tune the generated governance and Genie config
4. `make apply` splits the generated draft into account, data-access, and workspace artifacts, then applies all three layers

### Genie Space modes

The tool operates in two modes depending on whether `genie_space_id` is set in `env.auto.tfvars`:

| `genie_space_id` | `uc_tables` | What the tool does |
| --- | --- | --- |
| **empty** (default) | provided | Creates and fully manages the space: title, benchmarks, instructions, group ACLs, full lifecycle. |
| **set** | provided | Uses those tables for ABAC generation; applies group ACLs only. Space content not modified. |
| **set** | **omitted** | `make generate` queries the Genie API to discover tables and parse the existing config verbatim. Generates ABAC from those tables. Pushes `genie_space_configs` back on every apply. Never creates or deletes the space. |

### Multiple Genie Spaces and multiple catalogs

You can define multiple spaces in one environment, and each space can draw tables from multiple catalogs:

```hcl
# sql_warehouse_id works at two levels:
#   top-level          → shared fallback for all spaces (empty = auto-create serverless)
#   inside genie_spaces → per-space override; omit to use the top-level warehouse
genie_spaces = [
  {
    name             = "Finance Analytics"
    sql_warehouse_id = ""           # optional: overrides the top-level warehouse for this space
    uc_tables = [
      "dev_fin.finance.transactions",
      "dev_fin.finance.customers",
      "dev_fin.accounts.*",
    ]
  },
  {
    name     = "Clinical Analytics"
    uc_tables = [
      "dev_clinical.clinical.encounters",
      "dev_clinical.clinical.diagnoses",
    ]
  },
]

sql_warehouse_id = ""   # shared fallback warehouse
```

The `name` is the human-readable Genie Space title shown in the Databricks UI. It also:
- Links each space's infrastructure settings (in `env.auto.tfvars`) to its semantic config (in `abac.auto.tfvars` under `genie_space_configs`) — the keys must match exactly
- Determines the internal Terraform resource key (sanitized to lowercase alphanumeric + underscores, e.g. `"Finance Analytics"` → `finance_analytics`)

Renaming a space causes Terraform to destroy and re-create it.

The generated `abac.auto.tfvars` uses a `genie_space_configs` map keyed by the same name string. The `title` field within each config entry is optional — if omitted, the space `name` is used as the title:

```hcl
genie_space_configs = {
  "Finance Analytics" = {
    # title is optional — defaults to "Finance Analytics" from env.auto.tfvars
    benchmarks   = [{ question = "...", sql = "SELECT ... FROM dev_fin.finance.transactions" }]
    join_specs   = [...]
    # ...
  }
  "Clinical Analytics" = {
    description = "Clinical encounter data for healthcare staff."
    # ...
  }
}
```

### Attaching to an existing Genie Space

If a Genie Space was already configured in the Databricks UI by a data team, you can bring it under full governance without touching its content. Set `genie_space_id` and omit `uc_tables` — `make generate` will query the Genie API to discover what tables the space uses and generate all governance from those:

```bash
vi envs/dev/env.auto.tfvars
```

```hcl
genie_spaces = [
  {
    genie_space_id = "01ef7b3c2a4d5e6f"   # only required field; find in the Genie Space URL
    # name omitted     → Terraform key defaults to genie_space_id
    # uc_tables omitted → make generate fetches them from the Genie API
  },
]
```

```bash
make generate   # queries Genie Space API → fetches DDLs → LLM generates ABAC + benchmarks
```

During `make generate` you will see:

```
  Genie Space 'Executive Dashboard' has no uc_tables — querying API...
    Querying Genie Space 01ef7b3c2a4d5e6f for table list...
    Discovered 4 table(s): prod.finance.transactions, prod.finance.customers, ...

  Auto-discovered tables from existing Genie Space(s):
    - prod.finance.transactions
    - prod.finance.customers
    ...

  NOTE: Add these tables to data_access/env.auto.tfvars so that
  UC grants and masking functions are applied to them as well.
```

After generation, copy the discovered tables into `data_access/env.auto.tfvars`:

```hcl
# data_access/env.auto.tfvars
uc_tables = [
  "prod.finance.transactions",
  "prod.finance.customers",
  # ... (as printed by make generate)
]
```

Then apply as normal:

```bash
make apply
```

What the tool manages in this mode:

| Area | Managed by this tool |
| --- | --- |
| Group ACLs (CAN_RUN on the space) | **Yes** — driven by `abac.auto.tfvars` groups |
| Workspace group assignments and entitlements | **Yes** |
| ABAC config, masking, grants | **Yes** — generated from the discovered table set |
| Space title, description, benchmarks, instructions | **No** — preserved exactly as configured in the UI |
| SQL warehouse used by the space | **No** — preserved as configured in the UI |
| Space lifecycle (create / destroy) | **No** — the space is never deleted by `make destroy` |

You can mix attached and auto-created spaces in the same environment:

```hcl
genie_spaces = [
  {
    genie_space_id = "01ef7b3c2a4d5e6f"    # pre-existing — name optional, tables auto-discovered
  },
  {
    name      = "Ops Analytics"             # no ID — tool creates and fully manages this one
    uc_tables = ["dev_catalog.ops.incidents", "dev_catalog.ops.sla_metrics"]
  },
]
```

---

## 2. Add a new Genie Space (incremental generation)

Use this when you already have a working `dev` environment with Space A fully tuned and applied, and you want to add Space B — without re-running the LLM over Space A's tables or overwriting its hand-tuned benchmarks, masking functions, or FGAC policies.

### How per-space generation works

After the first `make generate`, the tool creates a per-space directory structure alongside the assembled output:

```
envs/dev/generated/
  spaces/
    finance_analytics/         # bootstrapped by make generate (full run)
      abac.auto.tfvars         # genie_space_configs entry for this space
    clinical_analytics/
      abac.auto.tfvars
  abac.auto.tfvars             # assembled — what make apply uses (unchanged interface)
  masking_functions.sql        # assembled
  TUNING.md
```

When you run `make generate SPACE="Space B"`:
- Only Space B's tables are fetched from Unity Catalog
- The LLM generates config only for Space B (genie_space_configs, tag_assignments, fgac_policies, masking functions)
- The LLM is instructed to skip groups and tag_policies — those are shared state, already established
- Existing groups are auto-loaded from `envs/account/abac.auto.tfvars` so the LLM reuses them
- The result is written to `generated/spaces/space_b/`
- The assembled `generated/abac.auto.tfvars` is **patched** (not replaced): Space B's entries are added; Space A's content is untouched

### When to use per-space generation vs. full generation

| Situation | Command |
| --------- | ------- |
| First time setting up an environment | `make generate` |
| Adding a new space (Space B) without touching Space A | `make generate SPACE="Space B"` |
| Re-tuning an existing space from scratch | `make generate SPACE="Finance Analytics"` |
| Adding new groups or changing shared tag policies | `make generate` (full — reviews all spaces) |
| Recovering from a corrupt assembled config | `make generate` (full — rewrites from scratch) |

**Note:** Full `make generate` (no `SPACE=`) always replaces the assembled `generated/abac.auto.tfvars` entirely. Only use it when you want to regenerate everything, or for the very first run.

### Step-by-step: add Space B to a live environment

```bash
# 1. Add Space B to env.auto.tfvars
vi envs/dev/env.auto.tfvars
```

```hcl
genie_spaces = [
  {
    name     = "Finance Analytics"    # Space A — already deployed and tuned
    uc_tables = [
      "dev_fin.finance.transactions",
      "dev_fin.finance.customers",
    ]
  },
  {
    name     = "Clinical Analytics"   # Space B — new
    uc_tables = [
      "dev_clinical.clinical.encounters",
      "dev_clinical.clinical.diagnoses",
    ]
  },
]
```

```bash
# 2. Generate ONLY Space B's config — Space A's tuned config is preserved
make generate SPACE="Clinical Analytics"

# During generation you will see:
#   Mode: per-space — 'Clinical Analytics'
#   Auto-loaded N group(s) from account config.  ← reuses Space A's groups
#   ...
#   Merging generated/spaces/clinical_analytics/ into generated/...
#     genie_space_configs: updated entry 'Clinical Analytics'
#     tag_assignments: added N new entry/entries
#     fgac_policies:   added N new entry/entries
#     masking_functions.sql: appended N new function(s)

# 3. Review the per-space draft and the assembled output
vi envs/dev/generated/spaces/clinical_analytics/abac.auto.tfvars
vi envs/dev/generated/abac.auto.tfvars   # assembled — verify Space A is unchanged

# 4. Validate and apply
make validate-generated
make apply
```

### Shared state (groups, tag_policies)

Per-space generation does **not** modify groups or tag_policies. These are shared governance foundations that apply across all spaces. The LLM reuses existing groups (loaded from `envs/account/abac.auto.tfvars`) rather than inventing new ones.

If you genuinely need new groups for Space B, run full `make generate` (no `SPACE=`). It regenerates groups from all tables across all configured spaces, and you review the delta before applying.

---

After `dev` is working, most teams choose one of these two paths.

### 3a. Promote `dev` to `prod`

Use this when `prod` should reuse the same table set, groups, and governance design as `dev`, but point at different catalog names.

```bash
make promote SOURCE_ENV=dev DEST_ENV=prod \
  DEST_CATALOG_MAP="dev_catalog=prod_catalog"
vi envs/prod/auth.auto.tfvars
# Enter the prod workspace credentials.

make apply ENV=prod
```

For multiple catalogs across spaces, list a mapping for every source catalog:

```bash
make promote SOURCE_ENV=dev DEST_ENV=prod \
  DEST_CATALOG_MAP="dev_fin=prod_fin,dev_clinical=prod_clinical"
```

**How `DEST_CATALOG_MAP` works:**

- Comma-separated `src_catalog=dest_catalog` pairs
- The promote command auto-detects all source catalog names from `genie_spaces[*].uc_tables`
- Every detected catalog must have a mapping — the command fails clearly if any are missing or if an unknown catalog is referenced

**Validation examples:**

```
# Missing mapping
ERROR: DEST_CATALOG_MAP is missing mappings for: dev_clinical
       Source catalogs detected in dev/env.auto.tfvars: dev_fin, dev_clinical

  make promote SOURCE_ENV=dev DEST_ENV=prod \
    DEST_CATALOG_MAP="dev_fin=prod_fin,dev_clinical=<dest_name>"

# Typo in source catalog name
ERROR: DEST_CATALOG_MAP references unknown source catalogs: dev_financ
       Check for typos. Source catalogs: dev_fin, dev_clinical
```

What promote does:

1. Validates `DEST_CATALOG_MAP` against detected source catalogs — fails before touching any files if incomplete
2. Writes `envs/prod/env.auto.tfvars` with `genie_spaces` list, substituting catalog names per the map
3. Remaps catalog references in the generated `abac.auto.tfvars` and `masking_functions.sql`
4. Splits the remapped config into:
   - `envs/account/abac.auto.tfvars`
   - `envs/prod/data_access/abac.auto.tfvars`
   - `envs/prod/data_access/masking_functions.sql`
   - `envs/prod/abac.auto.tfvars`
5. `make apply ENV=prod` applies the shared account layer, then the prod governance layer, then the prod workspace layer

Use `make generate ENV=prod` instead of `make promote` only when prod needs a fully separate LLM-generated design.

### 3b. Create a second independent environment for another business unit

Use this when a second business unit needs its own groups, governance, Genie spaces, and possibly its own tables, rather than a promotion of `dev`.

Example with a new environment named `bu2`:

```bash
make setup ENV=bu2
vi envs/bu2/auth.auto.tfvars
# Enter the BU workspace credentials.

vi envs/bu2/env.auto.tfvars
# Define the BU's genie_spaces with its own catalog and table list.
# Example:
#   genie_spaces = [
#     {
#       name     = "Operations Analytics"
#       uc_tables = ["bu2_catalog.ops.*", "bu2_catalog.finance.summary"]
#     },
#   ]

make generate ENV=bu2
vi envs/bu2/generated/abac.auto.tfvars
# Review and iterate on generated policies, groups, and Genie config.

vi envs/bu2/generated/masking_functions.sql
# Review and iterate on generated masking functions.

make validate-generated ENV=bu2
make apply ENV=bu2
```

When to use this flow instead of promotion:

- The business unit has different tables, schemas, or catalogs
- The business unit needs different groups or governance rules
- The Genie prompts, measures, or benchmarks should be generated independently
- The governance design should evolve separately from `dev`

## 4. Destroy and reset

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
   - `env.auto.tfvars`: one or more Genie Space definitions with fully-qualified table names, an optional shared warehouse, and optional per-space warehouse overrides

2. **`make generate` creates a draft**

   - fetches DDLs from Unity Catalog
   - sends the prompt plus DDLs to the configured LLM
   - writes draft outputs into `envs/<env>/generated/`

3. **You review, then `make apply` deploys**

   - tune `generated/abac.auto.tfvars` (groups, policies, `genie_space_configs`)
   - tune `generated/masking_functions.sql`
   - run `make validate-generated`
   - run `make apply`, which splits the draft into layered configs and applies them

### Generated Draft Outputs

| File | What it contains |
| ---- | ---------------- |
| `envs/<env>/generated/abac.auto.tfvars` | **Assembled output** — groups, tag policies, tag assignments, FGAC policies, and `genie_space_configs` (one entry per Genie Space). This is what `make apply` reads. |
| `envs/<env>/generated/masking_functions.sql` | **Assembled output** — all SQL masking and row-filter functions across all spaces. |
| `envs/<env>/generated/spaces/<key>/abac.auto.tfvars` | Per-space draft for a single space — bootstrapped by full generation, or written by `make generate SPACE="..."`. |
| `envs/<env>/generated/spaces/<key>/masking_functions.sql` | Per-space masking functions for a single space — written by `make generate SPACE="..."`. |

### What `make apply` creates

| Layer | Creates in Databricks |
| ----- | --------------------- |
| Account | Account groups, optional group membership, tag policy definitions |
| Data access | Tag assignments, masking functions, FGAC policies, catalog grants |
| Workspace | Workspace assignment, entitlements, optional warehouse, Genie Spaces (one per `genie_spaces` entry) and ACLs |

In practice, the flow is:

```text
inputs -> make generate -> review generated/ -> make validate-generated -> make apply
```
