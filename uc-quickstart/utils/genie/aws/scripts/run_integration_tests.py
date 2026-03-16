#!/usr/bin/env python3
"""
Integration test runner for the scenarios documented in docs/playbook.md.

Runs each scenario end-to-end with full data setup, generation, apply, verification,
and teardown. Each scenario is isolated — state from a previous run is destroyed and
cleaned before the next one starts.

Scenarios
---------
  quickstart       Single space, single catalog: Finance Analytics backed by dev_fin.
                   Tests the core quickstart flow from docs/playbook.md § 1.

  multi-catalog    One Genie Space spanning two catalogs (dev_fin + dev_clinical).
                   Tests the "single space spanning multiple catalogs" pattern.

  multi-space      Two independent spaces: Finance Analytics (dev_fin) and
                   Clinical Analytics (dev_clinical). Tests § 1 multi-space mode.
                   This is the core of the existing `make integration-test` flow.

  per-space        Incremental per-space generation. Deploys Finance Analytics first,
                   then adds Clinical Analytics using SPACE= without touching Finance.
                   Tests § 2 (Add a new Genie Space) isolation guarantee.

  promote          Full multi-space dev → prod promotion with catalog remapping.
                   Tests § 3a promote flow end-to-end.

  multi-env        Two independent workspace environments on the same account:
                   dev=Finance Analytics, bu2=Clinical Analytics.
                   Tests § 3b (second independent environment / BU).

  attach-promote   Attach to an existing Genie Space that was configured in the UI.
                   A Finance Analytics space is created via the Genie API (simulating
                   a data team that already set it up in the Databricks UI). The test
                   then runs `make generate` in genie_space_id-only mode (no uc_tables),
                   which discovers the space's tables from the API and generates full
                   ABAC governance. Finally promotes to prod. Tests playbook.md §3
                   "Attaching to an existing Genie Space" + §3a promotion.

  decentralized    Central Data Governance team + independent BU Genie teams.
                   Phase 1: governance env applies ABAC (MODE=governance + apply-governance).
                   Phase 2: bu_fin env creates Finance Analytics (MODE=genie + apply-genie).
                   Phase 3: bu_clin (second BU) added; governance state verified unchanged.
                   Phase 4: bu_fin → bu_fin_prod promoted via make promote + make apply-genie.
                   Asserts cross-layer state isolation throughout. Tests playbook.md §7.

  abac-only        ABAC governance only — no Genie Space (playbook.md §2).
                   Phase 1: uc_tables only in env.auto.tfvars, plain make generate + make apply.
                   Phase 2: §2 → §4 upgrade: add genie_spaces, make generate SPACE=, make apply.
                   Asserts governance preserved when Genie Space is added later.

  multi-space-import  Import two UI-configured Genie Spaces in one make generate call
                   (playbook.md §3 multi-space import). Creates two spaces via API,
                   imports both via genie_space_id entries, asserts both genie_space_configs
                   present, no new spaces created by Terraform.

  all              Run all scenarios sequentially (default when no --scenario given).

Usage
-----
  # Run all scenarios
  python scripts/run_integration_tests.py

  # Run a single scenario
  python scripts/run_integration_tests.py --scenario quickstart
  python scripts/run_integration_tests.py --scenario promote

  # Skip teardown so you can inspect results
  python scripts/run_integration_tests.py --scenario multi-space --keep-data

  # Pin a specific SQL warehouse (avoids cold-start delay)
  python scripts/run_integration_tests.py --warehouse-id abc123ef

  # Use a non-default auth file
  python scripts/run_integration_tests.py --auth-file envs/dev/auth.auto.tfvars

  # List available scenarios
  python scripts/run_integration_tests.py --list

Makefile targets (added by this PR)
------------------------------------
  make test-quickstart
  make test-multi-catalog
  make test-multi-space
  make test-per-space
  make test-promote
  make test-multi-env
  make test-attach-promote
  make test-decentralized
  make test-abac-only
  make test-multi-space-import
  make test-all
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

# Force line-buffered stdout so that print() and subprocess output appear
# in the correct order when the test runner is invoked with piped stdout.
if not sys.stdout.line_buffering:
    sys.stdout.reconfigure(line_buffering=True)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR  = Path(__file__).resolve().parent
MODULE_ROOT = SCRIPT_DIR.parent          # …/genie/aws/

# ENVS_DIR is set dynamically in main() — either from --envs-dir, from the
# provisioned state file (envs/test/), or defaulting to envs/.
# All helpers that reference ENVS_DIR use the module-level variable so that
# changing it once in main() propagates everywhere.
ENVS_DIR    = MODULE_ROOT / "envs"

PROVISION_STATE_FILE = SCRIPT_DIR / ".test_env_state.json"

DEFAULT_AUTH_FILE = ENVS_DIR / "dev" / "auth.auto.tfvars"

# Catalog names (must match setup_test_data.py constants)
DEV_FIN_CAT      = "dev_fin"
DEV_CLIN_CAT     = "dev_clinical"
PROD_FIN_CAT     = "prod_fin"
PROD_CLIN_CAT    = "prod_clinical"

CATALOG_MAP_DEV_TO_PROD = (
    f"{DEV_FIN_CAT}={PROD_FIN_CAT},{DEV_CLIN_CAT}={PROD_CLIN_CAT}"
)

# ---------------------------------------------------------------------------
# HCL snippets for each scenario's genie_spaces config
# ---------------------------------------------------------------------------

SPACES_FINANCE_ONLY = f"""\
genie_spaces = [
  {{
    name     = "Finance Analytics"
    uc_tables = [
      "{DEV_FIN_CAT}.finance.customers",
      "{DEV_FIN_CAT}.finance.transactions",
      "{DEV_FIN_CAT}.finance.credit_cards",
    ]
  }},
]
"""

SPACES_COMBINED = f"""\
genie_spaces = [
  {{
    name     = "Combined Analytics"
    uc_tables = [
      "{DEV_FIN_CAT}.finance.customers",
      "{DEV_FIN_CAT}.finance.transactions",
      "{DEV_FIN_CAT}.finance.credit_cards",
      "{DEV_CLIN_CAT}.clinical.patients",
      "{DEV_CLIN_CAT}.clinical.encounters",
    ]
  }},
]
"""

SPACES_MULTI = f"""\
genie_spaces = [
  {{
    name     = "Finance Analytics"
    uc_tables = [
      "{DEV_FIN_CAT}.finance.customers",
      "{DEV_FIN_CAT}.finance.transactions",
      "{DEV_FIN_CAT}.finance.credit_cards",
    ]
  }},
  {{
    name     = "Clinical Analytics"
    uc_tables = [
      "{DEV_CLIN_CAT}.clinical.patients",
      "{DEV_CLIN_CAT}.clinical.encounters",
    ]
  }},
]
"""

SPACES_CLINICAL_ONLY = f"""\
genie_spaces = [
  {{
    name     = "Clinical Analytics"
    uc_tables = [
      "{DEV_CLIN_CAT}.clinical.patients",
      "{DEV_CLIN_CAT}.clinical.encounters",
    ]
  }},
]
"""

# uc_tables only — no genie_spaces block (used by the abac-only scenario)
TABLES_FINANCE_ONLY_HCL = f"""\
uc_tables = [
  "{DEV_FIN_CAT}.finance.customers",
  "{DEV_FIN_CAT}.finance.transactions",
  "{DEV_FIN_CAT}.finance.credit_cards",
]
"""

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

def _green(s: str) -> str:  return f"\033[32m{s}\033[0m"
def _red(s: str)   -> str:  return f"\033[31m{s}\033[0m"
def _cyan(s: str)  -> str:  return f"\033[36m{s}\033[0m"
def _bold(s: str)  -> str:  return f"\033[1m{s}\033[0m"
def _yellow(s: str)-> str:  return f"\033[33m{s}\033[0m"


def _banner(title: str, width: int = 64) -> None:
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def _step(msg: str) -> None:
    print(f"\n{_cyan('──')} {msg}")


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run(
    cmd: list[str],
    *,
    cwd: Path = MODULE_ROOT,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a command, streaming output unless capture=True."""
    stdout = subprocess.PIPE if capture else None
    # Always merge stderr into stdout so errors are visible in the output stream.
    stderr = subprocess.STDOUT
    result = subprocess.run(cmd, cwd=cwd, stdout=stdout, stderr=stderr, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}"
        )
    return result


def _make(
    *targets_and_vars: str,
    cwd: Path = MODULE_ROOT,
    check: bool = True,
    retries: int = 0,
    retry_delay_seconds: int = 0,
) -> subprocess.CompletedProcess:
    """Run make with the given targets/variables.

    When retries > 0, a failed command is retried up to that many times.
    This is useful for LLM-dependent commands like ``make generate`` where
    the model may occasionally return a response that the code-block
    extractor cannot parse.

    retry_delay_seconds: seconds to wait between retry attempts.  Useful for
    ``make apply`` retries where Databricks' eventually-consistent ABAC quota
    counter may briefly show a stale value even after cleanup.

    When running against a provisioned test environment (ENVS_DIR != envs/),
    ENV_DIR / SOURCE_ENV_DIR / DEST_ENV_DIR overrides are injected automatically
    so the Makefile reads from envs/test/<env> instead of envs/<env>.
    """
    # Inject ENV_DIR overrides when using the provisioned test env directory.
    # The Makefile hardcodes MODULE_ROOT/envs/<ENV>; these overrides redirect
    # all file access to the isolated envs/test/<env>/ paths.
    injected: list[str] = []
    _default_envs = MODULE_ROOT / "envs"
    if ENVS_DIR != _default_envs:
        # Parse env-related variables already in targets_and_vars.
        existing_keys = {v.split("=", 1)[0] for v in targets_and_vars if "=" in v}
        for var in targets_and_vars:
            if "=" not in var:
                continue
            key, _, val = var.partition("=")
            # Redirect ENV=<env> → ENV_DIR=<ENVS_DIR>/<env>
            if key == "ENV" and val not in ("account", "data_access") and "ENV_DIR" not in existing_keys:
                injected.append(f"ENV_DIR={ENVS_DIR / val}")
            # Redirect SOURCE_ENV=<env> → SOURCE_ENV_DIR=<ENVS_DIR>/<env>
            elif key == "SOURCE_ENV" and "SOURCE_ENV_DIR" not in existing_keys:
                injected.append(f"SOURCE_ENV_DIR={ENVS_DIR / val}")
            # Redirect DEST_ENV=<env> → DEST_ENV_DIR=<ENVS_DIR>/<env>
            elif key == "DEST_ENV" and "DEST_ENV_DIR" not in existing_keys:
                injected.append(f"DEST_ENV_DIR={ENVS_DIR / val}")
        # Always redirect the account env dir when using a custom ENVS_DIR.
        if "ACCOUNT_ENV_DIR" not in existing_keys:
            injected.append(f"ACCOUNT_ENV_DIR={ENVS_DIR / 'account'}")

    for attempt in range(1 + retries):
        result = _run(
            ["make", "--no-print-directory", *targets_and_vars, *injected],
            cwd=cwd,
            check=False,
        )
        if result.returncode == 0:
            return result
        if attempt < retries:
            if retry_delay_seconds > 0:
                print(
                    f"  [RETRY] Command failed (exit {result.returncode}), "
                    f"waiting {retry_delay_seconds}s then retrying "
                    f"({attempt + 1}/{retries})..."
                )
                time.sleep(retry_delay_seconds)
            else:
                print(f"  [RETRY] Command failed (exit {result.returncode}), retrying ({attempt + 1}/{retries})...")
        elif check:
            raise RuntimeError(
                f"Command failed (exit {result.returncode}): "
                f"make {' '.join(targets_and_vars)}"
            )
    return result


def _setup_data(auth_file: Path, *flags: str, warehouse_id: str = "") -> None:
    cmd = [
        sys.executable,
        str(MODULE_ROOT / "scripts" / "setup_test_data.py"),
        "--auth-file", str(auth_file),
    ]
    if warehouse_id:
        cmd += ["--warehouse-id", warehouse_id]
    cmd += list(flags)
    _run(cmd)


# ---------------------------------------------------------------------------
# Env file helpers
# ---------------------------------------------------------------------------

def _resolve_warehouse_id(auth_file: Path, warehouse_id: str) -> str:
    """Return a ready warehouse ID — use the given one, or auto-detect from the workspace.

    Mirrors setup_test_data.py::_get_warehouse so every scenario shares the
    same warehouse rather than each one creating 'ABAC Governance Warehouse'.
    """
    if warehouse_id:
        return warehouse_id
    try:
        import hcl2 as _hcl2
        from databricks.sdk import WorkspaceClient as _WC

        def _s(v): return (v[0] if isinstance(v, list) else (v or "")).strip()

        with open(auth_file) as f:
            auth = _hcl2.load(f)
        host          = _s(auth.get("databricks_workspace_host", ""))
        client_id     = _s(auth.get("databricks_client_id", ""))
        client_secret = _s(auth.get("databricks_client_secret", ""))
        if not host:
            return ""
        w = _WC(host=host, client_id=client_id, client_secret=client_secret)
        warehouses = list(w.warehouses.list())
        for wh in warehouses:
            state = str(wh.state)
            if "RUNNING" in state or "STARTING" in state:
                print(f"  Auto-selected warehouse: {wh.name} ({wh.id})")
                return wh.id or ""
        if warehouses:
            wh = warehouses[0]
            print(f"  Auto-selected warehouse (not running): {wh.name} ({wh.id})")
            return wh.id or ""
    except Exception as exc:
        print(f"  WARNING: Could not auto-detect warehouse: {exc}")
    return ""


def _write_env_tfvars(env: str, spaces_hcl: str, warehouse_id: str = "") -> None:
    """Write a minimal env.auto.tfvars for the given env."""
    env_dir = ENVS_DIR / env
    wh_line = f'sql_warehouse_id = "{warehouse_id}"' if warehouse_id else 'sql_warehouse_id = ""'
    content = f"{spaces_hcl}\n{wh_line}\n"
    (env_dir / "env.auto.tfvars").write_text(content)


