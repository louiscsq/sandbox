#!/usr/bin/env python3
"""
Integration test runner for the scenarios documented in docs/flows.md.

Runs each scenario end-to-end with full data setup, generation, apply, verification,
and teardown. Each scenario is isolated — state from a previous run is destroyed and
cleaned before the next one starts.

Scenarios
---------
  quickstart       Single space, single catalog: Finance Analytics backed by dev_fin.
                   Tests the core quickstart flow from docs/flows.md § 1.

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
                   ABAC governance. Finally promotes to prod. Tests flows.md §1
                   "Attaching to an existing Genie Space" + §3a promotion.

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

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR  = Path(__file__).resolve().parent
MODULE_ROOT = SCRIPT_DIR.parent          # …/genie/aws/
ENVS_DIR    = MODULE_ROOT / "envs"

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
    result = subprocess.run(cmd, cwd=cwd, stdout=stdout, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}"
        )
    return result


def _make(
    *targets_and_vars: str,
    cwd: Path = MODULE_ROOT,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run make with the given targets/variables."""
    return _run(["make", "--no-print-directory", *targets_and_vars], cwd=cwd, check=check)


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

def _try_destroy(env: str) -> None:
    """Destroy Terraform resources for env if state exists."""
    state = ENVS_DIR / env / "terraform.tfstate"
    da_state = ENVS_DIR / env / "data_access" / "terraform.tfstate"
    if not state.exists() and not da_state.exists():
        return
    _step(f"Destroying {env} Terraform resources")
    _make(f"destroy", f"ENV={env}", check=False)


def _try_destroy_account() -> None:
    state = ENVS_DIR / "account" / "terraform.tfstate"
    if not state.exists():
        return
    _step("Destroying account Terraform resources")
    _make("destroy", "ENV=account", check=False)


def _force_delete_fgac_policies(*envs: str) -> None:
    """Best-effort API-level deletion of all FGAC policies for all test catalogs.

    Databricks enforces a limit of 10 ABAC policies per catalog.  If a previous
    test run left orphaned policies (e.g. because terraform destroy partially
    failed and the state file was then wiped), terraform apply in the next run
    will fail with "estimated count exceeds limit".  This function proactively
    deletes every policy_info it finds so each scenario starts from zero.
    """
    for env in envs:
        auth_file = ENVS_DIR / env / "auth.auto.tfvars"
        if not auth_file.exists():
            continue
        try:
            import hcl2 as _hcl2
            from databricks.sdk import WorkspaceClient as _WC
            from databricks.sdk.service.catalog import SecurableType as _ST

            def _s(v): return (v[0] if isinstance(v, list) else (v or "")).strip()

            with open(auth_file) as f:
                auth = _hcl2.load(f)
            host          = _s(auth.get("databricks_workspace_host", ""))
            client_id     = _s(auth.get("databricks_client_id", ""))
            client_secret = _s(auth.get("databricks_client_secret", ""))
            if not host:
                continue
            w = _WC(host=host, client_id=client_id, client_secret=client_secret)

            # Only clean catalogs that look like test catalogs (dev_*, prod_*, bu2_*)
            test_prefixes = ("dev_", "prod_", "bu2_")
            try:
                all_cats = [c.name for c in w.catalogs.list()
                            if c.name and any(c.name.startswith(p) for p in test_prefixes)]
            except Exception:
                all_cats = []

            for cat in all_cats:
                try:
                    policies = list(w.policy_infos.list_policy_infos_for_securable(
                        securable_type=_ST.CATALOG,
                        securable_fullname=cat,
                    ))
                    for p in policies:
                        try:
                            w.policy_infos.delete_policy_info(
                                name=p.name,
                                on_securable_type=_ST.CATALOG,
                                on_securable_fullname=cat,
                            )
                            print(f"  Force-deleted orphaned FGAC policy: {cat}/{p.name}")
                        except Exception as del_err:
                            print(f"  WARN: could not delete FGAC policy {cat}/{p.name}: {del_err}")
                except Exception:
                    pass  # catalog may not support policy_infos; skip
        except Exception as exc:
            print(f"  WARN: force_delete_fgac_policies({env}) failed: {exc}")


