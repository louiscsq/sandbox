#!/usr/bin/env bash
# =============================================================================
# Import existing Databricks resources into Terraform state
# =============================================================================
# Imports groups, tag policies, and FGAC policies that already exist in
# Databricks so that Terraform can manage them without "already exists" errors.
#
# Prerequisites:
#   - auth.auto.tfvars configured with valid credentials
#   - env.auto.tfvars configured with uc_tables and environment settings
#   - abac.auto.tfvars configured with groups/tag_policies/fgac_policies
#   - terraform init already run
#
# Usage:
#   ./scripts/import_existing.sh              # import all resource types
#   ./scripts/import_existing.sh --groups-only # import only groups
#   ./scripts/import_existing.sh --tags-only   # import only tag policies
#   ./scripts/import_existing.sh --fgac-only   # import only FGAC policies
#   ./scripts/import_existing.sh --dry-run     # show commands without running
# =============================================================================

set -euo pipefail

MODULE_DIR="$(pwd)"
MODULE_BASENAME="$(basename "$MODULE_DIR")"
ENV_NAME="$MODULE_BASENAME"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_RUNNER="${TERRAFORM_RUNNER:-$SCRIPT_DIR/terraform_layer.sh}"

if [ "$MODULE_BASENAME" = "account" ]; then
  LAYER="account"
elif [ "$MODULE_BASENAME" = "data_access" ]; then
  LAYER="data_access"
  ENV_NAME="$(basename "$(dirname "$MODULE_DIR")")"
else
  LAYER="workspace"
fi

DRY_RUN=false
IMPORT_GROUPS=true
IMPORT_TAGS=true
IMPORT_FGAC=true
IMPORT_TAG_ASSIGNMENTS=true

for arg in "$@"; do
  case "$arg" in
    --dry-run)     DRY_RUN=true ;;
    --groups-only) IMPORT_TAGS=false; IMPORT_FGAC=false; IMPORT_TAG_ASSIGNMENTS=false ;;
    --tags-only)   IMPORT_GROUPS=false; IMPORT_FGAC=false; IMPORT_TAG_ASSIGNMENTS=false ;;
    --fgac-only)   IMPORT_GROUPS=false; IMPORT_TAGS=false; IMPORT_TAG_ASSIGNMENTS=false ;;
    --tag-assignments-only) IMPORT_GROUPS=false; IMPORT_TAGS=false; IMPORT_FGAC=false ;;
    -h|--help)
      echo "Usage: $0 [--dry-run] [--groups-only|--tags-only|--fgac-only|--tag-assignments-only]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: $0 [--dry-run] [--groups-only|--tags-only|--fgac-only|--tag-assignments-only]"
      exit 1
      ;;
  esac
done

cd "$MODULE_DIR"

if [ ! -f abac.auto.tfvars ]; then
  echo "ERROR: abac.auto.tfvars not found. Configure it before importing."
  exit 1
fi

run_import() {
  local address="$1"
  local id="$2"

  if $DRY_RUN; then
    echo "  [DRY RUN] $TF_RUNNER '$LAYER' '$ENV_NAME' import '$address' '$id'"
  else
    echo "  Importing: $address -> $id"
    if "$TF_RUNNER" "$LAYER" "$ENV_NAME" import "$address" "$id" 2>&1; then
      echo "  ✓ Imported $address"
    else
      echo "  ✗ Failed to import $address (may not exist or already in state)"
    fi
  fi
}

# Look up group display-names from abac.auto.tfvars and resolve their numeric
# account-level SCIM IDs via the Databricks SDK (required for terraform import).
# Outputs "name:scim_id" lines; falls back to "name:" (empty ID) if unreachable.
extract_group_name_id_pairs() {
  python3 -c "
import hcl2, sys, os

# ── 1. Read group names from abac.auto.tfvars ──────────────────────────────
try:
    with open('abac.auto.tfvars') as f:
        cfg = hcl2.load(f)
    group_names = list(cfg.get('groups', {}).keys())
except Exception as e:
    sys.stderr.write(f'WARNING: Could not parse abac.auto.tfvars: {e}\n')
    sys.exit(0)

if not group_names:
    sys.exit(0)

# ── 2. Load auth credentials ───────────────────────────────────────────────
def _str(v):
    return (v[0] if isinstance(v, list) else v or '').strip()

auth = {}
for fname in ['auth.auto.tfvars']:
    if os.path.exists(fname):
        try:
            with open(fname) as f:
                auth = hcl2.load(f)
        except Exception:
            pass
        break

account_id    = _str(auth.get('databricks_account_id', ''))    or os.environ.get('DATABRICKS_ACCOUNT_ID', '')
client_id     = _str(auth.get('databricks_client_id', ''))     or os.environ.get('DATABRICKS_CLIENT_ID', '')
client_secret = _str(auth.get('databricks_client_secret', '')) or os.environ.get('DATABRICKS_CLIENT_SECRET', '')

# ── 3. Look up each group's numeric SCIM ID ────────────────────────────────
if not account_id:
    sys.stderr.write('WARNING: No databricks_account_id found; skipping group ID lookup.\n')
    sys.exit(0)

try:
    from databricks.sdk import AccountClient
    a = AccountClient(
        host='https://accounts.cloud.databricks.com',
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    for name in group_names:
        try:
            found = list(a.groups.list(filter=f'displayName eq \"{name}\"'))
            if found and found[0].id:
                print(name + ':' + str(found[0].id))
            # If not found, print nothing — the group doesn't exist, import not needed
        except Exception as e:
            sys.stderr.write(f'WARNING: group lookup failed for {name!r}: {e}\n')
except ImportError:
    sys.stderr.write('WARNING: databricks-sdk not installed; cannot look up group IDs.\n')
" 2>/dev/null || true
}

extract_tag_keys() {
  python3 -c "
import hcl2, sys
with open('abac.auto.tfvars') as f:
    cfg = hcl2.load(f)
for tp in cfg.get('tag_policies', []):
    print(tp.get('key', ''))
" 2>/dev/null || {
    echo "WARNING: Could not parse abac.auto.tfvars with python-hcl2." >&2
  }
}