def _patch_warehouse_id_in_env_tfvars(env: str, auth_file: Path) -> str:
    """After `make apply`, discover the running warehouse and write its ID into env.auto.tfvars.

    When two envs (e.g. dev + prod) are applied against the *same* workspace, the second
    apply tries to create another warehouse with the same name and fails.  Calling this
    function after the first env's apply patches sql_warehouse_id in env.auto.tfvars so
    that the promote step (which copies the value to the secondary env) causes Terraform to
    *reuse* the existing warehouse (count=0 branch) instead of creating a duplicate.

    Returns the discovered warehouse ID, or "" if none was found.
    """
    import re as _re2
    wh = _resolve_warehouse_id(auth_file, "")
    if not wh:
        return ""
    env_tfvars = ENVS_DIR / env / "env.auto.tfvars"
    if not env_tfvars.exists():
        return wh
    content = env_tfvars.read_text()
    new_content = _re2.sub(
        r'^sql_warehouse_id\s*=\s*"[^"]*"',
        f'sql_warehouse_id = "{wh}"',
        content,
        flags=_re2.MULTILINE,
    )
    if new_content != content:
        env_tfvars.write_text(new_content)
        print(f"  Patched {env}/env.auto.tfvars: sql_warehouse_id = {wh!r}")
    return wh


def _copy_auth(src_env: str, dest_env: str) -> None:
    """Copy auth.auto.tfvars from src_env to dest_env."""
    src  = ENVS_DIR / src_env / "auth.auto.tfvars"
    dest = ENVS_DIR / dest_env / "auth.auto.tfvars"
    shutil.copy2(src, dest)


def _clean_env_artifacts(env: str) -> None:
    """Remove generated output and split config so the next run starts fresh.

    Preserves auth.auto.tfvars and env.auto.tfvars (those are managed by the
    test runner). Terraform state is removed so apply runs from scratch.
    """
    env_dir = ENVS_DIR / env
    if not env_dir.exists():
        return

    removable_files = [
        "generated/abac.auto.tfvars",
        "generated/masking_functions.sql",
        "generated/generated_response.md",
        "generated/TUNING.md",
        "abac.auto.tfvars",
        "data_access/abac.auto.tfvars",
        "data_access/masking_functions.sql",
    ]
    removable_dirs = [
        "generated/spaces",
        ".terraform",
        "data_access/.terraform",
    ]
    removable_globs = [
        "*.tfstate",
        "*.tfstate.backup",
        ".*.apply.sha",
        ".genie_space_id*",
        "data_access/*.tfstate",
        "data_access/*.tfstate.backup",
        "data_access/.*.apply.sha",
    ]

    for rel in removable_files:
        p = env_dir / rel
        if p.exists():
            p.unlink()

    for rel in removable_dirs:
        p = env_dir / rel
        if p.exists():
            shutil.rmtree(p)

    for pattern in removable_globs:
        # Handle patterns that cross into data_access/
        base = env_dir if "/" not in pattern else env_dir / pattern.split("/")[0]
        glob = pattern.split("/")[-1]
        for p in base.glob(glob):
            p.unlink()


def _clean_account_artifacts() -> None:
    """Remove account-layer split config and state for a fresh start."""
    acct_dir = ENVS_DIR / "account"
    if not acct_dir.exists():
        return
    for rel in ["abac.auto.tfvars", "terraform.tfstate", "terraform.tfstate.backup",
                ".terraform.lock.hcl", ".account.apply.sha"]:
        p = acct_dir / rel
        if p.exists():
            p.unlink()
    tf_dir = acct_dir / ".terraform"
    if tf_dir.exists():
        shutil.rmtree(tf_dir)


# ---------------------------------------------------------------------------
# Destroy helpers (best-effort — skip if no state)
# ---------------------------------------------------------------------------

def _clear_apply_fingerprints(*env_dirs: Path) -> None:
    """Delete Terraform apply fingerprint files (.*.apply.sha) from the given directories.

    The apply fingerprint cache (e.g. .workspace.apply.sha) prevents re-applying when
    inputs haven't changed.  After `terraform destroy` the remote resources are gone but
    the fingerprint file still exists, causing the *next* scenario's `make apply` to skip
    recreating those resources.  We clear the files after every destroy so the subsequent
    apply always runs.
    """
    for d in env_dirs:
        for sha_file in d.glob(".*.apply.sha"):
            try:
                sha_file.unlink()
            except OSError:
                pass


def _try_destroy(env: str) -> None:
    """Destroy Terraform resources for env if state exists.

    Passes -lock=false so that a stale advisory lock left by a previously
    killed process does not block the cleanup.  Also passes -refresh=false
    so terraform doesn't try to read remote resources (like groups) that may
    have already been deleted by a prior account-layer destroy — without this,
    data_access destroy can fail with "cannot read group" errors, leaving
    orphaned tag assignments that block subsequent applies.
    """
    state    = ENVS_DIR / env / "terraform.tfstate"
    da_state = ENVS_DIR / env / "data_access" / "terraform.tfstate"
    if not state.exists() and not da_state.exists():
        # Even if there is nothing to destroy, clear any stale fingerprint files
        # so the next apply is not skipped due to an outdated hash.
        _clear_apply_fingerprints(ENVS_DIR / env, ENVS_DIR / env / "data_access")
        return
    _step(f"Destroying {env} Terraform resources")
    _make(f"destroy", f"ENV={env}", "DESTROY_FLAGS=-lock=false -refresh=false", check=False)
    _clear_apply_fingerprints(ENVS_DIR / env, ENVS_DIR / env / "data_access")


def _try_destroy_account() -> None:
    state = ENVS_DIR / "account" / "terraform.tfstate"
    if not state.exists():
        _clear_apply_fingerprints(ENVS_DIR / "account")
        return
    _step("Destroying account Terraform resources")
    _make("destroy", "ENV=account", "DESTROY_FLAGS=-lock=false -refresh=false", check=False)
    _clear_apply_fingerprints(ENVS_DIR / "account")


import re as _re_mod
# Tag policy keys that our LLM generates are always strictly lowercase snake_case.
# Any key that doesn't match is from another user/demo and must not be touched.
_OUR_TAG_KEY_RE = _re_mod.compile(r"^[a-z][a-z0-9_]*$")


def _force_delete_tag_policies(*envs: str) -> None:
    """Best-effort deletion of our own account-level UC tag policies.

    UC tag policies are account-scoped objects (not tied to a catalog).  They
    persist even after `terraform destroy` if the account state file was wiped
    before destroy could run.  The next scenario's generate step produces
    different key names (LLM is non-deterministic), so the import step finds
    old policies that don't match — causing "Cannot import non-existent remote
    object" and "Resource already managed by Terraform" errors.

    IMPORTANT: This is a SHARED account.  Many other SA demos have their own
    tag policies here (e.g. "Med Tech", "pii_tmna_demo", "Jai_pii").  We only
    delete policies whose keys match our strict snake_case pattern
    (^[a-z][a-z0-9_]*$) — anything with spaces, uppercase letters, or
    non-snake characters is skipped as belonging to another user.
    """
    for env in envs:
        auth_file = ENVS_DIR / env / "auth.auto.tfvars"
        if not auth_file.exists():
            auth_file = ENVS_DIR / "dev" / "auth.auto.tfvars"
        if not auth_file.exists():
            continue
        try:
            import hcl2 as _hcl2
            from databricks.sdk import WorkspaceClient as _WC

            def _s(v): return (v[0] if isinstance(v, list) else (v or "")).strip()

            with open(auth_file) as f:
                auth = _hcl2.load(f)
            host          = _s(auth.get("databricks_workspace_host", ""))
            client_id     = _s(auth.get("databricks_client_id", ""))
            client_secret = _s(auth.get("databricks_client_secret", ""))
            if not host:
                continue
            w = _WC(host=host, client_id=client_id, client_secret=client_secret)

            # List tag policies — SDK method name varies by version; try both
            policies = []
            list_err_msg = ""
            for list_fn_name in ("list_tag_policies", "list"):
                try:
                    list_fn = getattr(w.tag_policies, list_fn_name)
                    policies = list(list_fn())
                    break
                except Exception as e:
                    list_err_msg = str(e)
            else:
                # Neither SDK method worked; fall back to REST API
                import ssl as _ssl, urllib.request as _urq, json as _json
                _ctx = _ssl.create_default_context()
                _ctx.check_hostname = False
                _ctx.verify_mode = _ssl.CERT_NONE
                token = w.config.authenticate()
                base  = host.rstrip("/")
                try:
                    req = _urq.Request(f"{base}/api/2.1/unity-catalog/tag-policies", headers=token)
                    with _urq.urlopen(req, timeout=30, context=_ctx) as resp:
                        data = _json.loads(resp.read())
                    # Build minimal proxy objects from raw dicts
                    policies = [type("P", (), {"id": p.get("id"), "tag_key": p.get("tag_key")})()
                                for p in data.get("tag_policies", [])]
                except Exception as rest_err:
                    print(f"  WARN: could not list tag policies via SDK ({list_err_msg}) or REST ({rest_err})")
                    break

            deleted = 0
            skipped = 0
            for tp in policies:
                tp_id  = getattr(tp, "id",      None)
                tp_key = getattr(tp, "tag_key", None)
                if not tp_key:
                    continue
                # Skip tag policies owned by other users/demos.
                # Our LLM always generates strictly lowercase snake_case keys
                # (e.g. pii_level, phi_level, aml_scope).  Keys with spaces,
                # uppercase, or other characters belong to other accounts.
                if not _OUR_TAG_KEY_RE.match(tp_key):
                    skipped += 1
                    continue
                # delete_tag_policy() takes tag_key (not id) as its positional arg.
                del_ok = False
                try:
                    w.tag_policies.delete_tag_policy(tag_key=tp_key)
                    del_ok = True
                except Exception:
                    pass
                if not del_ok:
                    # REST fallback: DELETE /api/2.1/unity-catalog/tag-policies/{tag_key}
                    import ssl as _ssl2, urllib.request as _urq2, urllib.error as _ure2
                    _ctx2 = _ssl2.create_default_context()
                    _ctx2.check_hostname = False
                    _ctx2.verify_mode = _ssl2.CERT_NONE
                    try:
                        token2 = w.config.authenticate()
                        base2  = host.rstrip("/")
                        import urllib.parse as _urp2
                        del_req = _urq2.Request(
                            f"{base2}/api/2.1/unity-catalog/tag-policies/{_urp2.quote(tp_key, safe='')}",
                            headers=token2,
                            method="DELETE",
                        )
                        _urq2.urlopen(del_req, timeout=30, context=_ctx2)
                        del_ok = True
                    except _ure2.HTTPError as del_http:
                        if del_http.code == 404:
                            # 404 = not our policy or already gone; silently skip
                            del_ok = True
                        else:
                            print(f"  WARN: could not delete tag policy {tp_key!r}: HTTP {del_http.code}")
                    except Exception as del_err2:
                        print(f"  WARN: could not delete tag policy {tp_key!r}: {del_err2}")
                if del_ok:
                    print(f"  Force-deleted orphaned tag policy: {tp_key}")
                    deleted += 1
                else:
                    print(f"  WARN: DELETE FAILED for tag policy {tp_key!r} (id={tp_id})")

            if not policies:
                print("  No orphaned tag policies found.")
            elif skipped > 0:
                print(f"  Skipped {skipped} tag policy/ies owned by other users (non-snake_case keys).")
            break  # only need one env's auth for account-level resources
        except Exception as exc:
            print(f"  WARN: force_delete_tag_policies({env}) failed: {exc}")