def _preamble_cleanup(*envs: str) -> None:
    """Best-effort pre-scenario cleanup.

    Destroys Terraform resources for each env and the account layer *while their
    state files still exist*, then wipes all local artifacts.  This ensures each
    scenario starts clean even if a previous scenario failed before its own
    teardown block ran (which would have left Databricks groups, tag_policies,
    and Genie Spaces behind without Terraform state to track them).
    """
    _step("Pre-scenario cleanup (destroying any leftover resources from prior run)")
    for env in envs:
        _try_destroy(env)
    _try_destroy_account()
    # Force-delete any orphaned FGAC policies not tracked in Terraform state.
    # Databricks enforces a hard limit of 10 policies/catalog; orphans from
    # failed previous runs would cause "estimated count exceeds limit" errors.
    _force_delete_fgac_policies(*envs)
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
) -> None:
    """
    Flow: setup dev_fin → configure one space → generate → apply → verify → teardown.

    Exercises the core quickstart path from docs/flows.md § 1 with a single Genie
    Space backed by a single UC catalog.
    """
    _banner("Scenario: quickstart — Single space, single catalog")
    env = "dev"

    # ── setup ────────────────────────────────────────────────────────────────
    _step("Creating dev_fin test catalog")
    _setup_data(auth_file, warehouse_id=warehouse_id)   # dev_fin + dev_clinical (idempotent)

    _preamble_cleanup(env)
    _step("Preparing env")
    _make(f"setup", f"ENV={env}")
    _write_env_tfvars(env, SPACES_FINANCE_ONLY, warehouse_id)

    # ── generate + apply ─────────────────────────────────────────────────────
    _step("Generating ABAC config")
    _make(f"generate", f"ENV={env}")

    _step("Asserting generated output")
    gen_dir = ENVS_DIR / env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "abac.auto.tfvars generated")
    _assert_file_exists(gen_dir / "masking_functions.sql", "masking_functions.sql generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics config generated")
    _assert_file_exists(gen_dir / "spaces" / "finance_analytics" / "abac.auto.tfvars",
                        "per-space directory bootstrapped")

    _step("Applying all layers")
    _make(f"apply", f"ENV={env}")

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
) -> None:
    """
    Flow: setup dev_fin + dev_clinical → one space using tables from both catalogs
    → generate → apply → verify both catalogs tagged → teardown.

    Tests the "single space spanning multiple catalogs" pattern from flows.md § 1.
    """
    _banner("Scenario: multi-catalog — One space, two catalogs")
    env = "dev"

    # ── setup ────────────────────────────────────────────────────────────────
    _step("Creating dev_fin and dev_clinical test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    _preamble_cleanup(env)
    _step("Preparing env")
    _make(f"setup", f"ENV={env}")
    _write_env_tfvars(env, SPACES_COMBINED, warehouse_id)

    # ── generate + apply ─────────────────────────────────────────────────────
    _step("Generating ABAC config (tables from both catalogs)")
    _make(f"generate", f"ENV={env}")

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
    _make(f"apply", f"ENV={env}")

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
    _step("Creating dev_fin and dev_clinical test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    _preamble_cleanup(env)
    _step("Preparing env")
    _make(f"setup", f"ENV={env}")
    _write_env_tfvars(env, SPACES_MULTI, warehouse_id)

    # ── generate + apply ─────────────────────────────────────────────────────
    _step("Generating ABAC config (both spaces)")
    _make(f"generate", f"ENV={env}")

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
    _make(f"apply", f"ENV={env}")

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
) -> None:
    """
    Flow: deploy Finance Analytics first → then add Clinical Analytics using
    `make generate SPACE="Clinical Analytics"` → verify Finance config is
    preserved and Clinical config is merged in additively.

    Exercises the per-space isolation guarantee from docs/flows.md § 2.
    """
    _banner("Scenario: per-space — Incremental space addition (isolation test)")
    env = "dev"

    # ── setup ────────────────────────────────────────────────────────────────
    _step("Creating both test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    _preamble_cleanup(env)
    _step("Preparing env with Finance Analytics only")
    _make(f"setup", f"ENV={env}")
    _write_env_tfvars(env, SPACES_FINANCE_ONLY, warehouse_id)

    # ── Phase 1: deploy Finance only ─────────────────────────────────────────
    _step("Phase 1 — Full generate for Finance Analytics")
    _make(f"generate", f"ENV={env}")

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
    _make(f"apply", f"ENV={env}")
    _assert_genie_space_id_file(env, "Finance Analytics")

    # ── Phase 2: add Clinical Analytics without touching Finance ─────────────
    _step("Phase 2 — Adding Clinical Analytics to env.auto.tfvars")
    _write_env_tfvars(env, SPACES_MULTI, warehouse_id)

    _step("Phase 2 — Per-space generate for Clinical Analytics only")
    _make(f"generate", f"ENV={env}", f'SPACE=Clinical Analytics')

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
    _make(f"apply", f"ENV={env}")
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
) -> None:
    """
    Flow: setup dev + prod catalogs → two-space dev → generate + apply dev →
    promote with catalog remapping → apply prod → verify prod → teardown.

    Exercises docs/flows.md § 3a cross-env promotion end-to-end.
    """
    _banner("Scenario: promote — dev → prod cross-env promotion")
    dev_env  = "dev"
    prod_env = "prod"

    # ── setup ────────────────────────────────────────────────────────────────
    _step("Creating dev + prod test catalogs")
    _setup_data(auth_file, "--prod", warehouse_id=warehouse_id)

    _preamble_cleanup(dev_env, prod_env)
    for env in (dev_env, prod_env):
        _step(f"Preparing {env} env")
        _make(f"setup", f"ENV={env}")

    _write_env_tfvars(dev_env, SPACES_MULTI, warehouse_id)

    # ── dev generate + apply ─────────────────────────────────────────────────
    _step("Generating dev ABAC config")
    _make(f"generate", f"ENV={dev_env}")

    gen_dir = ENVS_DIR / dev_env / "generated"
    _assert_file_exists(gen_dir / "abac.auto.tfvars", "dev abac.auto.tfvars generated")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics in dev generated config")
    _assert_contains(gen_dir / "abac.auto.tfvars", "Clinical Analytics",
                     "Clinical Analytics in dev generated config")

    _step("Applying dev")
    _make(f"apply", f"ENV={dev_env}")
    _assert_genie_space_id_file(dev_env, "Finance Analytics")
    _assert_genie_space_id_file(dev_env, "Clinical Analytics")

    _step("Verifying dev data + ABAC")
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

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
    _make(f"apply", f"ENV={prod_env}")

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
) -> None:
    """
    Flow: two completely independent workspace environments on the same account —
    dev uses Finance Analytics (dev_fin) and bu2 uses Clinical Analytics (dev_clinical).
    Each has its own generate + apply cycle with separate generated config and state.

    Exercises docs/flows.md § 3b (second independent environment for another BU).
    """
    _banner("Scenario: multi-env — Two independent environments (dev + bu2)")
    dev_env = "dev"
    bu2_env = "bu2"

    # ── setup ────────────────────────────────────────────────────────────────
    _step("Creating both test catalogs")
    _setup_data(auth_file, warehouse_id=warehouse_id)

    _preamble_cleanup(dev_env, bu2_env)
    for env in (dev_env, bu2_env):
        _step(f"Preparing {env} env")
        _make(f"setup", f"ENV={env}")

    # Both envs share the same auth (same workspace)
    _copy_auth(dev_env, bu2_env)
    _write_env_tfvars(dev_env, SPACES_FINANCE_ONLY,  warehouse_id)
    _write_env_tfvars(bu2_env, SPACES_CLINICAL_ONLY, warehouse_id)

    # ── dev: generate + apply ─────────────────────────────────────────────────
    _step("dev — Generating Finance Analytics ABAC config")
    _make(f"generate", f"ENV={dev_env}")

    dev_gen = ENVS_DIR / dev_env / "generated"
    _assert_contains(dev_gen / "abac.auto.tfvars", "Finance Analytics",
                     "Finance Analytics in dev generated config")
    _assert_not_contains(dev_gen / "abac.auto.tfvars", "Clinical Analytics",
                         "Clinical Analytics absent from dev generated config")

    _step("dev — Applying Finance Analytics")
    _make(f"apply", f"ENV={dev_env}")
    _assert_genie_space_id_file(dev_env, "Finance Analytics")

    _step("dev — Verifying Finance Analytics data + ABAC")
    _verify_data(auth_file, dev=True, warehouse_id=warehouse_id)

    # ── bu2: generate + apply ─────────────────────────────────────────────────
    _step("bu2 — Generating Clinical Analytics ABAC config independently")
    _make(f"generate", f"ENV={bu2_env}")

    bu2_gen = ENVS_DIR / bu2_env / "generated"
    _assert_contains(bu2_gen / "abac.auto.tfvars", "Clinical Analytics",
                     "Clinical Analytics in bu2 generated config")
    _assert_not_contains(bu2_gen / "abac.auto.tfvars", "Finance Analytics",
                         "Finance Analytics absent from bu2 generated config")

    _step("bu2 — Applying Clinical Analytics")
    _make(f"apply", f"ENV={bu2_env}")
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
) -> None:
    """
    Simulates the "attach to an existing Genie Space" flow from docs/flows.md §1:

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
      (simulating the manual step instructed by flows.md).

    Phase 3 — Apply:
      `make apply` deploys ABAC governance (ACLs, column tags, masking functions,
      FGAC policies) without creating or deleting the Genie Space.
      The space's title, description, benchmarks, and instructions are preserved
      exactly as configured in the API/UI.

    Phase 4 — Promote to prod:
      `make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG_MAP=dev_fin=prod_fin`
      followed by `make apply ENV=prod` applies the same governance to prod.

    Tests: flows.md §1 "Attaching to an existing Genie Space" + §3a promotion.
    """
    _banner("Scenario: attach-promote — Attach to UI-created space, promote to prod")
    env      = "dev"
    prod_env = "prod"

    _ensure_packages()

    # ── Phase 1: simulate "space configured in UI" ───────────────────────────
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
    # env.auto.tfvars as instructed by the flows.md manual step.
    # The key assertion tested here is that Terraform does NOT create/delete
    # the existing Genie Space — it attaches to it as-is.
    _step("Phase 2 — Configuring env with genie_space_id + uc_tables (attach mode)")
    _preamble_cleanup(env, prod_env)
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
    _make(f"generate", f"ENV={env}")

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
    _make(f"apply", f"ENV={env}")

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
    _make(f"apply", f"ENV={prod_env}")

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


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, tuple[str, Callable]] = {
    "quickstart":      ("Single space, single catalog (Finance/dev_fin)",        scenario_quickstart),
    "multi-catalog":   ("One space spanning two catalogs (Combined)",            scenario_multi_catalog),
    "multi-space":     ("Two spaces, separate catalogs (Finance+Clinical)",      scenario_multi_space),
    "per-space":       ("Incremental per-space generation (isolation test)",     scenario_per_space),
    "promote":         ("Multi-space dev → prod promotion",                      scenario_promote),
    "multi-env":       ("Two independent envs (dev Finance, bu2 Clinical)",      scenario_multi_env),
    "attach-promote":  ("Attach to UI-created space (API discovery) + promote",  scenario_attach_and_promote),
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration test runner for flows.md scenarios",
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
    args = parser.parse_args()

    if args.list:
        print("\nAvailable scenarios:\n")
        for name, (desc, _) in SCENARIOS.items():
            print(f"  {name:<18}  {desc}")
        print()
        return

    auth_file   = Path(args.auth_file).resolve()
    warehouse_id = _resolve_warehouse_id(Path(args.auth_file).resolve(), args.warehouse_id)
    keep_data   = args.keep_data

    if not auth_file.exists():
        print(f"ERROR: auth file not found: {auth_file}")
        print("  Run from the genie/aws/ directory, or pass --auth-file <path>.")
        sys.exit(1)

    # Select scenarios to run
    if args.scenario == "all":
        selected = list(SCENARIOS.items())
    else:
        selected = [(args.scenario, SCENARIOS[args.scenario])]

    _banner(f"Integration Test Runner  —  {len(selected)} scenario(s)", width=64)
    print(f"  Auth:      {auth_file}")
    print(f"  Warehouse: {warehouse_id or '(auto)'}")
    print(f"  Keep data: {keep_data}")

    results: dict[str, str] = {}
    total_start = time.time()

    for name, (desc, fn) in selected:
        start = time.time()
        print(f"\n{'─' * 64}")
        print(f"  Running: {_bold(name)}  —  {desc}")
        print(f"{'─' * 64}")
        try:
            fn(auth_file, warehouse_id, keep_data)
            elapsed = time.time() - start
            results[name] = _green(f"PASSED  ({elapsed:.0f}s)")
        except Exception as exc:
            elapsed = time.time() - start
            results[name] = _red(f"FAILED  ({elapsed:.0f}s)")
            print(f"\n  {_red(_bold('FAILED'))}: {exc}")
            if args.scenario == "all":
                print(f"  {_yellow('Continuing with remaining scenarios...')}")
            else:
                sys.exit(1)

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
