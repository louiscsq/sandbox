# Integration Testing

This guide covers the automated integration test scenarios that validate the
playbooks documented in `docs/playbook.md`, the `setup_test_data.py` helper, and the
`run_integration_tests.py` test runner.

---

## Recommended Testing Workflow

### One command for CI/CD

For automated pipelines (PR checks, nightly runs), use `make test-ci`:

```bash
make test-ci
```

This single command runs the full pipeline in order:

1. **Unit tests** — fast Python-only checks, no cloud resources needed
2. **Provision** — fresh isolated Databricks workspace + metastore (~10–15 min)
3. **Integration tests** — all 8 scenarios (~90 min)
4. **Teardown** — always runs, even if tests fail, so no cloud resources are left behind

Exit code is non-zero if any phase fails. Teardown is **always** executed.

Options:

```bash
# Use a custom credentials file (useful for CI secrets injection)
make test-ci ACCOUNT_ADMIN_ENV=/path/to/credentials.env

# Run only one scenario (faster iteration)
make test-ci SCENARIO=quickstart

# Pin a specific SQL warehouse
make test-ci WAREHOUSE_ID=abc123
```

**GitHub Actions example:**

```yaml
- name: Integration tests
  run: make test-ci
  env:
    # Write the credentials file from a secret, then pass the path
    ACCOUNT_ADMIN_ENV: ${{ runner.temp }}/account-admin.env
```

### Manual step-by-step (for local development)

Use unit tests first to catch logic bugs quickly (< 1 second, no credentials
required), then provision a **fresh isolated environment** for integration tests
to avoid stale quota counter issues in a shared metastore.

```
make test-unit                              # fast — pure Python, no LLM/Terraform/Databricks
       ↓ (all pass)
python scripts/provision_test_env.py provision   # ~10-15 min — creates fresh workspace + metastore
       ↓
python scripts/run_integration_tests.py          # slow — deploys real resources (~hours)
       ↓
python scripts/provision_test_env.py teardown    # wipe the environment when done
```

### Why provision a fresh environment?

Databricks metastore-wide FGAC policy quotas use an **eventually consistent
counter** that can lag behind actual policy deletions by several minutes.
In a long-lived shared metastore, the counter can accumulate drift and
incorrectly block new policy creation even when no policies actually exist.
Provisioning a fresh workspace + metastore for each test run gives a clean
counter that always starts at zero.

### Unit Tests

The `tests/` directory contains pytest-based unit tests for the core Python
functions — all autofix functions in `generate_abac.py` and all validation
functions in `validate_abac.py`.

**Run:**

```bash
# Install deps once (if not already installed)
pip install pytest python-hcl2

# Run all 60+ unit tests (~1 second, no Databricks connection needed)
make test-unit

# Or invoke pytest directly for richer output
python3 -m pytest tests/ -v
python3 -m pytest tests/test_generate_abac.py -v   # autofix functions only
python3 -m pytest tests/test_validate_abac.py -v   # validation functions only
python3 -m pytest tests/ -k "TagPolicies" -v        # filter by name
```

**What is tested:**

| Test file | Functions covered |
|---|---|
| `tests/test_generate_abac.py` | `fix_hcl_syntax`, `autofix_tag_policies`, `autofix_invalid_tag_values`, `autofix_undefined_tag_refs`, `autofix_missing_fgac_policies`, `autofix_fgac_policy_count` |
| `tests/test_validate_abac.py` | `validate_groups`, `validate_tag_policies`, `validate_tag_assignments`, `validate_fgac_policies`, `parse_sql_functions`, `parse_sql_function_arg_counts`, `_condition_matches_tags` |

Unit tests catch the most common failure categories without incurring the
cost of a full LLM + Terraform run:

- LLM output contains missing commas between HCL objects → `fix_hcl_syntax`
- LLM uses a tag value not in the allowed list → `autofix_tag_policies`
- LLM generates an assignment with a typo'd value → `autofix_invalid_tag_values`
- LLM references a tag key that was never defined → `autofix_undefined_tag_refs`
- An uncovered sensitive column is left without an FGAC policy → `autofix_missing_fgac_policies`
- Too many FGAC policies for one catalog → `autofix_fgac_policy_count`