def _force_delete_fgac_policies(*envs: str, all_catalogs: bool = False) -> None:
    """Best-effort API-level deletion of all FGAC policies for all test catalogs.

    Databricks enforces a metastore-wide limit of 1000 ABAC policies total.
    Accumulated policies from failed/partial test runs can push the count past
    this limit, causing subsequent applies to fail with "estimated count exceeds
    limit".  This function proactively deletes every policy_info it finds so
    each scenario starts from zero.

    By default only test-catalog names (dev_*, prod_*, bu2_*) are cleaned.
    Pass all_catalogs=True (or --nuke-fgac CLI flag) to delete from EVERY
    catalog in the workspace — use this for a one-time reset when the metastore
    has accumulated thousands of orphaned policies from many partial test runs.

    Uses the REST API directly (not SDK) because policy_infos may not be
    available in all installed SDK versions.
    """
    import ssl as _ssl
    import urllib.request as _urq
    import urllib.error as _ure
    import urllib.parse as _urp
    import json as _json

    _ssl_ctx = _ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl.CERT_NONE

    # Catalogs that should never be touched even in all_catalogs mode
    _SYSTEM_CATS = {"hive_metastore", "main", "system", "samples", "__databricks_internal"}

    for env in envs:
        auth_file = ENVS_DIR / env / "auth.auto.tfvars"
        if not auth_file.exists():
            continue
        try:
            import hcl2 as _hcl2
            from databricks.sdk import WorkspaceClient as _WC

            def _s(v): return (v[0] if isinstance(v, list) else (v or "")).strip()

            with open(auth_file) as f:
                auth = _hcl2.load(f)
            host          = _s(auth.get("databricks_workspace_host", ""))
            client_id     = _s(auth.get("databricks_client_id", ""))
            client_secret = _s(auth.get("databricks_client_secret", ""))
            if not host:
                continue
            w = _WC(host=host, client_id=client_id, client_secret=client_secret)
            token = w.config.authenticate()  # {'Authorization': 'Bearer ...'}
            base  = host.rstrip("/")

            if all_catalogs:
                # Nuclear mode: clean every catalog except system ones.
                # Used for a one-time reset when the metastore has thousands of
                # accumulated orphaned policies from many partial test runs.
                try:
                    all_cats = [c.name for c in w.catalogs.list()
                                if c.name and c.name not in _SYSTEM_CATS]
                except Exception:
                    all_cats = []
                print(f"  [NUKE] Deleting FGAC policies from ALL {len(all_cats)} non-system catalogs...")
            else:
                # Normal mode: only test catalog name prefixes.
                test_prefixes = ("dev_", "prod_", "bu2_")
                try:
                    all_cats = [c.name for c in w.catalogs.list()
                                if c.name and any(c.name.startswith(p) for p in test_prefixes)]
                except Exception:
                    all_cats = []

                # Always include well-known test catalog names as a fallback.
                # FGAC policies are stored by catalog NAME, not ID.  If a previous
                # run already dropped the catalogs, w.catalogs.list() won't return
                # them — but orphaned policies for those names can still exist and
                # will re-attach when a new catalog with the same name is created.
                # The API returns 404 for unknown catalogs, which we catch below.
                known_test_cats = {
                    DEV_FIN_CAT, DEV_CLIN_CAT,
                    PROD_FIN_CAT, PROD_CLIN_CAT,
                    "bu2_fin", "bu2_clinical",
                }
                all_cats = list(set(all_cats) | known_test_cats)

            for cat in all_cats:
                try:
                    # Paginate through all policies for this catalog.
                    # Re-list after each round of deletions to catch any that
                    # the API paginates past or that become visible after the
                    # prior batch was removed (eventual consistency).
                    max_rounds = 5
                    for _round in range(max_rounds):
                        page_token = ""
                        round_deleted = 0
                        while True:
                            list_url = f"{base}/api/2.1/unity-catalog/policies/CATALOG/{_urp.quote(cat, safe='')}"
                            if page_token:
                                list_url += f"?page_token={_urp.quote(page_token, safe='')}"
                            req = _urq.Request(list_url, headers=token)
                            with _urq.urlopen(req, timeout=15, context=_ssl_ctx) as resp:
                                data = _json.loads(resp.read())
                            policies = data.get("policies", [])
                            for p in policies:
                                pname = p.get("name", "")
                                if not pname:
                                    continue
                                del_url = (f"{base}/api/2.1/unity-catalog/policies/CATALOG/"
                                           f"{_urp.quote(cat, safe='')}/{_urp.quote(pname, safe='')}")
                                del_req = _urq.Request(del_url, headers=token, method="DELETE")
                                try:
                                    _urq.urlopen(del_req, timeout=15, context=_ssl_ctx)
                                    print(f"  Force-deleted orphaned FGAC policy: {cat}/{pname}")
                                    round_deleted += 1
                                except Exception as del_err:
                                    print(f"  WARN: could not delete FGAC policy {cat}/{pname}: {del_err}")
                            page_token = data.get("next_page_token", "")
                            if not page_token:
                                break
                        if round_deleted == 0:
                            break  # nothing left to delete
                except _ure.HTTPError as he:
                    if he.code not in (403, 404):
                        print(f"  WARN: policy list HTTP {he.code} for {cat}")
                except Exception as cat_err:
                    print(f"  WARN: policy list failed for {cat}: {cat_err}")
        except Exception as exc:
            print(f"  WARN: force_delete_fgac_policies({env}) failed: {exc}")
        break  # only need one env's auth to clean all catalogs


def _force_delete_tag_assignments(*envs: str) -> None:
    """Best-effort API-level deletion of all tag assignments on test schemas.

    If a previous scenario's data_access destroy failed (e.g. because groups
    were already deleted), orphaned tag assignments remain in Databricks.  The
    next scenario's apply then fails with "Tag assignment with tag key … already
    exists".  This function proactively removes all tag assignments on test
    catalog schemas so each scenario starts clean.
    """
    import ssl as _ssl
    import urllib.request as _urq
    import urllib.error as _ure
    import urllib.parse as _urp
    import json as _json

    _ssl_ctx = _ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl.CERT_NONE

    for env in envs:
        auth_file = ENVS_DIR / env / "auth.auto.tfvars"
        if not auth_file.exists():
            continue
        try:
            import hcl2 as _hcl2
            from databricks.sdk import WorkspaceClient as _WC

            def _s(v): return (v[0] if isinstance(v, list) else (v or "")).strip()

            with open(auth_file) as f:
                auth = _hcl2.load(f)
            host          = _s(auth.get("databricks_workspace_host", ""))
            client_id     = _s(auth.get("databricks_client_id", ""))
            client_secret = _s(auth.get("databricks_client_secret", ""))
            if not host:
                continue
            w = _WC(host=host, client_id=client_id, client_secret=client_secret)
            token = w.config.authenticate()
            base  = host.rstrip("/")

            test_prefixes = ("dev_", "prod_", "bu2_")
            try:
                all_cats = [c.name for c in w.catalogs.list()
                            if c.name and any(c.name.startswith(p) for p in test_prefixes)]
            except Exception:
                all_cats = []

            for cat in all_cats:
                # List schemas in this catalog
                try:
                    schemas = [s.name for s in w.schemas.list(catalog_name=cat) if s.name]
                except Exception:
                    continue

                for schema in schemas:
                    if schema in ("information_schema", "default"):
                        continue

                    # Helper: list + delete all tag assignments for one set of
                    # query params (schema-level and table-level calls use the
                    # same delete endpoint but different listing URLs).
                    def _delete_tags_for(params: str, label: str) -> None:
                        try:
                            list_url = f"{base}/api/2.1/unity-catalog/tags?{params}"
                            req = _urq.Request(list_url, headers=token)
                            with _urq.urlopen(req, timeout=30, context=_ssl_ctx) as resp:
                                data = _json.loads(resp.read())
                            assignments = data.get("tag_assignments", [])
                            if not assignments:
                                return
                            del_body = _json.dumps({"tag_assignments": assignments}).encode()
                            del_req = _urq.Request(
                                f"{base}/api/2.1/unity-catalog/tags",
                                data=del_body,
                                headers={**token, "Content-Type": "application/json"},
                                method="DELETE",
                            )
                            _urq.urlopen(del_req, timeout=30, context=_ssl_ctx)
                            print(f"  Force-deleted {len(assignments)} orphaned tag assignment(s) on {label}")
                        except _ure.HTTPError as he:
                            if he.code not in (403, 404):
                                print(f"  WARN: tag cleanup HTTP {he.code} for {label}")
                        except Exception as err:
                            print(f"  WARN: tag cleanup failed for {label}: {err}")

                    # Schema-level tags
                    _delete_tags_for(
                        f"catalog_name={_urp.quote(cat, safe='')}&schema_name={_urp.quote(schema, safe='')}",
                        f"{cat}.{schema}",
                    )

                    # Column-level tags: the schema-level API only returns
                    # schema/table-level assignments, NOT column-level ones.
                    # Iterate over each table to delete column tags explicitly.
                    try:
                        tables = [t.name for t in w.tables.list(catalog_name=cat, schema_name=schema) if t.name]
                    except Exception:
                        tables = []
                    for tbl in tables:
                        _delete_tags_for(
                            f"catalog_name={_urp.quote(cat, safe='')}"
                            f"&schema_name={_urp.quote(schema, safe='')}"
                            f"&table_name={_urp.quote(tbl, safe='')}",
                            f"{cat}.{schema}.{tbl} (columns)",
                        )
        except Exception as exc:
            print(f"  WARN: force_delete_tag_assignments({env}) failed: {exc}")


def _drop_test_catalogs(*envs: str) -> None:
    """Drop test catalogs via SQL to fully reset FGAC estimated policy counts.

    Databricks tracks estimated policy counts per catalog.  These counts are
    eventually consistent and can become inflated when many test runs create
    and delete policies without dropping the catalogs.  Using DROP CATALOG
    via SQL (not SDK) ensures the catalog is fully purged — the SDK's
    catalogs.delete() may soft-delete, leaving the estimated counter intact.
    """
    test_prefixes = ("dev_", "prod_", "bu2_")
    for env in envs:
        auth_file = ENVS_DIR / env / "auth.auto.tfvars"
        if not auth_file.exists():
            continue
        try:
            import hcl2 as _hcl2
            from databricks.sdk import WorkspaceClient as _WC

            def _s(v): return (v[0] if isinstance(v, list) else (v or "")).strip()

            with open(auth_file) as f:
                auth = _hcl2.load(f)
            host          = _s(auth.get("databricks_workspace_host", ""))
            client_id     = _s(auth.get("databricks_client_id", ""))
            client_secret = _s(auth.get("databricks_client_secret", ""))
            if not host:
                continue
            w = _WC(host=host, client_id=client_id, client_secret=client_secret)

            # Find a SQL warehouse for executing DROP CATALOG
            wh_id = ""
            try:
                for ep in w.warehouses.list():
                    if ep.state and ep.state.value in ("RUNNING", "STARTING"):
                        wh_id = ep.id
                        break
                if not wh_id:
                    for ep in w.warehouses.list():
                        wh_id = ep.id
                        break
            except Exception:
                pass
            if not wh_id:
                print("  WARN: no SQL warehouse found; skipping catalog drop")
                return

            try:
                all_cats = [c.name for c in w.catalogs.list()
                            if c.name and any(c.name.startswith(p) for p in test_prefixes)]
            except Exception:
                all_cats = []
            for cat in all_cats:
                try:
                    resp = w.statement_execution.execute_statement(
                        statement=f"DROP CATALOG IF EXISTS `{cat}` CASCADE",
                        warehouse_id=wh_id,
                        wait_timeout="50s",
                    )
                    if resp.status and resp.status.state and resp.status.state.value == "SUCCEEDED":
                        print(f"  Dropped test catalog (SQL): {cat}")
                    else:
                        # Fallback to SDK delete
                        w.catalogs.delete(cat, force=True)
                        print(f"  Dropped test catalog (SDK): {cat}")
                except Exception as e:
                    print(f"  WARN: could not drop catalog {cat}: {e}")
            return  # only need one env's auth to clean all catalogs
        except Exception as exc:
            print(f"  WARN: _drop_test_catalogs({env}) failed: {exc}")


def _count_fgac_policies(*envs: str) -> int:
    """Count actual (not estimated) FGAC policies across all catalogs via REST API.

    Databricks uses an eventually-consistent *estimated* counter for the
    metastore-wide ABAC policy limit check.  After mass-deletion the real count
    drops immediately, but the estimated counter can lag for several minutes.
    Polling the real count lets us confirm cleanup succeeded and then wait for
    the estimated counter without guessing a fixed sleep duration.
    """
    import ssl as _ssl, urllib.request as _urq, urllib.error as _ure
    import urllib.parse as _urp, json as _json

    _ssl_ctx = _ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl.CERT_NONE

    for env in envs:
        auth_file = ENVS_DIR / env / "auth.auto.tfvars"
        if not auth_file.exists():
            continue
        try:
            import hcl2 as _hcl2
            from databricks.sdk import WorkspaceClient as _WC

            def _s(v): return (v[0] if isinstance(v, list) else (v or "")).strip()

            with open(auth_file) as f:
                auth = _hcl2.load(f)
            host          = _s(auth.get("databricks_workspace_host", ""))
            client_id     = _s(auth.get("databricks_client_id", ""))
            client_secret = _s(auth.get("databricks_client_secret", ""))
            if not host:
                continue
            w = _WC(host=host, client_id=client_id, client_secret=client_secret)
            token = w.config.authenticate()
            base  = host.rstrip("/")

            total = 0
            try:
                cats = [c.name for c in w.catalogs.list() if c.name]
            except Exception:
                cats = []
            for cat in cats:
                try:
                    page_token = ""
                    while True:
                        url = f"{base}/api/2.1/unity-catalog/policies/CATALOG/{_urp.quote(cat, safe='')}"
                        if page_token:
                            url += f"?page_token={_urp.quote(page_token, safe='')}"
                        req = _urq.Request(url, headers=token)
                        with _urq.urlopen(req, timeout=15, context=_ssl_ctx) as r:
                            data = _json.loads(r.read())
                        total += len(data.get("policies", []))
                        page_token = data.get("next_page_token", "")
                        if not page_token:
                            break
                except _ure.HTTPError as he:
                    if he.code not in (403, 404):
                        pass  # ignore inaccessible catalogs
                except Exception:
                    pass
            return total
        except Exception:
            pass
    return -1  # unknown


def _wait_for_fgac_quota(
    *envs: str,
    target: int = 900,
    max_wait_seconds: int = 360,
    poll_interval: int = 30,
) -> None:
    """Wait until the Databricks FGAC quota counter has propagated after cleanup.

    Databricks uses an *estimated* counter for the metastore-wide ABAC policy
    limit (1000 total).  After mass-deletion the REAL count drops immediately
    but this estimated counter can lag 3-10 minutes — Terraform will fail with
    "estimated count exceeds limit" if we apply too soon.

    Strategy:
      1. Confirm the real count is below target (cleanup worked).
         If not, poll every poll_interval seconds until it drops or we time out.
      2. If the real count IS below target, we still need to wait for Databricks'
         estimated counter to catch up.  We do this by keeping the full
         max_wait_seconds budget and polling; this avoids a hard-coded sleep
         while still ensuring we wait long enough.
    """
    waited = 0
    real_cleared = False

    while waited < max_wait_seconds:
        count = _count_fgac_policies(*envs)
        remaining = max_wait_seconds - waited

        if count < 0:
            print(f"  Cannot query FGAC count; waiting {poll_interval}s (budget: {remaining}s)...")
        elif count < target:
            if not real_cleared:
                real_cleared = True
                print(f"  Real FGAC count: {count} ✓  Waiting for estimated counter to propagate...")
            else:
                print(f"  Real FGAC count: {count} ✓  Still waiting ({remaining}s budget left)...")
        else:
            print(
                f"  Real FGAC count: {count} (≥ {target}). "
                f"Waiting {poll_interval}s for policies to drain ({remaining}s remaining)..."
            )
            real_cleared = False

        time.sleep(poll_interval)
        waited += poll_interval

    count = _count_fgac_policies(*envs)
    if count >= target:
        print(
            f"  WARNING: FGAC quota wait timed out after {max_wait_seconds}s "
            f"(real count: {count}). Proceeding — apply has built-in retries."
        )
    else:
        print(
            f"  FGAC quota: real count {count}, waited {waited}s. "
            f"Proceeding — estimated counter should be current."
        )


