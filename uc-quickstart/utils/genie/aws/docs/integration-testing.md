# Integration Testing

This guide covers how to use `scripts/setup_test_data.py` to create realistic
test data across two Unity Catalog domains, and how to run the full end-to-end
integration test that validates multi-space, multi-catalog, and multi-environment
promotion flows.

---

## Overview

The integration test exercises three scenarios in sequence:

| Scenario | What it validates |
|---|---|
| **Multi-space** | Two Genie Spaces (`Finance Analytics`, `Clinical Analytics`) each backed by a different UC catalog |
| **Per-space isolation** | Regenerating one space's config does not overwrite the other |
| **Multi-env promotion** | `dev_fin` → `prod_fin`, `dev_clinical` → `prod_clinical` with full ABAC governance |

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

## Using `setup_test_data.py` Standalone

Run from the `genie/aws/` root directory (where `auth.auto.tfvars` lives).

### Setup

```bash
# Dev catalogs only
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars

# Dev + prod catalogs (needed before make apply ENV=prod)
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --prod
```

### Verify (run after `make apply`)

Asserts row counts, column tags, and masking policies. Exits non-zero on failure —
suitable for use as a CI gate.

```bash
# Verify dev
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --verify

# Verify prod
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --verify-prod
```

The verify step checks:

| Check | Source | Pass condition |
|---|---|---|
| Row counts | `SELECT COUNT(*) FROM <table>` | Actual ≥ expected |
| Column tags | `system.information_schema.column_tags` | At least 1 tag per catalog |
| Column masks | `system.information_schema.column_masks` | At least 1 mask per catalog |

### Teardown

```bash
# Drop dev catalogs
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --teardown

# Drop prod catalogs
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --teardown-prod

# Drop both at once
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars \
  --teardown --teardown-prod
```

### Other options

```bash
# Pin a specific SQL warehouse (skips auto-discovery)
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars \
  --warehouse-id <warehouse-id>

# Preview SQL without executing
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --dry-run
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

## Running the Full Integration Test

`make integration-test` orchestrates the complete pipeline automatically.

### Prerequisites

- `envs/dev/auth.auto.tfvars` configured with workspace credentials
- `envs/dev/env.auto.tfvars` contains the `genie_spaces` block (printed by the
  setup script after first run — see the snippet at the end of its output)
- A SQL warehouse available in the workspace

### Run

```bash
# Full run — destroys everything at the end
make integration-test

# Keep data and deployed resources for inspection after the run
make integration-test KEEP_DATA=1

# Pin a warehouse to avoid cold-start delay
make integration-test WAREHOUSE_ID=abc123ef

# Use non-default environment names
make integration-test ENV=dev DEST_ENV=prod
```

### Pipeline steps

| Step | Command | Purpose |
|---|---|---|
| 1 | `setup_test_data.py --prod` | Create dev + prod UC catalogs and sample data |
| 2 | `make setup` | Scaffold env directories |
| 3 | `make apply ENV=account` | Deploy groups and tag policies |
| 4 | `make generate ENV=dev` | Full LLM generation (both spaces), bootstrap per-space dirs |
| 5 | `make apply ENV=dev` | Deploy dev governance (Genie spaces, column tags, masks) |
| 6 | `setup_test_data.py --verify` | Assert dev row counts + ABAC governance |
| 7 | `make generate SPACE="Finance Analytics"` | Per-space isolation test — only Finance is regenerated |
| 8 | `make promote ... DEST_CATALOG_MAP=...` | Remap dev catalogs → prod catalogs |
| 9 | `make apply ENV=prod` | Deploy prod governance |
| 10 | `setup_test_data.py --verify-prod` | Assert prod row counts + ABAC governance |
| 11 | Teardown | Drop data + destroy Terraform resources (skipped if `KEEP_DATA=1`) |

### Catalog mapping used in promotion

```
dev_fin      → prod_fin
dev_clinical → prod_clinical
```

This is set automatically by `make integration-test`. To run promotion manually:

```bash
make promote SOURCE_ENV=dev DEST_ENV=prod \
  DEST_CATALOG_MAP="dev_fin=prod_fin,dev_clinical=prod_clinical"
```

---

## Running Individual Scenarios

You can also run each scenario independently without the full pipeline.

### Scenario 1 — Multi-space (dev only)

```bash
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars
make generate ENV=dev
make apply ENV=dev
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --verify
```

### Scenario 2 — Per-space isolation

After a full `make generate` has run at least once:

```bash
# Regenerate only Finance Analytics — Clinical Analytics config is untouched
make generate SPACE="Finance Analytics" ENV=dev
make apply ENV=dev
```

To confirm isolation, inspect `generated/spaces/finance_analytics/` and verify
`generated/spaces/clinical_analytics/` is unchanged.

### Scenario 3 — Multi-env promotion

```bash
# 1. Create prod catalogs
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --prod

# 2. Promote and apply
make promote SOURCE_ENV=dev DEST_ENV=prod \
  DEST_CATALOG_MAP="dev_fin=prod_fin,dev_clinical=prod_clinical"
make apply ENV=prod

# 3. Verify
python scripts/setup_test_data.py --auth-file envs/dev/auth.auto.tfvars --verify-prod
```

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
  --teardown --teardown-prod
make destroy ENV=prod && make destroy ENV=dev && make destroy ENV=account
```