extract_tag_assignments() {
  python3 -c "
import hcl2, sys
with open('abac.auto.tfvars') as f:
    cfg = hcl2.load(f)
for ta in cfg.get('tag_assignments', []):
    etype = ta.get('entity_type', '')
    ename = ta.get('entity_name', '')
    tkey = ta.get('tag_key', '')
    tval = ta.get('tag_value', '')
    tf_key = f'{etype}|{ename}|{tkey}|{tval}'
    import_id = f'{etype},{ename},{tkey}'
    print(f'{tf_key}|{import_id}')
" 2>/dev/null || {
    echo "WARNING: Could not parse abac.auto.tfvars with python-hcl2." >&2
  }
}

extract_fgac_names() {
  python3 -c "
import hcl2, sys
with open('abac.auto.tfvars') as f:
    cfg = hcl2.load(f)
for p in cfg.get('fgac_policies', []):
    name = p.get('name', '')
    catalog = p.get('catalog', '')
    if name and catalog:
        print(name + '|' + catalog + '_' + name)
" 2>/dev/null || {
    echo "WARNING: Could not parse tfvars files with python-hcl2." >&2
  }
}

echo "============================================"
echo "  Import Existing Resources into Terraform"
echo "============================================"
echo ""

imported=0
skipped=0

if $IMPORT_GROUPS; then
  if [ "$LAYER" != "account" ]; then
    echo "--- Groups ---"
    echo "  Skipping group imports outside the shared account layer"
    echo ""
  else
    echo "--- Groups ---"
    group_pairs=$(extract_group_name_id_pairs)
    if [ -z "$group_pairs" ]; then
      echo "  No existing groups found to import."
    else
      while IFS=':' read -r name group_id; do
        [ -z "$name" ] || [ -z "$group_id" ] && continue
        run_import "module.account.databricks_group.groups[\"$name\"]" "$group_id"
        ((imported++)) || true
      done <<< "$group_pairs"
    fi
    echo ""
  fi
fi

if $IMPORT_TAGS; then
  echo "--- Tag Policies ---"
  if [ "$LAYER" != "account" ]; then
    echo "  Skipping tag policy imports outside envs/account (tag policies are account-scoped)"
  else
    tag_keys=$(extract_tag_keys)
    if [ -z "$tag_keys" ]; then
      echo "  No tag policies found in abac.auto.tfvars."
    else
      while IFS= read -r key; do
        [ -z "$key" ] && continue
        run_import "module.account.databricks_tag_policy.policies[\"$key\"]" "$key"
        ((imported++)) || true
      done <<< "$tag_keys"
    fi
  fi
  echo ""
fi

if $IMPORT_FGAC; then
  echo "--- FGAC Policies ---"
  if [ "$LAYER" != "data_access" ]; then
    echo "  Skipping FGAC policy imports outside envs/<workspace>/data_access"
  else
    fgac_entries=$(extract_fgac_names)
    if [ -z "$fgac_entries" ]; then
      echo "  No FGAC policies found in abac.auto.tfvars."
    else
      while IFS='|' read -r policy_key policy_name; do
        [ -z "$policy_key" ] && continue
        run_import "module.data_access.databricks_policy_info.policies[\"$policy_key\"]" "$policy_name"
        ((imported++)) || true
      done <<< "$fgac_entries"
    fi
  fi
  echo ""
fi

if $IMPORT_TAG_ASSIGNMENTS; then
  echo "--- Tag Assignments ---"
  if [ "$LAYER" != "data_access" ]; then
    echo "  Skipping tag assignment imports outside envs/<workspace>/data_access"
  else
    tag_assignment_entries=$(extract_tag_assignments)
    if [ -z "$tag_assignment_entries" ]; then
      echo "  No tag assignments found in abac.auto.tfvars."
    else
      while IFS='|' read -r etype ename tkey tval import_id; do
        [ -z "$etype" ] && continue
        tf_key="${etype}|${ename}|${tkey}|${tval}"
        run_import "module.data_access.databricks_entity_tag_assignment.assignments[\"$tf_key\"]" "$import_id"
        ((imported++)) || true
      done <<< "$tag_assignment_entries"
    fi
  fi
  echo ""
fi

echo "============================================"
if $DRY_RUN; then
  echo "  Dry run complete. $imported import(s) would be attempted."
else
  echo "  Done. $imported import(s) attempted."
fi
echo "  Next: terraform plan (to verify state is consistent)"
echo "============================================"