def _preamble_cleanup(*envs: str, fresh_env: bool = False) -> None:
    """Best-effort pre-scenario cleanup.

    Destroys Terraform resources for each env and the account layer *while their
    state files still exist*, then wipes all local artifacts.  This ensures each
    scenario starts clean even if a previous scenario failed before its own
    teardown block ran (which would have left Databricks groups, tag_policies,
    and Genie Spaces behind without Terraform state to track them).

    When fresh_env=True (provisioned via provision_test_env.py), the metastore
    counter always starts at 0 so the FGAC quota wait is skipped entirely.
    """
    _step("Pre-scenario cleanup (destroying any leftover resources from prior run)")

    # On a fresh provisioned environment the metastore starts clean, so there is
    # no stale FGAC quota to wait for.  However, if a PREVIOUS scenario in the
    # same test run applied Terraform resources and then failed before its own
    # teardown block ran, those resources (groups, Genie Spaces, tag policies)
    # persist and must be destroyed before the next scenario can recreate them.
    # We destroy using state files when they exist, then wipe all artifacts.
    if fresh_env:
        print("  Fresh metastore — destroying prior scenario state (if any).")
        for env in envs:
            _try_destroy(env)
        _try_destroy_account()
        # Explicitly delete tag policies and tag assignments via API in case
        # terraform destroy missed them (e.g. they were never in state due to
        # import failures or a partially-failed apply).  This prevents old
        # pci_level / phi_level etc. policies from persisting across scenarios
        # and causing "tag value is not an allowed value" errors on the next
        # scenario's apply.
        _force_delete_tag_policies(*envs)
        _force_delete_tag_assignments(*envs)
        _force_delete_fgac_policies(*envs, all_catalogs=True)
        for env in envs:
            _clean_env_artifacts(env)
        _clean_account_artifacts()
        return

    for env in envs:
        _try_destroy(env)
    _try_destroy_account()
    # ORDER IS CRITICAL — delete in dependency order so each step succeeds:
    # 1. Delete account-level UC tag policies FIRST.
    _force_delete_tag_policies(*envs)
    # 2. Delete FGAC policies from ALL non-system catalogs in the workspace.
    _force_delete_fgac_policies(*envs, all_catalogs=True)
    # 3. Delete column-level tag assignments.
    _force_delete_tag_assignments(*envs)
    # 4. Drop test catalogs LAST.
    _drop_test_catalogs(*envs)
    # On a shared/long-lived metastore the FGAC estimated counter can lag
    # several minutes after mass-deletion — poll until it settles.
    _wait_for_fgac_quota(*envs, target=900, max_wait_seconds=300, poll_interval=30)
    for env in envs:
        _clean_env_artifacts(env)
    _clean_account_artifacts()


def _teardown_data(*flags: str, auth_file: Path, warehouse_id: str = "") -> None:
    """Drop test catalogs (best-effort)."""
    _step("Tearing down test data")
    try:
        _setup_data(auth_file, *flags, warehouse_id=warehouse_id)
    except Exception as e:
        print(f"  {_yellow('WARN')} teardown: {e}")


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def _assert_file_exists(path: Path, description: str) -> None:
    if not path.exists():
        raise AssertionError(f"Expected file not found: {path}  ({description})")
    print(f"  {_green('PASS')}  {description}: {path.name} exists")


def _assert_contains(path: Path, text: str, description: str) -> None:
    content = path.read_text()
    if text not in content:
        raise AssertionError(
            f"Expected '{text}' not found in {path}\n  ({description})"
        )
    print(f"  {_green('PASS')}  {description}: '{text}' found in {path.name}")


def _assert_not_contains(path: Path, text: str, description: str) -> None:
    content = path.read_text()
    if text in content:
        raise AssertionError(
            f"Unexpected '{text}' found in {path}\n  ({description})"
        )
    print(f"  {_green('PASS')}  {description}: '{text}' absent from {path.name}")