---

## Provisioning a Fresh Integration-Test Environment

`scripts/provision_test_env.py` creates a brand-new serverless Databricks
workspace and Unity Catalog metastore specifically for integration testing, then
writes all `auth.auto.tfvars` files so the test runner uses that environment.

### One-time setup

```bash
# Copy the example credentials file
cp scripts/account-admin.env.example scripts/account-admin.env
```

Fill in `scripts/account-admin.env`:

| Key | Where to find it |
|---|---|
| `DATABRICKS_ACCOUNT_ID` | Account Console → top-right menu → Account ID |
| `DATABRICKS_CLIENT_ID` | Account Console → User Management → Service Principals → `<SP>` → Application ID |
| `DATABRICKS_CLIENT_SECRET` | Same SP → OAuth Secrets → Generate Secret |
| `DATABRICKS_AWS_REGION` | AWS region for the new workspace (e.g. `ap-southeast-2`) |
| `DATABRICKS_S3_BUCKET` | An existing S3 bucket you own (e.g. `s3://my-bucket`) — **must exist before running provision** (see below) |
| `AWS_ACCESS_KEY_ID` | AWS credentials with IAM write permissions (see below) |
| `AWS_SECRET_ACCESS_KEY` | — |
| `AWS_SESSION_TOKEN` | Only needed for temporary STS credentials (see note below) |

#### DATABRICKS_S3_BUCKET — what it is and how it is used

`DATABRICKS_S3_BUCKET` is the **S3 bucket that holds catalog data for the test environment**.

**You must create the bucket yourself before running `provision`.** The provision script does
not create the bucket — it only creates resources inside it.  If the bucket does not exist,
External Location creation will fail and all scenarios will error with
`External Location 's3://…/dev_fin' does not exist`.

How the bucket is used during a test run:

| Step | What the script creates |
|---|---|
| `provision` | A unique **S3 prefix** inside the bucket: `s3://<bucket>/genie-test-<run-id>/` |
| `provision` | An **AWS IAM role** (`genie-test-uc-role-<run-id>`) scoped to that prefix |
| `provision` | A Databricks **storage credential** backed by the IAM role |
| `provision` | A Databricks **External Location** covering `s3://<bucket>/genie-test-<run-id>/` |
| Integration tests | Each catalog gets its own subfolder: `.../genie-test-<run-id>/<catalog-name>/` |
| `teardown` | Deletes the IAM role; the metastore deletion cascades to catalogs/schemas/policies |

The **S3 objects** (actual data files) written during the test are **not deleted by teardown** —
the metastore and workspace are destroyed at the Databricks layer, but the underlying S3 prefixes
remain.  They are cheap (a few MB of small Delta files) and isolated by `run-id`, so they
accumulate over time.  Clean them up periodically with:

```bash
aws s3 rm s3://<your-bucket>/ --recursive --exclude "*" --include "genie-test-*"
```

