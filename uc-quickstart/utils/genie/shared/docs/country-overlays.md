# Country / Region Overlays

This document explains how the country overlay system works, how to use it, and how to add support for a new country or region.

> **Contributors:** Jump to [Adding a new country](#adding-a-new-country) for the step-by-step guide to creating or tuning a country overlay. No Python, Terraform, or Makefile changes are needed — just a single YAML file.

---

## Overview

By default, the ABAC generator produces governance rules using US-centric PII patterns (SSN, credit card, HIPAA). The **country overlay** system injects region-specific identifier knowledge — column patterns, masking functions, and regulatory context — into the LLM prompt so it produces governance appropriate for non-US datasets.

Each country overlay is a self-contained YAML file under `shared/countries/`. No Terraform, Python, or Makefile changes are needed to add a new region.

### Supported regions

| Code | Region | Key identifiers |
|------|--------|-----------------|
| `ANZ` | Australia & New Zealand | TFN, Medicare, BSB, IRD, NHI |
| `IN` | India | Aadhaar, PAN, GSTIN, IFSC, UPI |
| `SEA` | Singapore & Malaysia | NRIC, FIN, MyKad, UEN, EPF |

---

## How to use

### 1. Set the country in your environment

In `envs/<env>/env.auto.tfvars`:

```hcl
country = "ANZ"            # Single region
country = "ANZ,SEA"        # Multi-region dataset
country = ""               # US/global defaults (no overlay)
```

### 2. Generate

```bash
make generate ENV=dev
```

Or override via CLI without editing the file:

```bash
make generate ENV=dev COUNTRY=ANZ
make generate ENV=dev COUNTRY=ANZ,IN,SEA
```

CLI `COUNTRY=` takes priority over the `country` field in `env.auto.tfvars`.

### 3. Apply as usual

```bash
make apply ENV=dev
```

The generated `masking_functions.sql` will include country-specific UDFs (e.g. `mask_tfn`, `mask_aadhaar`, `mask_nric`), and `abac.auto.tfvars` will include tag assignments and FGAC policies referencing those functions.

---

## Architecture

### Data flow

The country overlay plugs into three stages of the normal generate → validate → apply pipeline:

```
┌─────────────────────────────────────────────────────────────────┐
│  1. CONFIGURE                                                   │
│                                                                 │
│  env.auto.tfvars:  country = "ANZ"                              │
│  (or CLI:          make generate COUNTRY=ANZ)                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. GENERATE  (make generate)                                   │
│                                                                 │
│  ┌──────────────────────┐    ┌────────────────────────────────┐ │
│  │ shared/countries/    │    │ LLM prompt                     │ │
│  │   ANZ.yaml           │───▶│                                │ │
│  │                      │    │ [US defaults]                  │ │
│  │ • identifiers (TFN,  │    │ + [ANZ overlay: TFN, Medicare, │ │
│  │   Medicare, BSB...)  │    │    BSB, regulations, masking   │ │
│  │ • masking functions  │    │    function signatures]        │ │
│  │ • prompt_overlay     │    │ + [your table DDLs]            │ │
│  └──────────────────────┘    └───────────────┬────────────────┘ │
│                                              │                  │
│                                              ▼                  │
│                              ┌────────────────────────────────┐ │
│                              │ LLM output                     │ │
│                              │                                │ │
│                              │ • masking_functions.sql         │ │
│                              │   (mask_tfn, mask_medicare ...) │ │
│                              │ • abac.auto.tfvars              │ │
│                              │   (tags referencing ANZ cols)   │ │
│                              └───────────────┬────────────────┘ │
└──────────────────────────────────────────────┼──────────────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. VALIDATE  (make validate)                                   │
│                                                                 │
│  ANZ.yaml identifiers extend the validation rules:              │
│                                                                 │
│  • Column hints:    tfn, tax_file_number  →  government_id      │
│  • Function checks: mask_tfn must cover government_id columns   │
│  • All US rules still apply — ANZ rules are additive            │
└──────────────────────────────────────────────┬──────────────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. APPLY  (make apply)                                         │
│                                                                 │
│  Deploys to Databricks (no country-specific logic here):        │
│  • Creates masking UDFs (mask_tfn, mask_medicare, ...)          │
│  • Applies tag assignments + FGAC policies                      │
│  • Sets up Genie Spaces                                         │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight:** The country overlay only affects stages 2 and 3. The YAML file teaches the LLM about your region's identifiers (generate) and extends the validation rules (validate). The apply stage is unchanged — Terraform deploys whatever the LLM produced.

### Key components

| Component | File | What it does |
|-----------|------|-------------|
| YAML overlay | `shared/countries/<CODE>.yaml` | Defines identifiers, masking functions, and prompt text for one region |
| Overlay loader | `shared/generate_abac.py` → `load_country_overlays()` | Reads YAML, returns prompt text to inject |
| Prompt builder | `shared/generate_abac.py` → `build_prompt()` | Injects overlay text before the table DDL section |
| Category loader | `shared/validate_abac.py` → `_load_country_categories()` | Reads YAML identifiers into hint→category and function→category maps |
| Column categorizer | `shared/validate_abac.py` → `_infer_column_categories()` | Matches column names against base US + country-specific patterns |
| Validation | `shared/validate_abac.py` | Checks generated masking functions against expected categories |
| Unit tests | `shared/tests/test_country_overlays.py` | 66 tests across 8 test classes |
| Integration test | `make test-country-overlay` | End-to-end: generate → apply → verify for ANZ, IN, SEA, and multi-region |

---

## YAML file structure

Each overlay file follows this structure:

```yaml
code: ANZ                              # Region code (uppercase, used in CLI/config)
name: Australia & New Zealand          # Human-readable name

regulations:                           # Applicable data protection laws
  - Privacy Act 1988 (AU)
  - Privacy Act 2020 (NZ)

identifiers:                           # Country-specific PII/sensitive identifiers
  - name: Tax File Number (TFN)       # Human-readable identifier name
    country: AU                        # ISO country within the region
    column_hints:                      # Lowercase substrings to match in column names
      - tfn
      - tax_file_number
      - tax_file_no
    format: "9 digits (NNN NNN NNN)"   # Format description (informational)
    sensitivity: restricted            # restricted | confidential | public
    masking_function: mask_tfn         # SQL UDF name (or null if no masking needed)
    category: government_id            # Category for validation: government_id, health_id,
                                       #   financial_id, business_id

masking_functions:                     # SQL UDF definitions
  - name: mask_tfn
    signature: "mask_tfn(val STRING) RETURNS STRING"
    comment: "Masks Australian Tax File Number — reveals last 3 digits"
    body: |
      CASE
        WHEN val IS NULL THEN NULL
        WHEN LENGTH(REGEXP_REPLACE(val, '[^0-9]', '')) < 9 THEN '***-***-***'
        ELSE CONCAT('***-***-', RIGHT(REGEXP_REPLACE(val, '[^0-9]', ''), 3))
      END

prompt_overlay: |                      # Markdown injected into the LLM prompt
  ### Country-Specific Identifiers: Australia & New Zealand

  **Regulatory context:** ...

  **Available masking functions:**
  - `mask_tfn(val STRING)` — Masks TFN, reveals last 3 digits
  ...
```

### Field reference

| Field | Required | Purpose |
|-------|----------|---------|
| `code` | Yes | Region code, must match filename (e.g. `ANZ.yaml` → `code: ANZ`) |
| `name` | Yes | Human-readable region name for logging |
| `regulations` | Yes | List of applicable laws — included in prompt for regulatory context |
| `identifiers` | Yes | List of identifier objects (see below) |
| `masking_functions` | Yes | List of SQL UDF definitions |
| `prompt_overlay` | Yes | Markdown text injected into LLM prompt (must be >100 chars) |

**Identifier fields:**

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | Yes | Human-readable name (e.g. "Tax File Number (TFN)") |
| `country` | Yes | ISO country code within region (e.g. "AU", "NZ") |
| `column_hints` | Yes | Lowercase substrings matched against column names during validation |
| `format` | No | Format description (informational, included in prompt) |
| `sensitivity` | No | Data sensitivity level |
| `masking_function` | Yes | UDF name from `masking_functions` list, or `null` for public data |
| `category` | Yes | One of: `government_id`, `health_id`, `financial_id`, `business_id` |

---

## Adding a new country

### Step 1: Create the YAML file

Create `shared/countries/<CODE>.yaml` following the structure above. Use an existing file (e.g. `ANZ.yaml`) as a template.

**Naming convention:** Use a short uppercase code — typically a country ISO code (`JP`, `KR`, `BR`) or a multi-country region code (`SEA`, `ANZ`, `EU`).

**Checklist for the YAML file:**

- [ ] `code` matches the filename (without `.yaml`)
- [ ] `regulations` lists the key data protection laws for the region
- [ ] Each `identifier` has:
  - A unique `name`
  - Accurate `column_hints` — think about what developers actually name these columns (include common misspellings, e.g. India includes both `aadhaar` and `aadhar`)
  - A `masking_function` that either references a function in `masking_functions` or is `null`
  - A `category` from the allowed set: `government_id`, `health_id`, `financial_id`, `business_id`
- [ ] Each `masking_function` has:
  - A `signature` that is valid Databricks SQL
  - A `body` that handles NULL input and edge cases
  - A `comment` explaining what it does
- [ ] `prompt_overlay` is comprehensive markdown that:
  - Explains the regulatory context
  - Lists all available masking functions with signatures and descriptions
  - Warns about disambiguation gotchas (e.g. India's PAN vs credit card PAN, SEA's SG NRIC vs MY MyKad)

### Step 2: Write masking functions carefully

Masking functions run as Databricks SQL UDFs. Follow these patterns:

```sql
-- Always handle NULL
CASE
  WHEN val IS NULL THEN NULL
  -- Handle invalid/short input gracefully
  WHEN LENGTH(REGEXP_REPLACE(val, '[^0-9]', '')) < expected_length THEN '***-masked***'
  -- Reveal only the minimum needed for identification
  ELSE CONCAT('***-', RIGHT(REGEXP_REPLACE(val, '[^0-9]', ''), 3))
END
```

**Guidelines:**
- Always handle `NULL` as the first branch
- Strip non-digit characters before length checks (`REGEXP_REPLACE(val, '[^0-9]', '')`)
- Reveal the minimum necessary — typically last 3-4 digits
- If an identifier encodes sensitive data in its structure (like MyKad encoding DOB in first 6 digits), mask more aggressively and document the warning in `prompt_overlay`
- Use `INITCAP`, `CONCAT`, `LEFT`, `RIGHT`, `REGEXP_REPLACE` — these are available in Databricks SQL

### Step 3: Write the prompt overlay

The `prompt_overlay` field is the most important part — it's what the LLM actually reads. Write it as clear markdown:

```markdown
### Country-Specific Identifiers: <Region Name>

**Regulatory context:**
<1-2 paragraphs about key data protection laws and their requirements>

**Identifier summary:**
| Identifier | Column hints | Masking function |
|------------|-------------|-----------------|
| TFN | tfn, tax_file_number | mask_tfn |
| ... | ... | ... |

**Available masking functions:**
- `mask_foo(val STRING) RETURNS STRING` — description of what it masks and reveals
- ...

**Disambiguation warnings:**
- <Gotcha 1: e.g. "PAN in India is a tax ID, not a credit card PAN">
- <Gotcha 2: e.g. "MyKad first 6 digits encode date of birth — always fully mask">
```

### Step 4: That's it — no code changes needed

The system auto-discovers YAML files in `shared/countries/`. Once your file exists:

```bash
# Test it
make generate ENV=dev COUNTRY=<CODE>

# Validate
make validate ENV=dev COUNTRY=<CODE>
```

### Step 5: Add unit tests (recommended)

Add a test class to `shared/tests/test_country_overlays.py` following the pattern of existing country tests:

```python
class TestJPContent:
    """Japan-specific content validation."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_yaml("JP")

    def test_has_my_number_identifier(self):
        names = {i["name"] for i in self.data["identifiers"]}
        assert "My Number (個人番号)" in names

    def test_my_number_column_hints(self):
        for ident in self.data["identifiers"]:
            if "My Number" in ident["name"]:
                assert "my_number" in ident["column_hints"]
                break
```

The existing `TestYamlFileIntegrity` class automatically picks up new YAML files — it validates structure, required fields, and cross-references for all files in `shared/countries/`.

### Step 6: Run the integration test (optional but recommended)

The `test-country-overlay` integration test validates ANZ, IN, and SEA end-to-end. To include your new country, add it to the multi-region phase of the test (or create a dedicated scenario). At minimum, verify manually:

```bash
make generate ENV=dev COUNTRY=<CODE>
# Inspect generated/abac.auto.tfvars — does it reference your masking functions?
# Inspect generated/masking_functions.sql — are your UDFs present?
make apply ENV=dev
# Check Databricks — are masking functions deployed and working?
```

---

## FAQ

**Can I combine country overlays with MODE=governance or MODE=genie?**

Yes. Country overlays are independent of the operating mode. They inject additional context into the LLM prompt regardless of whether you're generating full ABAC, governance-only, or genie-only config.

**What if the LLM ignores the country overlay?**

The LLM may not use every masking function or recognize every column. The overlay provides hints — it's not deterministic. If the LLM consistently misses an identifier:
1. Make the `column_hints` more specific
2. Add the identifier to the disambiguation warnings in `prompt_overlay`
3. Add a stronger instruction in the prompt overlay (e.g. "You MUST use mask_tfn for any column matching tfn or tax_file_number")

**What if my dataset has columns from multiple regions?**

Use a comma-separated list: `country = "ANZ,IN,SEA"`. All overlays are concatenated into the prompt and all column hints are merged during validation.

**Do I need to update Terraform modules?**

No. Country overlays only affect the generation and validation phases. The Terraform modules deploy whatever masking functions the LLM generates — they're agnostic to the country.

**What categories are available for identifiers?**

`government_id`, `health_id`, `financial_id`, `business_id`. These map to how `validate_abac.py` categorizes columns and checks that masking functions are applied to the right column types.

**What if an identifier doesn't need masking?**

Set `masking_function: null`. Example: India's IFSC code is public bank routing information. The identifier is still listed so the LLM knows not to mask it unnecessarily.