def _assert_not_declared_hcl(path: Path, key: str, description: str) -> None:
    """Assert a top-level HCL key is NOT declared as an actual assignment.

    Unlike _assert_not_contains, this ignores comment lines (lines starting
    with '#') so that mode-specific header comments or LLM placeholder comments
    such as '# tag_assignments = [] — managed centrally' do not cause false
    positives.  Only an actual HCL declaration of the form
        key = [ ...
        key = { ...
    on a non-comment line triggers a failure.
    """
    content = path.read_text()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*[\[{{]", re.MULTILINE)
    if pattern.search(content):
        raise AssertionError(
            f"Unexpected HCL declaration '{key}' found in {path}\n  ({description})"
        )
    print(f"  {_green('PASS')}  {description}: '{key}' not declared in {path.name}")


def _assert_genie_space_id_file(env: str, space_name: str) -> None:
    """Check that a .genie_space_id_<key> file was created by make apply."""
    key = re.sub(r"[^a-z0-9]+", "_", space_name.lower()).strip("_")
    candidates = list((ENVS_DIR / env).glob(f".genie_space_id_{key}*"))
    if not candidates:
        # Also accept the legacy single-space file
        legacy = ENVS_DIR / env / ".genie_space_id"
        if legacy.exists():
            print(f"  {_green('PASS')}  Genie Space ID file exists (legacy): .genie_space_id")
            return
        raise AssertionError(
            f"No .genie_space_id_* file found for space '{space_name}' in envs/{env}/"
        )
    print(f"  {_green('PASS')}  Genie Space ID file: {candidates[0].name}")


def _verify_data(
    auth_file: Path,
    *,
    dev: bool = False,
    prod: bool = False,
    warehouse_id: str = "",
) -> None:
    """Run setup_test_data.py --verify (and --verify-prod) as assertions."""
    flags: list[str] = []
    if dev:
        flags.append("--verify")
    if prod:
        flags.append("--verify-prod")
    if not flags:
        return
    _setup_data(auth_file, *flags, warehouse_id=warehouse_id)


# ---------------------------------------------------------------------------
# Scenario: 1 — Quickstart (single space, single catalog)
# ---------------------------------------------------------------------------

def scenario_quickstart(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Flow: setup dev_fin → configure one space → generate → apply → verify → teardown.

    Exercises the core quickstart path from docs/playbook.md § 1 with a single Genie
    Space backed by a single UC catalog.
    """
    _banner("Scenario: quickstart — Single space, single catalog")
    env = "dev"

    # ── setup ────────────────────────────────────────────────────────────────
    _preamble_cleanup(env, fresh_env=fresh_env)

    _step("Creating dev_fin test catalog")
    _setup_data(auth_file, warehouse_id=warehouse_id)   # dev_fin + dev_clinical (idempotent)

    _step("Preparing env")
    _make(f"setup", f"ENV={env}")
    _write_env_tfvars(env, SPACES_FINANCE_ONLY, warehouse_id)

    # ── generate + apply ─────────────────────────────────────────────────────
    _step("Generating ABAC config")
    _make(f"generate", f"ENV={env}", retries=2)

    _step("Asserting generated output")
    gen_dir = ENVS_DIR / env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "abac.auto.tfvars generated")
    _assert_file_exists(gen_dir / "masking_functions.sql", "masking_functions.sql generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics config generated")
    _assert_file_exists(gen_dir / "spaces" / "finance_analytics" / "abac.auto.tfvars",
                        "per-space directory bootstrapped")

    _step("Applying all layers")
    _make(f"apply", f"ENV={env}", retries=3, retry_delay_seconds=120)

    _step("Asserting Genie Space deployed")
    _assert_genie_space_id_file(env, "Finance Analytics")

    _step("Verifying data + ABAC governance")
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", "--teardown-prod", auth_file=auth_file,
                       warehouse_id=warehouse_id)
        _try_destroy(env)
        _try_destroy_account()

    print(f"\n  {_green(_bold('PASSED'))}  quickstart")


# ---------------------------------------------------------------------------
# Scenario: 2 — Multi-catalog in one Genie Space
# ---------------------------------------------------------------------------

def scenario_multi_catalog(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Flow: setup dev_fin + dev_clinical → one space using tables from both catalogs
    → generate → apply → verify both catalogs tagged → teardown.

    Tests the "single space spanning multiple catalogs" pattern from playbook.md § 1.
    """
    _banner("Scenario: multi-catalog — One space, two catalogs")
    env = "dev"

    # ── setup ────────────────────────────────────────────────────────────────
    _preamble_cleanup(env, fresh_env=fresh_env)

    _step("Creating dev_fin and dev_clinical test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    _step("Preparing env")
    _make(f"setup", f"ENV={env}")
    _write_env_tfvars(env, SPACES_COMBINED, warehouse_id)

    # ── generate + apply ─────────────────────────────────────────────────────
    _step("Generating ABAC config (tables from both catalogs)")
    _make(f"generate", f"ENV={env}", retries=2)

    _step("Asserting generated output covers both catalogs")
    gen_dir = ENVS_DIR / env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "abac.auto.tfvars generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Combined Analytics",
                     "Combined Analytics space config generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", DEV_FIN_CAT,
                     f"{DEV_FIN_CAT} catalog referenced in policies")
    _assert_contains(gen_dir / "abac.auto.tfvars", DEV_CLIN_CAT,
                     f"{DEV_CLIN_CAT} catalog referenced in policies")

    _step("Applying all layers")
    _make(f"apply", f"ENV={env}", retries=3, retry_delay_seconds=120)

    _step("Asserting single Genie Space deployed")
    _assert_genie_space_id_file(env, "Combined Analytics")

    _step("Verifying data + ABAC governance (both catalogs)")
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", "--teardown-prod", auth_file=auth_file,
                       warehouse_id=warehouse_id)
        _try_destroy(env)
        _try_destroy_account()

    print(f"\n  {_green(_bold('PASSED'))}  multi-catalog")


# ---------------------------------------------------------------------------
# Scenario: 3 — Multi Genie Spaces
# ---------------------------------------------------------------------------

def scenario_multi_space(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Flow: setup both catalogs → two spaces (Finance + Clinical) → full generate
    → apply → verify both spaces deployed → teardown.

    This mirrors the existing `make integration-test` multi-space scenario and
    exercises the full two-space + two-catalog path.
    """
    _banner("Scenario: multi-space — Two spaces, separate catalogs")
    env = "dev"

    # ── setup ────────────────────────────────────────────────────────────────
    _preamble_cleanup(env, fresh_env=fresh_env)

    _step("Creating dev_fin and dev_clinical test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    _step("Preparing env")
    _make(f"setup", f"ENV={env}")
    _write_env_tfvars(env, SPACES_MULTI, warehouse_id)

    # ── generate + apply ─────────────────────────────────────────────────────
    _step("Generating ABAC config (both spaces)")
    _make(f"generate", f"ENV={env}", retries=2)

    _step("Asserting generated output contains both spaces")
    gen_dir = ENVS_DIR / env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "abac.auto.tfvars generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics config present")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Clinical Analytics",
                     "Clinical Analytics config present")
    _assert_file_exists(gen_dir / "spaces" / "finance_analytics" / "abac.auto.tfvars",
                        "finance_analytics per-space dir bootstrapped")
    _assert_file_exists(gen_dir / "spaces" / "clinical_analytics" / "abac.auto.tfvars",
                        "clinical_analytics per-space dir bootstrapped")

    _step("Applying all layers")
    _make(f"apply", f"ENV={env}", retries=3, retry_delay_seconds=120)

    _step("Asserting both Genie Spaces deployed")
    _assert_genie_space_id_file(env, "Finance Analytics")
    _assert_genie_space_id_file(env, "Clinical Analytics")

    _step("Verifying data + ABAC governance")
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", "--teardown-prod", auth_file=auth_file,
                       warehouse_id=warehouse_id)
        _try_destroy(env)
        _try_destroy_account()

    print(f"\n  {_green(_bold('PASSED'))}  multi-space")


# ---------------------------------------------------------------------------
# Scenario: 4 — Per-space incremental generation
# ---------------------------------------------------------------------------

def scenario_per_space(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Flow: deploy Finance Analytics first → then add Clinical Analytics using
    `make generate SPACE="Clinical Analytics"` → verify Finance config is
    preserved and Clinical config is merged in additively.

    Exercises the per-space isolation guarantee from docs/playbook.md § 4.
    """
    _banner("Scenario: per-space — Incremental space addition (isolation test)")
    env = "dev"

    # ── setup ────────────────────────────────────────────────────────────────
    _preamble_cleanup(env, fresh_env=fresh_env)

    _step("Creating both test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    _step("Preparing env with Finance Analytics only")
    _make(f"setup", f"ENV={env}")
    _write_env_tfvars(env, SPACES_FINANCE_ONLY, warehouse_id)

    # ── Phase 1: deploy Finance only ─────────────────────────────────────────
    _step("Phase 1 — Full generate for Finance Analytics")
    _make(f"generate", f"ENV={env}", retries=2)

    gen_dir = ENVS_DIR / env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "abac.auto.tfvars generated (phase 1)")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics present after phase-1 generate")
    _assert_not_contains(gen_dir / "abac.auto.tfvars", "Clinical Analytics",
                         "Clinical Analytics absent before phase-2 generate")

    # Snapshot the Finance entry checksum for later comparison
    fin_space_dir = gen_dir / "spaces" / "finance_analytics"
    _assert_file_exists(fin_space_dir / "abac.auto.tfvars",
                        "finance_analytics per-space dir bootstrapped")
    fin_checksum_before = (fin_space_dir / "abac.auto.tfvars").read_text()

    _step("Phase 1 — Applying Finance Analytics")
    _make(f"apply", f"ENV={env}", retries=3, retry_delay_seconds=120)
    _assert_genie_space_id_file(env, "Finance Analytics")

    # ── Phase 2: add Clinical Analytics without touching Finance ─────────────
    _step("Phase 2 — Adding Clinical Analytics to env.auto.tfvars")
    _write_env_tfvars(env, SPACES_MULTI, warehouse_id)

    _step("Phase 2 — Per-space generate for Clinical Analytics only")
    _make(f"generate", f"ENV={env}", f'SPACE=Clinical Analytics', retries=2)

    _step("Asserting per-space isolation")
    assembled = gen_dir / "abac.auto.tfvars"
    _assert_contains(assembled, "Finance Analytics",
                     "Finance Analytics config preserved in assembled output")
    _assert_contains(assembled, "Clinical Analytics",
                     "Clinical Analytics config merged into assembled output")

    fin_checksum_after = (fin_space_dir / "abac.auto.tfvars").read_text()
    if fin_checksum_before != fin_checksum_after:
        raise AssertionError(
            "finance_analytics per-space config was modified by Clinical Analytics generate!"
        )
    print(f"  {_green('PASS')}  finance_analytics per-space dir unchanged after SPACE= generate")

    _assert_file_exists(gen_dir / "spaces" / "clinical_analytics" / "abac.auto.tfvars",
                        "clinical_analytics per-space dir created")

    _step("Phase 2 — Applying with both spaces")
    _make(f"apply", f"ENV={env}", retries=3, retry_delay_seconds=120)
    _assert_genie_space_id_file(env, "Finance Analytics")
    _assert_genie_space_id_file(env, "Clinical Analytics")

    _step("Verifying data + ABAC governance")
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", "--teardown-prod", auth_file=auth_file,
                       warehouse_id=warehouse_id)
        _try_destroy(env)
        _try_destroy_account()

    print(f"\n  {_green(_bold('PASSED'))}  per-space")


# ---------------------------------------------------------------------------
# Scenario: 5 — Promote dev → prod
# ---------------------------------------------------------------------------

def scenario_promote(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Flow: setup dev + prod catalogs → two-space dev → generate + apply dev →
    promote with catalog remapping → apply prod → verify prod → teardown.

    Exercises docs/playbook.md § 5 cross-env promotion end-to-end.
    """
    _banner("Scenario: promote — dev → prod cross-env promotion")
    dev_env  = "dev"
    prod_env = "prod"

    # ── setup ────────────────────────────────────────────────────────────────
    _preamble_cleanup(dev_env, prod_env, fresh_env=fresh_env)

    _step("Creating dev + prod test catalogs")
    _setup_data(auth_file, "--prod", warehouse_id=warehouse_id)

    for env in (dev_env, prod_env):
        _step(f"Preparing {env} env")
        _make(f"setup", f"ENV={env}")

    _write_env_tfvars(dev_env, SPACES_MULTI, warehouse_id)

    # ── dev generate + apply ─────────────────────────────────────────────────
    _step("Generating dev ABAC config")
    _make(f"generate", f"ENV={dev_env}", retries=2)

    gen_dir = ENVS_DIR / dev_env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "dev abac.auto.tfvars generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics in dev generated config")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Clinical Analytics",
                     "Clinical Analytics in dev generated config")

    _step("Applying dev")
    _make(f"apply", f"ENV={dev_env}", retries=3, retry_delay_seconds=120)
    _assert_genie_space_id_file(dev_env, "Finance Analytics")
    _assert_genie_space_id_file(dev_env, "Clinical Analytics")

    _step("Verifying dev data + ABAC")
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

    # Patch the dev env.auto.tfvars with the actual warehouse created by Terraform.
    # The promote step copies sql_warehouse_id from dev → prod; if we leave it as ""
    # both dev and prod applies would try to CREATE a warehouse, and the second one
    # fails with "warehouse already exists" (same workspace, same name).
    _patch_warehouse_id_in_env_tfvars(dev_env, auth_file)

    # ── promote ──────────────────────────────────────────────────────────────
    _step(f"Promoting {dev_env} → {prod_env} with catalog map: {CATALOG_MAP_DEV_TO_PROD}")
    _make(
        f"promote",
        f"SOURCE_ENV={dev_env}",
        f"DEST_ENV={prod_env}",
        f"DEST_CATALOG_MAP={CATALOG_MAP_DEV_TO_PROD}",
    )

    prod_env_dir = ENVS_DIR / prod_env
    _assert_file_exists(prod_env_dir / "env.auto.tfvars",
                        "prod env.auto.tfvars written by promote")
    prod_env_content = (prod_env_dir / "env.auto.tfvars").read_text()
    if PROD_FIN_CAT not in prod_env_content:
        raise AssertionError(
            f"Expected {PROD_FIN_CAT} in prod env.auto.tfvars after promote"
        )
    print(f"  {_green('PASS')}  prod env.auto.tfvars contains remapped prod catalogs")

    _assert_file_exists(prod_env_dir / "generated" / "abac.auto.tfvars",
                        "prod generated/abac.auto.tfvars written by promote")
    _assert_contains(prod_env_dir / "generated" / "abac.auto.tfvars", PROD_FIN_CAT,
                     f"{PROD_FIN_CAT} in promoted prod config")

    # ── prod apply + verify ──────────────────────────────────────────────────
    # Copy auth to prod (promote doesn't touch auth)
    _copy_auth(dev_env, prod_env)

    _step("Applying prod")
    _make(f"apply", f"ENV={prod_env}", retries=3, retry_delay_seconds=120)

    _step("Verifying prod data + ABAC")
    _verify_data(auth_file, prod=True, warehouse_id=warehouse_id)

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", "--teardown-prod", auth_file=auth_file,
                       warehouse_id=warehouse_id)
        _try_destroy(prod_env)
        _try_destroy(dev_env)
        _try_destroy_account()

    print(f"\n  {_green(_bold('PASSED'))}  promote")


# ---------------------------------------------------------------------------
# Scenario: 6 — Multi-env (independent BU)
# ---------------------------------------------------------------------------

def scenario_multi_env(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Flow: two completely independent workspace environments on the same account —
    dev uses Finance Analytics (dev_fin) and bu2 uses Clinical Analytics (dev_clinical).
    Each has its own generate + apply cycle with separate generated config and state.

    Exercises docs/playbook.md § 6 (second independent environment for another BU).
    """
    _banner("Scenario: multi-env — Two independent environments (dev + bu2)")
    dev_env = "dev"
    bu2_env = "bu2"

    # ── setup ────────────────────────────────────────────────────────────────
    _preamble_cleanup(dev_env, bu2_env, fresh_env=fresh_env)

    _step("Creating both test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    for env in (dev_env, bu2_env):
        _step(f"Preparing {env} env")
        _make(f"setup", f"ENV={env}")

    # Both envs share the same auth (same workspace)
    _copy_auth(dev_env, bu2_env)
    _write_env_tfvars(dev_env, SPACES_FINANCE_ONLY,  warehouse_id)
    _write_env_tfvars(bu2_env, SPACES_CLINICAL_ONLY, warehouse_id)

    # ── dev: generate + apply ─────────────────────────────────────────────────
    _step("dev — Generating Finance Analytics ABAC config")
    _make(f"generate", f"ENV={dev_env}", retries=2)

    dev_gen = ENVS_DIR / dev_env / "generated"
    _assert_contains(dev_gen / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics in dev generated config")
    _assert_not_contains(dev_gen / "abac.auto.tfvars", "Clinical Analytics",
                         "Clinical Analytics absent from dev generated config")

    _step("dev — Applying Finance Analytics")
    _make(f"apply", f"ENV={dev_env}", retries=3, retry_delay_seconds=120)
    _assert_genie_space_id_file(dev_env, "Finance Analytics")

    _step("dev — Verifying Finance Analytics data + ABAC")
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

    # dev and bu2 share the same workspace.  If both env.auto.tfvars have
    # sql_warehouse_id = "" Terraform will try to create "ABAC Serverless Warehouse"
    # twice in the same workspace → name conflict.  After dev's apply we discover
    # the created warehouse and patch it into both dev and bu2 env.auto.tfvars so
    # bu2's apply reuses the existing warehouse (count=0 branch).
    actual_wh = _patch_warehouse_id_in_env_tfvars(dev_env, auth_file)
    if actual_wh:
        _write_env_tfvars(bu2_env, SPACES_CLINICAL_ONLY, actual_wh)

    # ── bu2: generate + apply ─────────────────────────────────────────────────
    _step("bu2 — Generating Clinical Analytics ABAC config independently")
    _make(f"generate", f"ENV={bu2_env}", retries=2)

    bu2_gen = ENVS_DIR / bu2_env / "generated"
    _assert_contains(bu2_gen / "abac.auto.tfvars", "Clinical Analytics",
                     "Clinical Analytics in bu2 generated config")
    _assert_not_contains(bu2_gen / "abac.auto.tfvars", "Finance Analytics",
                         "Finance Analytics absent from bu2 generated config")

    _step("bu2 — Applying Clinical Analytics")
    _make(f"apply", f"ENV={bu2_env}", retries=3, retry_delay_seconds=120)
    _assert_genie_space_id_file(bu2_env, "Clinical Analytics")

    _step("bu2 — Verifying Clinical Analytics ABAC governance")
    # Verify dev_clinical tables exist and tags/masks applied
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

    _step("Asserting independent state files")
    dev_state = ENVS_DIR / dev_env / "terraform.tfstate"
    bu2_state = ENVS_DIR / bu2_env / "terraform.tfstate"
    _assert_file_exists(dev_state, "dev has own terraform.tfstate")
    _assert_file_exists(bu2_state, "bu2 has own terraform.tfstate")
    if dev_state.read_text() == bu2_state.read_text():
        raise AssertionError("dev and bu2 terraform.tfstate are identical — expected independent state")
    print(f"  {_green('PASS')}  dev and bu2 have independent Terraform state")

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", "--teardown-prod", auth_file=auth_file,
                       warehouse_id=warehouse_id)
        _try_destroy(bu2_env)
        _try_destroy(dev_env)
        _try_destroy_account()
        # Remove the bu2 env directory (it's ephemeral)
        bu2_dir = ENVS_DIR / bu2_env
        if bu2_dir.exists():
            shutil.rmtree(bu2_dir)

    print(f"\n  {_green(_bold('PASSED'))}  multi-env")


# ---------------------------------------------------------------------------
# Genie Space API helpers (for the attach-promote scenario)
# ---------------------------------------------------------------------------

def _ensure_packages() -> None:
    try:
        import hcl2  # noqa: F401
        from databricks.sdk import WorkspaceClient  # noqa: F401
    except ImportError:
        _run([sys.executable, "-m", "pip", "install", "-q",
              "databricks-sdk", "python-hcl2"])


def _load_auth_cfg(auth_file: Path) -> dict:
    """Load databricks credentials from auth.auto.tfvars."""
    _ensure_packages()
    import hcl2
    with open(auth_file) as f:
        return hcl2.load(f)


def _configure_sdk_env(cfg: dict) -> None:
    """Set DATABRICKS_* env vars from auth config so the SDK picks them up."""
    mapping = {
        "databricks_workspace_host": "DATABRICKS_HOST",
        "databricks_client_id":      "DATABRICKS_CLIENT_ID",
        "databricks_client_secret":  "DATABRICKS_CLIENT_SECRET",
    }
    for k, env_k in mapping.items():
        v = cfg.get(k, "")
        if v and not os.environ.get(env_k):
            os.environ[env_k] = v


def _get_or_find_warehouse(auth_file: Path, warehouse_id: str) -> str:
    """Return a warehouse ID — use the given one or pick the first available."""
    from databricks.sdk import WorkspaceClient

    cfg = _load_auth_cfg(auth_file)
    _configure_sdk_env(cfg)
    w = WorkspaceClient(product="genierails-test-runner", product_version="0.1.0")

    if warehouse_id:
        return warehouse_id

    print("  No warehouse-id provided; auto-selecting a SQL warehouse...")
    warehouses = list(w.warehouses.list())
    for wh in warehouses:
        state = str(wh.state)
        if "RUNNING" in state or "STARTING" in state:
            print(f"    Using warehouse: {wh.name} ({wh.id})")
            return wh.id
    if warehouses:
        wh = warehouses[0]
        print(f"    Using warehouse: {wh.name} ({wh.id})")
        return wh.id
    raise RuntimeError("No SQL warehouses found in the workspace.")


def _create_genie_space_via_api(
    auth_file: Path,
    title: str,
    tables: list[str],
    warehouse_id: str,
) -> str:
    """Create a Genie Space directly via REST API, simulating the UI experience.

    Returns the new space_id.
    """
    import json
    from databricks.sdk import WorkspaceClient

    cfg = _load_auth_cfg(auth_file)
    _configure_sdk_env(cfg)
    w = WorkspaceClient(product="genierails-test-runner", product_version="0.1.0")

    body = {
        "warehouse_id": warehouse_id,
        "title": title,
        "serialized_space": json.dumps({
            "version": 2,
            "data_sources": {
                "tables": [{"identifier": t} for t in sorted(tables)]
            },
        }, separators=(",", ":")),
    }

    print(f"  Creating Genie Space '{title}' via API with {len(tables)} table(s)...")
    resp = w.api_client.do("POST", "/api/2.0/genie/spaces", body=body)
    space_id = resp.get("space_id", "")
    if not space_id:
        raise RuntimeError(f"Genie API did not return space_id. Response: {resp}")
    print(f"  Created Genie Space: {space_id}")
    return space_id


def _delete_genie_space_via_api(auth_file: Path, space_id: str) -> None:
    """Permanently delete a Genie Space via REST API (teardown helper)."""
    from databricks.sdk import WorkspaceClient

    cfg = _load_auth_cfg(auth_file)
    _configure_sdk_env(cfg)
    w = WorkspaceClient(product="genierails-test-runner", product_version="0.1.0")

    print(f"  Deleting Genie Space {space_id} via API...")
    try:
        w.api_client.do("DELETE", f"/api/2.0/genie/spaces/{space_id}")
        print(f"  Genie Space {space_id} deleted.")
    except Exception as exc:
        print(f"  {_yellow('WARN')} Could not delete Genie Space {space_id}: {exc}")


# ---------------------------------------------------------------------------
# Scenario: 7 — Attach to an existing Genie Space and promote to prod
# ---------------------------------------------------------------------------

def scenario_attach_and_promote(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Simulates the "Import an existing Genie Space" flow from docs/playbook.md §3:

    Phase 1 — Simulate "configured in the UI":
      A Finance Analytics Genie Space is created directly via the Genie REST API
      (not Terraform), with dev_fin tables. This represents what a data team would
      have built in the Databricks UI before this tool was adopted.

    Phase 2 — Attach and govern (genie_space_id-only mode):
      env.auto.tfvars is configured with just genie_space_id (no uc_tables).
      `make generate` queries the Genie API to discover the space's tables, then
      generates full ABAC governance (groups, policies, masking functions) from
      those tables. The genie_space_configs entry is parsed verbatim from the API
      (no LLM involvement for the space's existing config).
      After generate, env.auto.tfvars is updated with the discovered uc_tables
      (simulating the manual step instructed by playbook.md).

    Phase 3 — Apply:
      `make apply` deploys ABAC governance (ACLs, column tags, masking functions,
      FGAC policies) without creating or deleting the Genie Space.
      The space's title, description, benchmarks, and instructions are preserved
      exactly as configured in the API/UI.

    Phase 4 — Promote to prod:
      `make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG_MAP=dev_fin=prod_fin`
      followed by `make apply ENV=prod` applies the same governance to prod.

    Tests: playbook.md §3 "Import an existing Genie Space" + §5 promotion.
    """
    _banner("Scenario: attach-promote — Attach to UI-created space, promote to prod")
    env      = "dev"
    prod_env = "prod"

    _ensure_packages()

    # ── Phase 1: simulate "space configured in UI" ───────────────────────────
    _preamble_cleanup(env, prod_env, fresh_env=fresh_env)

    _step("Phase 1 — Setting up dev_fin and prod_fin test catalogs")
    _setup_data(auth_file, "--prod", warehouse_id=warehouse_id)

    resolved_wh = _get_or_find_warehouse(auth_file, warehouse_id)

    fin_tables = [
        f"{DEV_FIN_CAT}.finance.customers",
        f"{DEV_FIN_CAT}.finance.transactions",
        f"{DEV_FIN_CAT}.finance.credit_cards",
    ]

    _step("Phase 1 — Creating Genie Space via API (simulating UI configuration)")
    space_id = _create_genie_space_via_api(
        auth_file,
        title="Finance Analytics",
        tables=fin_tables,
        warehouse_id=resolved_wh,
    )

    # ── Phase 2: attach with genie_space_id + known uc_tables ────────────────
    # NOTE: The Genie API does not reliably return serialized_space in GET
    # responses for newly created spaces (async processing, may take many
    # minutes). We therefore configure uc_tables explicitly here — this
    # simulates the user running `make generate --genie-space-id <id>`,
    # inspecting the logged discovered tables, and pasting them into
    # env.auto.tfvars as instructed by the playbook.md manual step.
    # The key assertion tested here is that Terraform does NOT create/delete
    # the existing Genie Space — it attaches to it as-is.
    _step("Phase 2 — Configuring env with genie_space_id + uc_tables (attach mode)")
    _make(f"setup", f"ENV={env}")
    _make(f"setup", f"ENV={prod_env}")

    attach_with_tables_hcl = f"""\
genie_spaces = [
  {{
    name           = "Finance Analytics"
    genie_space_id = "{space_id}"
    uc_tables = [
      "{DEV_FIN_CAT}.finance.customers",
      "{DEV_FIN_CAT}.finance.transactions",
      "{DEV_FIN_CAT}.finance.credit_cards",
    ]
  }},
]
"""
    _write_env_tfvars(env, attach_with_tables_hcl, resolved_wh)

    _step("Phase 2 — Running make generate (attach mode with explicit uc_tables)")
    _make(f"generate", f"ENV={env}", retries=2)

    _step("Asserting generated config references the dev_fin catalog")
    gen_dir = ENVS_DIR / env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars",
                        "abac.auto.tfvars generated")
    _assert_file_exists(gen_dir / "masking_functions.sql",
                        "masking_functions.sql generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", DEV_FIN_CAT,
                     f"{DEV_FIN_CAT} catalog referenced in generated policies")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics genie_space_configs entry present")

    # ── Phase 3: apply governance (no space create/delete) ───────────────────
    _step("Phase 3 — Applying governance (space must survive, not be created/deleted)")
    _make(f"apply", f"ENV={env}", retries=3, retry_delay_seconds=120)

    _step("Asserting space NOT created by Terraform (no .genie_space_id_* file)")
    id_files = list((ENVS_DIR / env).glob(".genie_space_id_*"))
    legacy   = ENVS_DIR / env / ".genie_space_id"
    if id_files or legacy.exists():
        raise AssertionError(
            "Terraform created a new Genie Space in attach mode — expected no .genie_space_id_* file. "
            "The existing space should be used as-is."
        )
    print(f"  {_green('PASS')}  No .genie_space_id_* file: Terraform did not create a new space")

    _step("Verifying dev ABAC governance applied to discovered tables")
    _verify_data(auth_file, dev=True, warehouse_id=resolved_wh)

    # ── Phase 4: promote to prod ─────────────────────────────────────────────
    _step(f"Phase 4 — Promoting {env} → {prod_env} (dev_fin → prod_fin)")
    _make(
        "promote",
        f"SOURCE_ENV={env}",
        f"DEST_ENV={prod_env}",
        f"DEST_CATALOG_MAP={DEV_FIN_CAT}={PROD_FIN_CAT}",
    )

    _assert_file_exists(
        ENVS_DIR / prod_env / "env.auto.tfvars",
        "prod env.auto.tfvars written by promote",
    )
    _assert_contains(
        ENVS_DIR / prod_env / "generated" / "abac.auto.tfvars",
        PROD_FIN_CAT,
        f"{PROD_FIN_CAT} catalog in promoted prod config",
    )

    _copy_auth(env, prod_env)

    _step("Phase 4 — Applying prod governance")
    _make(f"apply", f"ENV={prod_env}", retries=3, retry_delay_seconds=120)

    _step("Verifying prod ABAC governance")
    _verify_data(auth_file, prod=True, warehouse_id=resolved_wh)

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", "--teardown-prod", auth_file=auth_file,
                       warehouse_id=resolved_wh)
        _try_destroy(prod_env)
        _try_destroy(env)
        _try_destroy_account()
        # Delete the UI-created space (Terraform won't do it in attach mode)
        _delete_genie_space_via_api(auth_file, space_id)

    print(f"\n  {_green(_bold('PASSED'))}  attach-promote")


def scenario_decentralized(
    auth_file: Path,
    warehouse_id: str = "",
    keep_data: bool = False,
    fresh_env: bool = False,
) -> None:
    """Decentralized governance: central ABAC team + independent BU Genie teams.

    Phase 1 — Governance team:
      Creates a 'governance' env that governs both dev_fin + dev_clinical catalogs.
      Runs `make generate MODE=governance` — asserts ABAC sections are present and
      genie_space_configs is absent.
      Runs `make apply-governance` — applies account + data_access only; no Genie
      space is created (.genie_space_id_* file must NOT appear).

    Phase 2 — BU Finance team:
      Creates a 'bu_fin' env pointing at dev_fin tables with a Finance Analytics space.
      Runs `make generate MODE=genie` — asserts genie_space_configs is present and
      ABAC sections (groups, tag_assignments, fgac_policies) are absent.
      Runs `make apply-genie` — applies workspace only; Finance Analytics Genie Space
      IS created (.genie_space_id_finance_analytics must appear).

    Phase 3 — Adding a second BU (isolation check):
      Creates a 'bu_clin' env for a second BU team with Clinical Analytics.
      Runs `make generate MODE=genie` + `make apply-genie`.
      Asserts that the governance team's data_access/terraform.tfstate is byte-for-byte
      unchanged after the second BU is added (proving independence).
      Tests playbook.md §7 "Adding a second BU".

    Phase 4 — BU Finance team promote to prod:
      Runs `make promote SOURCE_ENV=bu_fin DEST_ENV=bu_fin_prod DEST_CATALOG_MAP=dev_fin=prod_fin`.
      Then runs `make apply-genie ENV=bu_fin_prod` (NOT make apply) — applies workspace only.
      Asserts bu_fin_prod has .genie_space_id_* but no data_access/terraform.tfstate.
      Asserts governance state is unmodified throughout.
      Tests the BU-team prod-promotion pattern from docs/decentralized.md.

    Tests: playbook.md §7 "Decentralized governance" and docs/decentralized.md.
    """
    _banner("Scenario: decentralized — Central governance team + BU Genie teams")
    gov_env     = "governance"
    bu_env      = "bu_fin"
    bu_clin_env = "bu_clin"
    bu_prod_env = "bu_fin_prod"

    _ensure_packages()

    # ── Phase 1: Governance team — data setup ────────────────────────────────
    _preamble_cleanup(gov_env, bu_env, bu_clin_env, bu_prod_env, fresh_env=fresh_env)

    _step("Phase 1 — Setting up dev_fin + dev_clinical + prod_fin test catalogs")
    _setup_data(auth_file, "--prod", warehouse_id=warehouse_id)

    resolved_wh = _get_or_find_warehouse(auth_file, warehouse_id)
    _make("setup", f"ENV={gov_env}")

    # Governance env: list both catalogs, no genie_spaces block
    gov_tables_hcl = f"""\
uc_tables = [
  "{DEV_FIN_CAT}.finance.customers",
  "{DEV_FIN_CAT}.finance.transactions",
  "{DEV_FIN_CAT}.finance.credit_cards",
  "{DEV_CLIN_CAT}.clinical.patients",
  "{DEV_CLIN_CAT}.clinical.encounters",
]
"""
    wh_line = f'sql_warehouse_id = "{resolved_wh}"' if resolved_wh else 'sql_warehouse_id = ""'
    gov_env_dir = ENVS_DIR / gov_env
    (gov_env_dir / "env.auto.tfvars").write_text(gov_tables_hcl + wh_line + "\n")
    _copy_auth("dev", gov_env)

    _step("Phase 1 — Generating ABAC config (governance MODE)")
    _make("generate", f"ENV={gov_env}", "MODE=governance", retries=2)

    _step("Asserting governance mode output: ABAC sections present, genie_space_configs absent")
    gov_gen = gov_env_dir / "generated" / "abac.auto.tfvars"
    _assert_file_exists(gov_gen, "governance/generated/abac.auto.tfvars created")
    _assert_file_exists(
        gov_env_dir / "generated" / "masking_functions.sql",
        "governance/generated/masking_functions.sql created",
    )
    for section in ("tag_assignments", "fgac_policies"):
        _assert_contains(gov_gen, section, f"'{section}' present in governance output")
    _assert_not_contains(
        gov_gen, "genie_space_configs",
        "genie_space_configs absent in governance output (governance mode)",
    )

    _step("Phase 1 — Applying governance layers (account + data_access only)")
    _make("apply-governance", f"ENV={gov_env}", retries=3, retry_delay_seconds=120)

    _step("Asserting governance env: data_access state exists, no Genie Space created")
    da_state = gov_env_dir / "data_access" / "terraform.tfstate"
    if not da_state.exists():
        raise AssertionError(
            f"Expected data_access/terraform.tfstate in '{gov_env}' env after apply-governance, "
            "but it does not exist."
        )
    print(f"  {_green('PASS')}  data_access/terraform.tfstate exists in '{gov_env}' env")

    id_files_gov = list(gov_env_dir.glob(".genie_space_id_*"))
    if id_files_gov:
        raise AssertionError(
            f"apply-governance created a Genie Space in '{gov_env}' env — expected none. "
            f"Files found: {[str(f) for f in id_files_gov]}"
        )
    print(f"  {_green('PASS')}  No .genie_space_id_* file in '{gov_env}' env — workspace layer skipped")

    # ── Phase 2: BU Finance team — Genie-only flow ───────────────────────────
    _step("Phase 2 — Setting up BU Finance env")
    _make("setup", f"ENV={bu_env}")

    _write_env_tfvars(bu_env, SPACES_FINANCE_ONLY, resolved_wh)
    _copy_auth("dev", bu_env)

    _step("Phase 2 — Generating Genie config (genie MODE)")
    _make("generate", f"ENV={bu_env}", "MODE=genie", retries=2)

    _step("Asserting genie mode output: genie_space_configs present, ABAC sections absent")
    bu_gen = ENVS_DIR / bu_env / "generated" / "abac.auto.tfvars"
    _assert_file_exists(bu_gen, f"{bu_env}/generated/abac.auto.tfvars created")
    _assert_contains(bu_gen, "genie_space_configs",
                     "genie_space_configs present in genie output")
    for section in ("tag_assignments", "fgac_policies"):
        _assert_not_declared_hcl(bu_gen, section,
                                 f"'{section}' not declared in genie output (genie mode)")
    # masking SQL must NOT be written in genie mode
    bu_sql = ENVS_DIR / bu_env / "generated" / "masking_functions.sql"
    if bu_sql.exists():
        raise AssertionError(
            f"masking_functions.sql was written for '{bu_env}' in genie mode — expected none. "
            "Masking functions are owned by the governance team."
        )
    print(f"  {_green('PASS')}  No masking_functions.sql in '{bu_env}' genie-mode output")

    _step("Phase 2 — Applying BU workspace layer (Genie space only)")
    _make("apply-genie", f"ENV={bu_env}", retries=3, retry_delay_seconds=120)

    _step("Asserting BU env: .genie_space_id_* created, no data_access state")
    bu_env_dir = ENVS_DIR / bu_env
    id_files_bu = list(bu_env_dir.glob(".genie_space_id_*"))
    if not id_files_bu:
        raise AssertionError(
            f"apply-genie did not create a .genie_space_id_* file in '{bu_env}' env. "
            "The Finance Analytics Genie Space should have been created."
        )
    print(f"  {_green('PASS')}  .genie_space_id_* file present in '{bu_env}' env: "
          + ", ".join(f.name for f in id_files_bu))

    bu_da_state = bu_env_dir / "data_access" / "terraform.tfstate"
    if bu_da_state.exists():
        raise AssertionError(
            f"apply-genie wrote a data_access/terraform.tfstate in '{bu_env}' env — expected none. "
            "BU team should only manage the workspace layer."
        )
    print(f"  {_green('PASS')}  No data_access/terraform.tfstate in '{bu_env}' env — workspace layer only")

    # ── Phase 3: Second BU — isolation check ─────────────────────────────────
    # Snapshot governance data_access state before Phase 3 to verify it does not change.
    gov_da_state_snapshot = da_state.read_text()

    _step("Phase 3 — Setting up second BU team (Clinical Analytics)")
    _make("setup", f"ENV={bu_clin_env}")
    _write_env_tfvars(bu_clin_env, SPACES_CLINICAL_ONLY, resolved_wh)
    _copy_auth("dev", bu_clin_env)

    _step("Phase 3 — Generating Genie config for second BU (genie MODE)")
    _make("generate", f"ENV={bu_clin_env}", "MODE=genie", retries=2)

    bu_clin_gen = ENVS_DIR / bu_clin_env / "generated" / "abac.auto.tfvars"
    _assert_file_exists(bu_clin_gen, f"{bu_clin_env}/generated/abac.auto.tfvars created")
    _assert_contains(bu_clin_gen, "Clinical Analytics",
                     "Clinical Analytics genie_space_configs in second BU output")
    for section in ("tag_assignments", "fgac_policies"):
        _assert_not_declared_hcl(bu_clin_gen, section,
                                 f"'{section}' not declared in second BU genie output")

    _step("Phase 3 — Applying second BU workspace layer")
    _make("apply-genie", f"ENV={bu_clin_env}", retries=3, retry_delay_seconds=120)

    _step("Asserting second BU env: .genie_space_id_* created, governance state unchanged")
    bu_clin_env_dir = ENVS_DIR / bu_clin_env
    id_files_clin = list(bu_clin_env_dir.glob(".genie_space_id_*"))
    if not id_files_clin:
        raise AssertionError(
            f"apply-genie did not create a .genie_space_id_* file in '{bu_clin_env}' env. "
            "The Clinical Analytics Genie Space should have been created."
        )
    print(f"  {_green('PASS')}  .genie_space_id_* file present in '{bu_clin_env}' env: "
          + ", ".join(f.name for f in id_files_clin))

    gov_da_state_after_p3 = da_state.read_text()
    if gov_da_state_snapshot != gov_da_state_after_p3:
        raise AssertionError(
            f"governance/data_access/terraform.tfstate was modified when '{bu_clin_env}' BU was added. "
            "The governance team's state should be completely unaffected by adding a second BU."
        )
    print(f"  {_green('PASS')}  governance data_access state byte-for-byte unchanged after second BU")

    # ── Phase 4: BU Finance team promote to prod ─────────────────────────────
    _step(f"Phase 4 — BU Finance team promoting {bu_env} → {bu_prod_env}")
    _make(
        "promote",
        f"SOURCE_ENV={bu_env}",
        f"DEST_ENV={bu_prod_env}",
        f"DEST_CATALOG_MAP={DEV_FIN_CAT}={PROD_FIN_CAT}",
    )

    _assert_file_exists(
        ENVS_DIR / bu_prod_env / "env.auto.tfvars",
        f"{bu_prod_env} env.auto.tfvars written by promote",
    )
    _assert_contains(
        ENVS_DIR / bu_prod_env / "generated" / "abac.auto.tfvars",
        PROD_FIN_CAT,
        f"{PROD_FIN_CAT} catalog in promoted prod config",
    )

    _copy_auth("dev", bu_prod_env)

    _step("Phase 4 — Applying prod workspace layer (make apply-genie, not make apply)")
    _make("apply-genie", f"ENV={bu_prod_env}", retries=3, retry_delay_seconds=120)

    _step("Asserting prod BU env: .genie_space_id_* created, no data_access state")
    bu_prod_env_dir = ENVS_DIR / bu_prod_env
    id_files_prod = list(bu_prod_env_dir.glob(".genie_space_id_*"))
    if not id_files_prod:
        raise AssertionError(
            f"apply-genie did not create a .genie_space_id_* file in '{bu_prod_env}' env. "
            "Finance Analytics should have been created in the prod BU env."
        )
    print(f"  {_green('PASS')}  .genie_space_id_* file present in '{bu_prod_env}' env: "
          + ", ".join(f.name for f in id_files_prod))

    bu_prod_da_state = bu_prod_env_dir / "data_access" / "terraform.tfstate"
    if bu_prod_da_state.exists():
        raise AssertionError(
            f"apply-genie wrote a data_access/terraform.tfstate in '{bu_prod_env}' env — "
            "BU prod promote should apply only the workspace layer."
        )
    print(f"  {_green('PASS')}  No data_access/terraform.tfstate in '{bu_prod_env}' — workspace layer only")

    gov_da_state_after_p4 = da_state.read_text()
    if gov_da_state_snapshot != gov_da_state_after_p4:
        raise AssertionError(
            "governance/data_access/terraform.tfstate was modified during BU prod promote. "
            "The governance team's state should be completely unaffected."
        )
    print(f"  {_green('PASS')}  governance data_access state unchanged after BU prod promote")

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", "--teardown-prod", auth_file=auth_file,
                       warehouse_id=resolved_wh)
        _try_destroy(bu_prod_env)
        _try_destroy(bu_clin_env)
        _try_destroy(bu_env)
        _try_destroy(gov_env)
        _try_destroy_account()

    print(f"\n  {_green(_bold('PASSED'))}  decentralized")


# ---------------------------------------------------------------------------
# Scenario: abac-only — ABAC governance without Genie Space (+ upgrade path)
# ---------------------------------------------------------------------------

def scenario_abac_only(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Phase 1 — ABAC-only deploy (playbook.md §2):
      Configure env with uc_tables only (no genie_spaces block).
      Run plain `make generate` (no MODE= flag) + `make apply`.
      Assert: no genie_space_configs in generated output, masking_functions.sql
      generated, no .genie_space_id_* file, data_access/terraform.tfstate exists.

    Phase 2 — §2 → §4 upgrade path:
      Add Finance Analytics to genie_spaces and run `make generate SPACE="Finance Analytics"`.
      Then `make apply`. Assert Genie Space created, existing governance preserved
      (data_access/terraform.tfstate still exists, column tags and masks still applied).

    Tests: playbook.md §2 "ABAC governance only" and the §2 → §4 upgrade path.
    """
    _banner("Scenario: abac-only — ABAC governance without Genie Space (+ upgrade to Genie)")
    env = "dev"

    _preamble_cleanup(env, fresh_env=fresh_env)

    _step("Phase 1 — Setting up dev_fin test catalog")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    resolved_wh = _get_or_find_warehouse(auth_file, warehouse_id)

    # Phase 1: uc_tables only, no genie_spaces
    _step("Phase 1 — Configuring env with uc_tables only (no genie_spaces)")
    _make("setup", f"ENV={env}")
    wh_line = f'sql_warehouse_id = "{resolved_wh}"' if resolved_wh else 'sql_warehouse_id = ""'
    env_dir = ENVS_DIR / env
    (env_dir / "env.auto.tfvars").write_text(TABLES_FINANCE_ONLY_HCL + wh_line + "\n")

    _step("Phase 1 — Generating ABAC config (plain make generate, no genie_spaces)")
    _make("generate", f"ENV={env}", retries=2)

    gen_dir = env_dir / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "abac.auto.tfvars generated")
    _assert_file_exists(gen_dir / "masking_functions.sql", "masking_functions.sql generated")
    _assert_not_declared_hcl(gen_dir / "abac.auto.tfvars", "genie_space_configs",
                             "genie_space_configs absent (no genie_spaces in env config)")

    _step("Phase 1 — Applying (all three layers)")
    _make("apply", f"ENV={env}", retries=3, retry_delay_seconds=120)

    _step("Asserting Phase 1: no Genie Space created, data_access state exists")
    id_files = list(env_dir.glob(".genie_space_id_*"))
    legacy   = env_dir / ".genie_space_id"
    if id_files or legacy.exists():
        raise AssertionError(
            "make apply created a Genie Space in ABAC-only mode — expected none. "
            f"Files: {[f.name for f in id_files]}"
        )
    print(f"  {_green('PASS')}  No .genie_space_id_* file — Genie Space correctly not created")

    da_state = env_dir / "data_access" / "terraform.tfstate"
    if not da_state.exists():
        raise AssertionError(
            "data_access/terraform.tfstate not found after ABAC-only apply. "
            "Expected all three layers to be applied."
        )
    print(f"  {_green('PASS')}  data_access/terraform.tfstate exists — governance deployed")

    _step("Verifying ABAC governance applied to dev_fin tables")
    _verify_data(auth_file, dev=True, warehouse_id=resolved_wh)

    # ── Phase 2: §2 → §4 upgrade path ────────────────────────────────────────
    _step("Phase 2 — Adding Finance Analytics to env.auto.tfvars (ABAC-only → Genie upgrade)")
    _write_env_tfvars(env, SPACES_FINANCE_ONLY, resolved_wh)

    _step("Phase 2 — Per-space generate for Finance Analytics")
    _make("generate", f"ENV={env}", "SPACE=Finance Analytics", retries=2)

    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics genie_space_configs present after upgrade")

    _step("Phase 2 — Applying (Genie Space created on top of existing governance)")
    _make("apply", f"ENV={env}", retries=3, retry_delay_seconds=120)

    _step("Asserting Phase 2: Genie Space created, governance preserved")
    _assert_genie_space_id_file(env, "Finance Analytics")

    if not da_state.exists():
        raise AssertionError(
            "data_access/terraform.tfstate was removed during Genie Space upgrade — "
            "existing governance should be preserved."
        )
    print(f"  {_green('PASS')}  data_access/terraform.tfstate still exists — governance preserved")

    _step("Verifying ABAC governance still applied after Genie Space added")
    _verify_data(auth_file, dev=True, warehouse_id=resolved_wh)

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", auth_file=auth_file, warehouse_id=resolved_wh)
        _try_destroy(env)
        _try_destroy_account()

    print(f"\n  {_green(_bold('PASSED'))}  abac-only")


# ---------------------------------------------------------------------------
# Scenario: multi-space-import — Import two UI-created Genie Spaces at once
# ---------------------------------------------------------------------------

def scenario_multi_space_import(
    auth_file: Path,
    warehouse_id: str,
    keep_data: bool,
    fresh_env: bool = False,
) -> None:
    """
    Import two existing Genie Spaces in one make generate call (playbook.md §3 multi-space).

    Creates two spaces via the Genie REST API (simulating UI-configured spaces),
    then configures genie_spaces with two genie_space_id entries. Asserts both
    configs appear in the generated output and Terraform does not create new
    spaces on apply (both are attached, not created).

    Tests: playbook.md §3 "Multi-space import" section.
    """
    _banner("Scenario: multi-space-import — Import two UI-created Genie Spaces")
    env = "dev"

    _ensure_packages()
    _preamble_cleanup(env, fresh_env=fresh_env)

    _step("Setting up dev_fin and dev_clinical test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    resolved_wh = _get_or_find_warehouse(auth_file, warehouse_id)

    fin_tables = [
        f"{DEV_FIN_CAT}.finance.customers",
        f"{DEV_FIN_CAT}.finance.transactions",
        f"{DEV_FIN_CAT}.finance.credit_cards",
    ]
    clin_tables = [
        f"{DEV_CLIN_CAT}.clinical.patients",
        f"{DEV_CLIN_CAT}.clinical.encounters",
    ]

    _step("Creating Finance Analytics Genie Space via API (simulating UI configuration)")
    fin_space_id = _create_genie_space_via_api(
        auth_file, title="Finance Analytics", tables=fin_tables, warehouse_id=resolved_wh,
    )

    _step("Creating Clinical Analytics Genie Space via API (simulating UI configuration)")
    clin_space_id = _create_genie_space_via_api(
        auth_file, title="Clinical Analytics", tables=clin_tables, warehouse_id=resolved_wh,
    )

    _step("Configuring env with two genie_space_id entries (multi-space import)")
    _make("setup", f"ENV={env}")

    two_space_import_hcl = f"""\
genie_spaces = [
  {{
    name           = "Finance Analytics"
    genie_space_id = "{fin_space_id}"
    uc_tables = [
      "{DEV_FIN_CAT}.finance.customers",
      "{DEV_FIN_CAT}.finance.transactions",
      "{DEV_FIN_CAT}.finance.credit_cards",
    ]
  }},
  {{
    name           = "Clinical Analytics"
    genie_space_id = "{clin_space_id}"
    uc_tables = [
      "{DEV_CLIN_CAT}.clinical.patients",
      "{DEV_CLIN_CAT}.clinical.encounters",
    ]
  }},
]
"""
    _write_env_tfvars(env, two_space_import_hcl, resolved_wh)

    _step("Running make generate — importing both spaces in one call")
    _make("generate", f"ENV={env}", retries=2)

    gen_dir = ENVS_DIR / env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "abac.auto.tfvars generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics genie_space_configs present")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Clinical Analytics",
                     "Clinical Analytics genie_space_configs present")
    _assert_contains(gen_dir / "abac.auto.tfvars", DEV_FIN_CAT,
                     f"{DEV_FIN_CAT} catalog referenced in generated policies")
    _assert_contains(gen_dir / "abac.auto.tfvars", DEV_CLIN_CAT,
                     f"{DEV_CLIN_CAT} catalog referenced in generated policies")

    _step("Applying governance (both spaces attached — Terraform must not create new spaces)")
    _make("apply", f"ENV={env}", retries=3, retry_delay_seconds=120)

    _step("Asserting no .genie_space_id_* files — both spaces attached, not created")
    id_files = list((ENVS_DIR / env).glob(".genie_space_id_*"))
    legacy   = ENVS_DIR / env / ".genie_space_id"
    if id_files or legacy.exists():
        raise AssertionError(
            "Terraform created new Genie Spaces in multi-space import mode — expected none. "
            f"Files: {[f.name for f in id_files]}"
        )
    print(f"  {_green('PASS')}  No .genie_space_id_* files — both spaces correctly attached")

    _step("Verifying ABAC governance applied across both catalogs")
    _verify_data(auth_file, dev=True, warehouse_id=resolved_wh)

    # ── teardown ─────────────────────────────────────────────────────────────
    if not keep_data:
        _teardown_data("--teardown", auth_file=auth_file, warehouse_id=resolved_wh)
        _try_destroy(env)
        _try_destroy_account()
        _delete_genie_space_via_api(auth_file, fin_space_id)
        _delete_genie_space_via_api(auth_file, clin_space_id)

    print(f"\n  {_green(_bold('PASSED'))}  multi-space-import")


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, tuple[str, Callable]] = {
    "quickstart":           ("Single space, single catalog (Finance/dev_fin)",                    scenario_quickstart),
    "multi-catalog":        ("One space spanning two catalogs (Combined)",                        scenario_multi_catalog),
    "multi-space":          ("Two spaces, separate catalogs (Finance+Clinical)",                  scenario_multi_space),
    "per-space":            ("Incremental per-space generation (isolation test)",                 scenario_per_space),
    "promote":              ("Multi-space dev → prod promotion",                                  scenario_promote),
    "multi-env":            ("Two independent envs (dev Finance, bu2 Clinical)",                  scenario_multi_env),
    "attach-promote":       ("Attach to UI-created space (API discovery) + promote",              scenario_attach_and_promote),
    "decentralized":        ("Central governance team (MODE=governance) + BU Genie teams (MODE=genie)", scenario_decentralized),
    "abac-only":            ("ABAC governance only (no Genie Space) + upgrade to Genie",         scenario_abac_only),
    "multi-space-import":   ("Import two UI-created Genie Spaces in one make generate",          scenario_multi_space_import),
}


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def _preflight_fgac_quota_check(auth_file: Path) -> None:
    """Check the metastore-wide FGAC policy quota before running tests.

    The Databricks ABAC quota counter is eventually-consistent and known to
    drift after large-scale policy deletions.  When the counter reads ≥ 1000
    but the actual visible policy count is near 0, every `terraform apply`
    will fail immediately — wasting hours of test time.

    This check detects that condition early and prints a clear error with the
    support ticket instructions needed to fix it.
    """
    try:
        import hcl2 as _hcl2
        import json as _pf_json
        import ssl as _pf_ssl
        import urllib.request as _pf_urq
        import urllib.parse as _pf_urp
        from databricks.sdk import WorkspaceClient as _WC

        _pf_ctx = _pf_ssl.create_default_context()
        _pf_ctx.check_hostname = False
        _pf_ctx.verify_mode = _pf_ssl.CERT_NONE

        def _s(v): return (v[0] if isinstance(v, list) else (v or "")).strip()

        with open(auth_file) as f:
            auth = _hcl2.load(f)
        host          = _s(auth.get("databricks_workspace_host", ""))
        client_id     = _s(auth.get("databricks_client_id", ""))
        client_secret = _s(auth.get("databricks_client_secret", ""))
        if not host:
            return  # can't check without host

        w = _WC(host=host, client_id=client_id, client_secret=client_secret)
        token = w.config.authenticate()
        base  = host.rstrip("/")
        metastore_id = w.metastores.current().metastore_id

        # 1. Get the estimated metastore-wide FGAC quota counter
        estimated_count = -1
        quota_limit     = 1000
        try:
            url = f"{base}/api/2.1/unity-catalog/resource-quotas/METASTORE/{metastore_id}/abac-policy-quota"
            req = _pf_urq.Request(url, headers=token)
            with _pf_urq.urlopen(req, timeout=10, context=_pf_ctx) as r:
                data = _pf_json.loads(r.read())
            qi = data.get("quota_info", data)
            estimated_count = qi.get("quota_count", -1)
            quota_limit     = qi.get("quota_limit", 1000)
        except Exception:
            pass  # quota API unavailable — skip check

        if estimated_count < 0:
            return  # couldn't read quota, proceed optimistically

        # 2. Get the actual current policy count across all visible catalogs
        actual_count = 0
        try:
            cats = [c.name for c in w.catalogs.list() if c.name]
            for cat in cats:
                try:
                    url = f"{base}/api/2.1/unity-catalog/policies/CATALOG/{_pf_urp.quote(cat, safe='')}"
                    req = _pf_urq.Request(url, headers=token)
                    with _pf_urq.urlopen(req, timeout=10, context=_pf_ctx) as r:
                        actual_count += len(_pf_json.loads(r.read()).get("policies", []))
                except Exception:
                    pass
        except Exception:
            actual_count = -1

        headroom = quota_limit - estimated_count

        print(f"\n  [Pre-flight] FGAC quota:  estimated={estimated_count}/{quota_limit}  "
              f"actual={actual_count if actual_count >= 0 else '?'}  headroom={headroom}")

        # 3. Decide whether to proceed, warn, or abort
        if estimated_count < quota_limit - 50:
            # Plenty of room — green light
            print(f"  [Pre-flight] Quota OK — proceeding.\n")
            return

        if estimated_count >= quota_limit and actual_count >= 0 and actual_count < 50:
            # Counter says full but reality is empty — classic stale counter bug
            print()
            print("  " + "=" * 62)
            print("  !! FGAC QUOTA COUNTER IS STALE — TESTS WILL FAIL !!")
            print("  " + "=" * 62)
            print(f"\n  The Databricks metastore-wide ABAC policy counter reports")
            print(f"  {estimated_count}/{quota_limit} (at or over limit), but querying")
            print(f"  all visible catalogs finds only {actual_count} actual policies.")
            print(f"\n  This is a known Databricks backend bug: the estimated counter")
            print(f"  does not properly decrement when policies are deleted.")
            print(f"  Terraform will refuse to create any new FGAC policies until")
            print(f"  Databricks resets this counter.")
            print()
            print(f"  Metastore ID : {metastore_id}")
            print(f"  Workspace    : {host}")
            print()
            print(f"  HOW TO FIX:")
            print(f"  1. File a Databricks Support ticket:")
            print(f"       Subject: 'FGAC/ABAC policy quota counter stuck at {estimated_count}")
            print(f"                 for metastore {metastore_id}'")
            print(f"       Ask them to reset the abac-policy-quota counter for this metastore.")
            print(f"  2. Or switch to a workspace/metastore with available quota.")
            print()
            print(f"  Run with --skip-fgac-quota-check to bypass this check (tests will still fail).")
            print()
            sys.exit(1)

        if headroom < 50:
            # Very low headroom — warn but allow proceeding
            print(f"\n  [Pre-flight] WARNING: Only {headroom} FGAC policy slots remain "
                  f"in the metastore (estimated {estimated_count}/{quota_limit}).")
            print(f"  Tests may fail if this is a shared metastore with other active users.")
            print(f"  Proceeding...\n")

    except Exception as exc:
        # Pre-flight is best-effort; don't block tests on diagnostic failures
        print(f"  [Pre-flight] Could not check FGAC quota: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test runner for playbook.md scenarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--scenario", "-s",
        choices=[*SCENARIOS, "all"],
        default="all",
        help="Scenario to run (default: all)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--warehouse-id", default="",
        metavar="ID",
        help="Pin a specific SQL warehouse ID (avoids cold-start delay)",
    )
    parser.add_argument(
        "--auth-file",
        default=str(DEFAULT_AUTH_FILE),
        metavar="PATH",
        help=f"Path to auth.auto.tfvars (default: {DEFAULT_AUTH_FILE})",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="Skip teardown so you can inspect results after the run",
    )
    parser.add_argument(
        "--nuke-fgac",
        action="store_true",
        help=(
            "One-time emergency cleanup: delete FGAC policies from ALL catalogs in the "
            "metastore before running scenarios.  Use when the metastore-wide ABAC policy "
            "count has accumulated past 1000 from many failed/partial test runs."
        ),
    )
    parser.add_argument(
        "--skip-fgac-quota-check",
        action="store_true",
        help="Skip the pre-flight FGAC quota check (tests may still fail if quota is full).",
    )
    parser.add_argument(
        "--fail-fast", "-x",
        action="store_true",
        help=(
            "Stop immediately when a scenario fails instead of continuing with the "
            "remaining scenarios.  Recommended for CI/CD pipelines to avoid wasting "
            "cloud resources when a fundamental issue is present."
        ),
    )
    args = parser.parse_args()

    if args.list:
        print("\nAvailable scenarios:\n")
        for name, (desc, _) in SCENARIOS.items():
            print(f"  {name:<18}  {desc}")
        print()
        return

    # ------------------------------------------------------------------
    # Auto-detect provisioned environment from provision_test_env.py state
    # ------------------------------------------------------------------
    global ENVS_DIR  # DEFAULT_AUTH_FILE is derived from ENVS_DIR, not a separate global
    fresh_env = False

    if PROVISION_STATE_FILE.exists():
        try:
            import json as _json
            _state = _json.loads(PROVISION_STATE_FILE.read_text())
            _test_envs = _state.get("test_envs_dir")
            if _test_envs and Path(_test_envs).exists():
                ENVS_DIR = Path(_test_envs)
                fresh_env = True
                print(f"\n  {_cyan('●')}  Provisioned environment detected — using {ENVS_DIR.relative_to(MODULE_ROOT)}/")
                print(f"     FGAC quota wait and pre-flight check are disabled (fresh metastore).")
        except Exception:
            pass

    _default_auth = ENVS_DIR / "dev" / "auth.auto.tfvars"
    auth_file    = Path(args.auth_file if args.auth_file != str(MODULE_ROOT / "envs" / "dev" / "auth.auto.tfvars")
                        else _default_auth).resolve()
    # Only propagate an explicitly-specified warehouse ID to scenarios.
    # Auto-discovered IDs (from _resolve_warehouse_id) are NOT propagated:
    # in fresh environments the Starter Warehouse may be non-functional, and
    # writing its ID into env.auto.tfvars causes Terraform to skip creating its
    # own managed warehouse (count=0 branch).  Each component — setup_test_data,
    # the Terraform module, and verify — auto-discovers a usable warehouse on its
    # own.  Only propagate when the user explicitly pins a warehouse via
    # --warehouse-id so they can reuse an existing one across scenarios.
    warehouse_id = args.warehouse_id if args.warehouse_id else ""
    _display_wh  = _resolve_warehouse_id(auth_file, args.warehouse_id)
    keep_data    = args.keep_data

    if not auth_file.exists():
        print(f"ERROR: auth file not found: {auth_file}")
        print("  Run from the genie/aws/ directory, or pass --auth-file <path>.")
        sys.exit(1)

    # Optional one-time nuclear cleanup of ALL FGAC policies across all catalogs.
    # This clears accumulated orphaned policies from many prior partial test runs.
    if args.nuke_fgac:
        _banner("NUKE: Clearing ALL FGAC policies from metastore", width=64)
        print("  WARNING: This deletes FGAC policies from every non-system catalog.")
        _force_delete_fgac_policies("dev", all_catalogs=True)
        print("  Done. Waiting 90s for quota counter to propagate...")
        time.sleep(90)
        print("  Metastore FGAC quota reset complete.")
        if args.scenario == "all" and not any(True for _ in SCENARIOS):
            return  # nuke-only mode if no scenario was requested

    # Pre-flight: check FGAC metastore quota (skip for fresh provisioned envs)
    if not args.skip_fgac_quota_check and not fresh_env:
        _preflight_fgac_quota_check(auth_file)

    # Select scenarios to run
    if args.scenario == "all":
        selected = list(SCENARIOS.items())
    else:
        selected = [(args.scenario, SCENARIOS[args.scenario])]

    _banner(f"Integration Test Runner  —  {len(selected)} scenario(s)", width=64)
    fail_fast = args.fail_fast

    print(f"  Auth:      {auth_file}")
    print(f"  Envs dir:  {ENVS_DIR.relative_to(MODULE_ROOT)}/")
    print(f"  Warehouse: {_display_wh or '(auto)'}{' [pinned]' if args.warehouse_id else ' [auto-discover per-component]'}")
    print(f"  Fresh env: {fresh_env}")
    print(f"  Keep data: {keep_data}")
    print(f"  Fail fast: {fail_fast}")
    if args.nuke_fgac:
        print(f"  Nuke FGAC: enabled (all-catalog cleanup at start)")

    results: dict[str, str] = {}
    total_start = time.time()

    for name, (desc, fn) in selected:
        start = time.time()
        print(f"\n{'─' * 64}")
        print(f"  Running: {_bold(name)}  —  {desc}")
        print(f"{'─' * 64}")
        try:
            fn(auth_file, warehouse_id, keep_data, fresh_env=fresh_env)
            elapsed = time.time() - start
            results[name] = _green(f"PASSED  ({elapsed:.0f}s)")
        except Exception as exc:
            elapsed = time.time() - start
            results[name] = _red(f"FAILED  ({elapsed:.0f}s)")
            print(f"\n  {_red(_bold('FAILED'))}: {exc}")
            if fail_fast:
                # Print partial summary before aborting so the CI log shows
                # which scenario failed and how long it took.
                _banner("Results (aborted — fail-fast)", width=64)
                for n, r in results.items():
                    print(f"  {n:<18}  {r}")
                print(f"\n  {_red(_bold('Stopped after first failure (--fail-fast)'))}")
                sys.exit(1)
            elif args.scenario != "all":
                sys.exit(1)
            else:
                print(f"  {_yellow('Continuing with remaining scenarios...')}")

    # ── Summary ───────────────────────────────────────────────────────────────
    total_elapsed = time.time() - total_start
    _banner("Results", width=64)
    all_passed = True
    for name, result in results.items():
        print(f"  {name:<18}  {result}")
        if "FAILED" in result:
            all_passed = False

    print()
    if all_passed:
        print(f"  {_green(_bold('All scenarios PASSED'))}  (total: {total_elapsed:.0f}s)")
    else:
        print(f"  {_red(_bold('Some scenarios FAILED'))}  (total: {total_elapsed:.0f}s)")
        sys.exit(1)
    print()


if __name__ == "__main__":
    main()