> **Tip — use a dedicated test bucket.** Keep `DATABRICKS_S3_BUCKET` separate from any
> production or user-facing bucket.  The provision script creates IAM roles with
> `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on the whole prefix, so using a
> dedicated bucket limits blast radius.

#### AWS credential type recommendation

> **Use long-lived IAM user credentials** (`AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`, no `AWS_SESSION_TOKEN`) whenever possible. Temporary STS tokens expire after 1–12 hours, which can cause teardown to fail if the full test run (~90 min + review time) outlasts the token lifetime.

| Credential type | `AWS_SESSION_TOKEN` required | Expires | Recommended for |
|---|---|---|---|
| IAM user access keys | No | Never | **Local dev and CI/CD** |
| AWS SSO / `aws sso login` | Yes (auto-set by CLI) | 1–8 h | Interactive use only |
| STS `AssumeRole` | Yes | 15 min – 12 h | Short-lived pipelines |

Required IAM permissions for the credentials:
`iam:CreateRole`, `iam:DeleteRole`, `iam:PutRolePolicy`, `iam:DeleteRolePolicy`,
`iam:ListRolePolicies`, `iam:ListAttachedRolePolicies`, `iam:DetachRolePolicy`,
`iam:UpdateAssumeRolePolicy`, `sts:GetCallerIdentity`

### Provision

```bash
python scripts/provision_test_env.py provision
```

This will:

1. Look up the SP's SCIM identity in the Databricks account.
2. Create a **serverless workspace** (`genie-test-<id>`) — no VPC/S3/IAM required.
3. Create a fresh **Unity Catalog metastore** with a unique storage path inside your S3 bucket.
4. Assign the metastore to the workspace.
5. Create an **AWS IAM role** scoped to the test S3 prefix and register it as a storage credential.
6. Create an **External Location** so catalogs can be created without a metastore root.
7. Set the SP as **metastore admin** and **workspace admin**.
8. Write `auth.auto.tfvars` for all env directories (`dev`, `bu2`, `prod`, `account`).
9. Save a state file (`scripts/.test_env_state.json`) for teardown.

Workspace provisioning typically takes **10–15 minutes**.

### Run tests

```bash
# Check what environment is provisioned
python scripts/provision_test_env.py status

# Run all scenarios (warehouse is auto-detected from the workspace)
python scripts/run_integration_tests.py

# Run a specific scenario
python scripts/run_integration_tests.py --scenario quickstart
```

### Tear down

```bash
python scripts/provision_test_env.py teardown
```

This deletes the IAM role, workspace, metastore (and all catalogs/schemas/policies inside
it), admin group, and removes the generated `auth.auto.tfvars` files.

> **If teardown reports "ExpiredToken" for the IAM role deletion:** your AWS session token
> expired during the test run. Export fresh credentials in your shell, then re-run teardown —
> the script reads current environment variables in preference to the file:
>
> ```bash
> export AWS_ACCESS_KEY_ID=...
> export AWS_SECRET_ACCESS_KEY=...
> export AWS_SESSION_TOKEN=...   # omit if using long-lived keys
> python scripts/provision_test_env.py teardown
> ```
>
> Alternatively, delete the role manually: **AWS Console → IAM → Roles → search for `genie-test-uc-role-*`**.
> The Databricks workspace and metastore are always deleted by teardown regardless of whether
> the IAM role deletion succeeds.

### Options

| Flag | Description |
|---|---|
| `--env-file PATH` | Path to credentials file (default: `scripts/account-admin.env`) |
| `--dry-run` | Print what would happen without creating/deleting anything |
| `--force` | With `provision`: overwrite an existing provisioned environment |

---

## Scenarios

`scripts/run_integration_tests.py` runs each playbook.md scenario end-to-end with
full data setup, LLM generation, Terraform apply, assertions, and teardown. Each
scenario is isolated — state from a previous run is destroyed and cleaned before
the next one starts.

| Scenario | playbook.md section | What it validates |
|---|---|---|
| **quickstart** | § 1 | Single Genie Space backed by a single UC catalog (`dev_fin`) |
| **multi-catalog** | § 1 (multi-catalog) | One Genie Space drawing tables from two catalogs (`dev_fin` + `dev_clinical`) |
| **multi-space** | § 1 (multi-space) | Two Genie Spaces with separate catalogs — Finance Analytics + Clinical Analytics |
| **per-space** | § 4 | Add Clinical Analytics incrementally without touching Finance Analytics (isolation guarantee) |
| **promote** | § 5 | Full dev → prod promotion with catalog remapping across both spaces |
| **multi-env** | § 6 | Two independent envs on the same account: `dev` (Finance), `bu2` (Clinical) |
| **attach-promote** | § 3 | Import a Genie Space already configured in the UI — discover its tables from the API, govern it, then promote to prod |
| **decentralized** | § 7 | Central governance team applies ABAC via `apply-governance` (`MODE=governance`); separate BU team creates Genie space via `apply-genie` (`MODE=genie`); asserts no cross-layer state contamination |

---

## Test Catalogs

`setup_test_data.py` creates the following Unity Catalog resources:

### Dev

| Catalog | Schema | Table | Rows | Sensitive data |
|---|---|---|---|---|
| `dev_fin` | `finance` | `customers` | 10 | SSN, DOB, email, phone (PII) |
| `dev_fin` | `finance` | `transactions` | 15 | AML flag, risk score (AML) |
| `dev_fin` | `finance` | `credit_cards` | 10 | card number, CVV (PCI) |
| `dev_clinical` | `clinical` | `patients` | 10 | SSN, DOB, insurance ID (PHI) |
| `dev_clinical` | `clinical` | `encounters` | 12 | diagnosis, treatment notes (PHI) |

### Prod (mirror schema, different data)

| Catalog | Schema | Table | Rows |
|---|---|---|---|
| `prod_fin` | `finance` | `customers` | 10 |
| `prod_fin` | `finance` | `transactions` | 15 |
| `prod_fin` | `finance` | `credit_cards` | 10 |
| `prod_clinical` | `clinical` | `patients` | 10 |
| `prod_clinical` | `clinical` | `encounters` | 12 |

---

## Quick Start

### Prerequisites

- `envs/dev/auth.auto.tfvars` configured with workspace credentials
- A SQL warehouse available in the workspace (or pass `WAREHOUSE_ID=<id>` to
  avoid cold-start delay)

### Run all scenarios

```bash
# Run all six scenarios sequentially (full teardown after each)
make test-all

