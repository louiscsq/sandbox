"""GenieRails telemetry utilities.

Ensures every Databricks API call — whether from the Python SDK or from
``terraform`` CLI — is attributed to ``genierails`` in the User-Agent header.

Architecture (mirrors https://github.com/databrickslabs/dqx):

1. **Import-time registration** — ``ua.with_extra`` / ``ua.with_product``
   adds ``genierails/<version>`` to every SDK User-Agent header globally.

2. **WorkspaceClient patching** — ``verify_workspace_client`` forces
   ``_product_info`` on any client so even externally-created clients
   carry the correct attribution.

3. **Action-level telemetry** — ``log_telemetry`` and the
   ``@telemetry_logger`` decorator fire a lightweight API call with an
   extra ``key=value`` User-Agent pair so the Databricks control plane
   records which actions are invoked.

4. **Terraform telemetry** — ``terraform_env`` returns env vars
   (``DATABRICKS_USER_AGENT_EXTRA``) for subprocess calls to
   ``terraform``, and ``run_terraform`` is a convenience wrapper.
"""

import functools
import logging
import os
import re
import subprocess
import sys
from typing import Callable

PRODUCT_NAME = "genierails"
PRODUCT_VERSION = "0.1.0"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Import-time SDK User-Agent registration
# ---------------------------------------------------------------------------
# Mirrors dqx/__init__.py — runs once when this module is first imported.
# Every subsequent WorkspaceClient will include "genierails/0.1.0" in its
# User-Agent header automatically.

try:
    import databricks.sdk.useragent as ua

    # Relax semver pattern to allow dev/pre-release versions like "0.1.0-dev"
    ua.semver_pattern = re.compile(r"^(\d+\.)?(\d+\.)?(\*|\d+).*")

    ua.with_extra(PRODUCT_NAME, PRODUCT_VERSION)
    ua.with_product(PRODUCT_NAME, PRODUCT_VERSION)
    logger.debug(
        "Registered SDK User-Agent: %s/%s", PRODUCT_NAME, PRODUCT_VERSION
    )
except (ImportError, ModuleNotFoundError):
    # databricks-sdk not installed yet — callers handle this via
    # _ensure_packages() before creating any WorkspaceClient.
    logger.debug("databricks.sdk.useragent not available — skipping import-time registration")

# ---------------------------------------------------------------------------
# 2. WorkspaceClient patching
# ---------------------------------------------------------------------------


def verify_workspace_client(ws):
    """Ensure *ws* carries the genierails product info for telemetry.

    If the client was created without ``product=PRODUCT_NAME``, this patches
    ``_product_info`` on its config so that every subsequent API call includes
    the correct User-Agent attribution.

    Returns the (possibly patched) client.
    """
    product_info = getattr(ws.config, "_product_info", None)
    if product_info is None or product_info[0] != PRODUCT_NAME:
        setattr(ws.config, "_product_info", (PRODUCT_NAME, PRODUCT_VERSION))
        logger.debug(
            "Patched WorkspaceClient _product_info -> %s/%s",
            PRODUCT_NAME,
            PRODUCT_VERSION,
        )
    return ws

# ---------------------------------------------------------------------------
# 3. Action-level telemetry
# ---------------------------------------------------------------------------


def log_telemetry(ws, key: str, value: str) -> None:
    """Log an action-level telemetry event on the Databricks control plane.

    Creates a *copy* of the client config with the extra user-agent pair
    ``key=value``, then fires a lightweight API call
    (``clusters.select_spark_version``) so the control plane records it.

    This intentionally does **not** mutate the original client.
    """
    from databricks.sdk import WorkspaceClient

    new_config = ws.config.copy().with_user_agent_extra(key, value)
    tmp = WorkspaceClient(config=new_config)
    logger.debug("Logging telemetry %s=%s", key, value)
    try:
        tmp.clusters.select_spark_version()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Telemetry ping failed (non-fatal): %s", exc)


def telemetry_logger(key: str, value: str, *, ws_attr: str = "ws") -> Callable:
    """Decorator that logs telemetry before executing the wrapped function.

    Works on both plain functions and methods. For methods, it looks up the
    WorkspaceClient from ``self.<ws_attr>``; for plain functions it looks for
    a ``ws`` keyword argument.

    Usage on a method::

        class Engine:
            def __init__(self, ws):
                self.ws = ws

            @telemetry_logger("engine", "apply_checks")
            def apply_checks(self, df):
                ...

    Usage on a plain function::

        @telemetry_logger("action", "deploy")
        def deploy(ws, sql_file, warehouse_id):
            ...
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            ws = None
            # Try to get ws from 'self.<ws_attr>' (method) or first positional arg
            if args:
                ws = getattr(args[0], ws_attr, None)
                if ws is None and hasattr(args[0], "config"):
                    # First arg might be the WorkspaceClient itself
                    ws = args[0]
            if ws is None:
                ws = kwargs.get("ws") or kwargs.get("w")
            if ws is not None:
                try:
                    log_telemetry(ws, key, value)
                except Exception:  # noqa: BLE001
                    pass
            return fn(*args, **kwargs)

        return wrapper

    return decorator

# ---------------------------------------------------------------------------
# 4. Terraform telemetry
# ---------------------------------------------------------------------------


def terraform_env() -> dict[str, str]:
    """Return env vars that attribute Terraform provider API calls to genierails.

    The Databricks Terraform provider reads ``DATABRICKS_USER_AGENT_EXTRA``
    and appends it to every API request's User-Agent header.

    Usage::

        env = {**os.environ, **terraform_env()}
        subprocess.run(["terraform", "apply"], env=env)
    """
    return {
        "DATABRICKS_USER_AGENT_EXTRA": f"{PRODUCT_NAME}/{PRODUCT_VERSION}",
    }


def run_terraform(
    args: list[str],
    *,
    cwd: str | None = None,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess:
    """Run a ``terraform`` command with genierails User-Agent attribution.

    Merges ``terraform_env()`` into the current environment so the Databricks
    Terraform provider includes ``genierails/0.1.0`` in every API call.

    Args:
        args: Terraform sub-command and flags, e.g. ``["apply", "-auto-approve"]``.
        cwd: Working directory (defaults to caller's cwd).
        check: Raise on non-zero exit (default True).
        capture_output: Capture stdout/stderr (default False).

    Returns:
        ``subprocess.CompletedProcess``
    """
    cmd = ["terraform", *args]
    env = {**os.environ, **terraform_env()}
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=capture_output,
        text=True,
    )