# Keep data and Terraform resources after the run for inspection
make test-all KEEP_DATA=1

# Pin a warehouse to avoid cold-start delay
make test-all WAREHOUSE_ID=abc123ef
```

### Run a single scenario

```bash
make test-quickstart
make test-multi-catalog
make test-multi-space
make test-per-space
make test-promote
make test-multi-env
make test-attach-promote
make test-decentralized

# All targets accept WAREHOUSE_ID= and KEEP_DATA=1
make test-promote WAREHOUSE_ID=abc123ef KEEP_DATA=1
```

### Run directly with Python

```bash
# List available scenarios
python scripts/run_integration_tests.py --list

# Run all
python scripts/run_integration_tests.py

# Run one scenario
python scripts/run_integration_tests.py --scenario quickstart
python scripts/run_integration_tests.py --scenario per-space --keep-data

# Pin a warehouse
python scripts/run_integration_tests.py --warehouse-id abc123ef

# Non-default auth file
python scripts/run_integration_tests.py --auth-file envs/dev/auth.auto.tfvars
```

---

## Scenario Details

### 1. quickstart — Single space, single catalog

Validates the core quickstart from docs/playbook.md § 1 with a single Genie
Space backed by `dev_fin`.

**Steps:**

| Step | Action |
|---|---|
| 1 | Create `dev_fin` test catalogs and sample data |
| 2 | Configure `dev` env: one space "Finance Analytics" with `dev_fin.*` tables |
| 3 | `make generate ENV=dev` — LLM generates ABAC config and masking functions |
| 4 | Assert `generated/abac.auto.tfvars` and `generated/spaces/finance_analytics/` created |
| 5 | `make apply ENV=dev` — deploys account, data_access, workspace layers |
| 6 | Assert `.genie_space_id_finance_analytics` file exists |
| 7 | `setup_test_data.py --verify` — row counts, column tags, column masks |
| 8 | Teardown data + Terraform resources |

**Key assertions:**
- `generated/abac.auto.tfvars` contains `Finance Analytics` genie_space_configs entry
- `generated/spaces/finance_analytics/abac.auto.tfvars` exists (per-space dir bootstrapped)
- `.genie_space_id_*` file created after apply
- Row counts ≥ expected for all `dev_fin` tables
- Column tags and masking policies applied

---

### 2. multi-catalog — One space spanning two catalogs

Validates the "single space spanning multiple catalogs" pattern from playbook.md § 1.
One space ("Combined Analytics") draws tables from both `dev_fin` and `dev_clinical`.

**Key assertions:**
- `generated/abac.auto.tfvars` contains `Combined Analytics` and references both `dev_fin` and `dev_clinical`
- Only one Genie Space deployed
- Column tags applied across both catalogs

---

### 3. multi-space — Two spaces, separate catalogs

Validates the two-space multi-catalog flow from playbook.md § 1. Finance Analytics
uses `dev_fin`; Clinical Analytics uses `dev_clinical`. This is the core of the
original `make integration-test` flow.

**Key assertions:**
- `generated/abac.auto.tfvars` contains both `Finance Analytics` and `Clinical Analytics` entries
- `generated/spaces/finance_analytics/` and `generated/spaces/clinical_analytics/` both bootstrapped
- Two `.genie_space_id_*` files created
- Row counts and ABAC verified for both catalogs

---

### 4. per-space — Incremental space addition (isolation test)

Validates the per-space generation isolation guarantee from playbook.md § 4.

**Phase 1:** Deploy Finance Analytics only.

**Phase 2:** Add Clinical Analytics using `make generate SPACE="Clinical Analytics"` —
without triggering a full LLM re-run over Finance Analytics.

**Key assertions:**
- After full generate: `Finance Analytics` in assembled output, `Clinical Analytics` absent
- `generated/spaces/finance_analytics/abac.auto.tfvars` content is **byte-for-byte unchanged**
  after the per-space generate for Clinical Analytics
- Assembled `generated/abac.auto.tfvars` contains **both** spaces after merge
- `generated/spaces/clinical_analytics/abac.auto.tfvars` created by SPACE= generate
- Both Genie Spaces deployed after final apply

---

### 5. promote — dev → prod cross-env promotion

Validates the full dev → prod promotion from playbook.md § 5.

**Catalog mapping:** `dev_fin → prod_fin`, `dev_clinical → prod_clinical`

**Steps:**

| Step | Action |
|---|---|
| 1 | Create dev + prod test catalogs |
| 2 | Configure dev: two spaces (Finance + Clinical) |
| 3 | `make generate ENV=dev` + `make apply ENV=dev` |
| 4 | Verify dev data + ABAC |
| 5 | `make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG_MAP=dev_fin=prod_fin,dev_clinical=prod_clinical` |
| 6 | `make apply ENV=prod` |
| 7 | `setup_test_data.py --verify-prod` |
| 8 | Teardown both envs |

**Key assertions:**
- `envs/prod/env.auto.tfvars` written by promote with `prod_fin` catalog references
- `envs/prod/generated/abac.auto.tfvars` contains remapped prod catalog names
- Prod column tags and masking policies applied

---

### 6. multi-env — Two independent envs (BU scenario)

Validates the independent second environment from playbook.md § 6.

- `dev` env: Finance Analytics backed by `dev_fin`
- `bu2` env: Clinical Analytics backed by `dev_clinical`
- Both envs use the same Databricks workspace and account
- Each has its own `make generate` + `make apply` cycle with completely separate
  generated config and Terraform state

**Key assertions:**
- `dev/generated/abac.auto.tfvars` contains Finance Analytics, not Clinical Analytics
- `bu2/generated/abac.auto.tfvars` contains Clinical Analytics, not Finance Analytics
- `envs/dev/terraform.tfstate` and `envs/bu2/terraform.tfstate` exist and differ
- Finance Analytics Genie Space deployed in dev, Clinical Analytics deployed in bu2

---

### 7. attach-promote — Attach to UI-created space and promote to prod

Validates the "Import an existing Genie Space" flow from playbook.md § 3, combined
with a dev → prod promotion. This is the adoption story: a data team already built a
Genie Space in the Databricks UI and now wants to bring it under ABAC governance.

**Phase 1 — Simulate UI configuration:**

A Finance Analytics Genie Space is created directly via the Genie REST API
(`POST /api/2.0/genie/spaces`) with `dev_fin` tables. This represents the space a
data team built in the UI before this tool was adopted.

**Phase 2 — Attach (API discovery mode):**

`env.auto.tfvars` is configured with only `genie_space_id` — `uc_tables` is deliberately
omitted. `make generate` then queries the Genie API to discover what tables the space
uses and generates full ABAC governance from those tables. The `genie_space_configs`
block is parsed verbatim from the API response (not re-generated by the LLM), so the
space's existing title, instructions, benchmarks, and sample questions are preserved.

After `make generate`, `env.auto.tfvars` is updated to add the discovered `uc_tables`
(simulating the manual playbook.md step: "copy the discovered tables into
`data_access/env.auto.tfvars`"). This is needed so the `data_access` layer applies
UC grants to the correct tables.

**Phase 3 — Apply:**

`make apply` deploys ABAC governance (group ACLs, column tags, masking functions,
FGAC policies) **without** creating or deleting the Genie Space. Terraform operates
only on `existing_spaces` resources — no `genie_space_create` provisioner runs.

**Phase 4 — Promote:**

`make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG_MAP=dev_fin=prod_fin` followed
by `make apply ENV=prod` applies the same governance to prod.

**Steps:**

| Step | Action |
|---|---|
| 1 | Create `dev_fin` + `prod_fin` test catalogs |
| 2 | Create a Genie Space via `POST /api/2.0/genie/spaces` (simulating UI setup) |
| 3 | Configure `dev` env: `genie_space_id = "<id>"`, no `uc_tables` |
| 4 | `make generate ENV=dev` — discovers tables from Genie API, generates ABAC |
| 5 | Assert generated config references `dev_fin` catalog and `Finance Analytics` |
| 6 | Update `env.auto.tfvars` with discovered `uc_tables` (simulating playbook.md manual step) |
| 7 | `make apply ENV=dev` — applies ABAC; no new space created |
| 8 | Assert **no** `.genie_space_id_*` file was created (space not created by Terraform) |
| 9 | `setup_test_data.py --verify` — row counts, column tags, masks |
| 10 | `make promote ... DEST_CATALOG_MAP=dev_fin=prod_fin` |
| 11 | `make apply ENV=prod` |
| 12 | `setup_test_data.py --verify-prod` |
| 13 | Delete the UI-created space via `DELETE /api/2.0/genie/spaces/{id}` (teardown) |

**Key assertions:**
- `generated/abac.auto.tfvars` contains `dev_fin` catalog references (tables discovered from API)
- `generated/abac.auto.tfvars` contains `Finance Analytics` `genie_space_configs` entry
- **No** `.genie_space_id_*` file exists after `make apply` — Terraform did not create a new space
- `envs/prod/generated/abac.auto.tfvars` contains `prod_fin` after promote
- Column tags and masking policies applied in both dev and prod

---

### 8. decentralized — Central governance team + BU Genie team

Validates the decentralized governance pattern from playbook.md § 7 and [decentralized.md](decentralized.md).

**Phase 1 — Governance team:**

A `governance` env is set up with both `dev_fin` + `dev_clinical` table references and **no** `genie_spaces` block. `make generate MODE=governance` is run — only ABAC content is generated. `make apply-governance` applies the account and data_access layers without touching the workspace layer.

**Phase 2 — BU Finance team:**

A `bu_fin` env is set up with a Finance Analytics space pointing at `dev_fin` tables. `make generate MODE=genie` is run — only `genie_space_configs` is generated (no ABAC, no masking SQL). `make apply-genie` applies only the workspace layer and creates the Genie Space.

**Phase 3 — State isolation:**

The test asserts that:
- `governance` env has `data_access/terraform.tfstate` but **no** `.genie_space_id_*` file
- `bu_fin` env has a `.genie_space_id_*` file but **no** `data_access/terraform.tfstate`

**Steps:**

| Step | Action |
|---|---|
| 1 | Create `dev_fin` + `dev_clinical` test catalogs |
| 2 | Configure `governance` env with both catalogs' tables (no `genie_spaces`) |
| 3 | `make generate ENV=governance MODE=governance` |
| 4 | Assert `tag_assignments` + `fgac_policies` present; `genie_space_configs` absent |
| 5 | `make apply-governance ENV=governance` |
| 6 | Assert `data_access/terraform.tfstate` exists; no `.genie_space_id_*` file |
| 7 | Configure `bu_fin` env with Finance Analytics space |
| 8 | `make generate ENV=bu_fin MODE=genie` |
| 9 | Assert `genie_space_configs` present; `tag_assignments` + `fgac_policies` absent; no `masking_functions.sql` |
| 10 | `make apply-genie ENV=bu_fin` |
| 11 | Assert `.genie_space_id_finance_analytics` file exists; no `data_access/terraform.tfstate` |
| 12 | Teardown both envs |

**Key assertions:**
- `governance/generated/abac.auto.tfvars` contains `tag_assignments` and `fgac_policies`
- `governance/generated/abac.auto.tfvars` does NOT contain `genie_space_configs`
- `governance/generated/masking_functions.sql` exists
- `bu_fin/generated/abac.auto.tfvars` contains `genie_space_configs`
- `bu_fin/generated/abac.auto.tfvars` does NOT contain `tag_assignments` or `fgac_policies`
- `bu_fin/generated/masking_functions.sql` does NOT exist (governance team owns it)
- Cross-layer state isolation: governance has data_access state; BU has workspace state only

---

## Verify Checks (setup_test_data.py --verify)

| Check | Source | Pass condition |
|---|---|---|
| Row counts | `SELECT COUNT(*) FROM <table>` | Actual ≥ expected |
| Column tags | `system.information_schema.column_tags` | At least 1 tag per catalog |
| Column masks | `system.information_schema.column_masks` | At least 1 mask per catalog |

---

## Using `setup_test_data.py` Standalone

Run from the `genie/aws/` root directory.

### Setup

```bash
# Dev catalogs only
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars

# Dev + prod catalogs (needed before make apply ENV=prod)
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --prod
```

### Verify (run after `make apply`)

```bash
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --verify
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --verify-prod
```

### Teardown

```bash
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars \
  --teardown --teardown-prod
```

### CLI reference

| Flag | Description |
|---|---|
| `--auth-file <path>` | Path to `auth.auto.tfvars` (default: `./auth.auto.tfvars`) |
| `--prod` | Also create prod catalogs (`prod_fin`, `prod_clinical`) |
| `--verify` | Assert dev table row counts + ABAC governance; exits non-zero on failure |
| `--verify-prod` | Same as `--verify` but for prod catalogs |
| `--teardown` | Drop dev catalogs (`dev_fin`, `dev_clinical`) |
| `--teardown-prod` | Drop prod catalogs (`prod_fin`, `prod_clinical`) |
| `--warehouse-id <id>` | Use a specific SQL warehouse instead of auto-selecting |
| `--dry-run` | Print SQL to stdout without executing |

---

## Legacy: `make integration-test`

The original monolithic integration test is still available. It combines the
multi-space and promote scenarios (playbook.md § 1 + § 5) into a single pipeline without isolation:

```bash
# Full run — destroys everything at the end
make integration-test

# Keep data and deployed resources for inspection
make integration-test KEEP_DATA=1

# Pin a warehouse
make integration-test WAREHOUSE_ID=abc123ef
```

**Pipeline steps:**

| Step | Command | Purpose |
|---|---|---|
| 1 | `setup_test_data.py --prod` | Create dev + prod UC catalogs and sample data |
| 2 | `make setup` | Scaffold env directories |
| 3 | `make apply ENV=account` | Deploy groups and tag policies |
| 4 | `make generate ENV=dev` | Full LLM generation (both spaces) |
| 5 | `make apply ENV=dev` | Deploy dev governance |
| 6 | `setup_test_data.py --verify` | Assert dev ABAC governance |
| 7 | `make generate SPACE="Finance Analytics"` | Per-space isolation check |
| 8 | `make promote ... DEST_CATALOG_MAP=...` | Remap dev → prod catalogs |
| 9 | `make apply ENV=prod` | Deploy prod governance |
| 10 | `setup_test_data.py --verify-prod` | Assert prod ABAC governance |
| 11 | Teardown | Drop data + destroy Terraform (skipped if `KEEP_DATA=1`) |

Use `make test-all` instead for isolated, individually-reportable scenarios.

---

## Cleanup

```bash
# Drop test data only (leave Terraform resources in place)
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars \
  --teardown --teardown-prod

# Destroy Terraform resources only (leaves UC catalogs in place)
make destroy ENV=prod
make destroy ENV=dev
make destroy ENV=account

# Full cleanup — data + Terraform
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars \
  --teardown --teardown-prod && \
make destroy ENV=prod && make destroy ENV=dev && make destroy ENV=account
```

> **Note:** Always run `make destroy` before dropping UC catalogs. If catalogs
> are dropped first, the `deploy_masking_functions` destroy provisioner will
> fail with `Catalog not found`. If this happens, remove the stuck resource
> with `terraform state rm module.data_access.null_resource.deploy_masking_functions`
> in the affected env's `data_access/` directory, then re-run `make destroy`.

---

## Troubleshooting

### IAM role not deleted — `ExpiredToken`

**Symptom:**
```
⚠  Could not delete IAM role 'genie-test-uc-role-*': An error occurred (ExpiredToken)
   when calling the ListRolePolicies operation: The security token included in the request is expired
⚠  Your AWS session token has expired.  To retry with fresh credentials:
   1. Export new tokens:  AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...
   2. Re-run teardown:    python scripts/provision_test_env.py teardown
```

**Cause:** You are using temporary AWS STS credentials (`AWS_SESSION_TOKEN`). The integration
test suite takes ~90 minutes; if the STS token lifetime is shorter than the total run time
(provision + test + teardown), the token expires before teardown can delete the IAM role.

**Fix (preferred) — switch to long-lived IAM user keys:**

Remove `AWS_SESSION_TOKEN` from `scripts/account-admin.env` and replace `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` with permanent IAM user credentials. Long-lived keys never expire and
work reliably across the full CI pipeline.

**Fix (immediate) — refresh the token and re-run teardown:**

```bash
# Export fresh credentials in your shell (overrides the stale file values)
export AWS_ACCESS_KEY_ID=ASIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...

# Re-run teardown — it will pick up the fresh env vars
python scripts/provision_test_env.py teardown
```

**Fix (manual) — delete the role directly in AWS:**

If you cannot obtain fresh credentials, delete the orphaned role in the AWS Console:

1. Go to **IAM → Roles**
2. Search for `genie-test-uc-role-`
3. Select the role → **Delete**

The Databricks workspace and metastore are always removed by teardown regardless of whether
the IAM step succeeds, so only the IAM role requires manual cleanup.

**Prevention for `make test-ci`:** If your organisation requires STS tokens, extend the session
duration to at least 4 hours before starting the pipeline:

```bash
# Request a longer-lived token (max depends on your IAM policy, up to 12 h for roles)
aws sts assume-role --role-arn arn:aws:iam::<account>:role/<role> \
  --role-session-name genie-ci --duration-seconds 14400   # 4 hours
```

---

### Orphaned workspace or metastore after failed teardown

If teardown fails completely, check the Databricks Account Console:

- **Workspaces**: Account Console → Workspaces → filter by name `genie-test-*` → Delete
- **Metastores**: Account Console → Data → Unity Catalog → filter by name `genie-test-*` → Delete (check "Force delete")
- **Groups**: Account Console → User Management → Groups → filter by name `genie-test-admins-*` → Delete

After manually cleaning up, remove the stale state file so subsequent runs start clean:

```bash
rm -f scripts/.test_env_state.json
```
