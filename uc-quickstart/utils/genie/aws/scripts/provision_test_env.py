#!/usr/bin/env python3
"""
Provision a fresh integration-test environment: one serverless Databricks workspace
+ one Unity Catalog metastore, with the test Service Principal set as both
metastore admin and workspace admin.

Solves the FGAC quota counter drift problem by giving every integration-test
run a brand-new metastore (counter always starts at 0).  After the run, call
`teardown` to delete the workspace and metastore — wiping all state cleanly.

Usage
-----
  # One-time: copy the example and fill in your account-admin SP credentials
  cp scripts/account-admin.env.example scripts/account-admin.env

  # Provision a fresh environment (≈10-15 min for workspace creation)
  python scripts/provision_test_env.py provision

  # Check what is currently provisioned
  python scripts/provision_test_env.py status

  # Run the integration tests against the provisioned environment
  python scripts/run_integration_tests.py --scenario all

  # Tear down everything when done
  python scripts/provision_test_env.py teardown

Environment file (scripts/account-admin.env)
--------------------------------------------
  DATABRICKS_ACCOUNT_ID       = <your Databricks account UUID>
  DATABRICKS_CLIENT_ID        = <SP application/client ID — must have Account Admin>
  DATABRICKS_CLIENT_SECRET    = <SP OAuth secret>
  DATABRICKS_AWS_REGION       = ap-southeast-2   # or your region

  # AWS credentials (needed to create/delete the UC IAM role automatically).
  # Leave blank to use the default boto3 chain: ~/.aws/credentials, AWS_PROFILE,
  # instance profile, etc.
  AWS_ACCESS_KEY_ID     =
  AWS_SECRET_ACCESS_KEY =

Storage setup (fully automated)
--------------------------------
  The provision script creates everything needed in AWS and Databricks:

  0. S3 bucket        — named genie-uc-test-<aws-account-id>.  Created on first
                        run; reused if it already exists.  Deleted on teardown.
  1. AWS IAM role     — a fresh role scoped to the test-run S3 prefix, with the
                        correct UC trust policy (principal = Databricks UC service).
  2. Storage credential — registered in the new metastore via the Databricks API.
  3. External Location  — path-scoped S3 prefix for this run registered in the
                          new workspace, so catalogs can be created without a
                          metastore-level storage root.

  The IAM role and S3 test prefix are both deleted automatically by `teardown`.
  The bucket itself is deleted only if this script created it.

  You only need to provide:
    • AWS credentials with permission to create/delete IAM roles, S3 buckets,
      and policies (iam:CreateRole, iam:DeleteRole, iam:PutRolePolicy,
      iam:DeleteRolePolicy, iam:UpdateAssumeRolePolicy, sts:GetCallerIdentity,
      s3:CreateBucket, s3:DeleteBucket, s3:PutPublicAccessBlock,
      s3:ListBucketVersions, s3:DeleteObject, s3:DeleteObjectVersion).

State file
----------
  scripts/.test_env_state.json  — written by provision, read by teardown.
  This file is gitignored.  If it is missing, teardown does nothing.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR  = Path(__file__).resolve().parent
MODULE_ROOT = SCRIPT_DIR.parent
ENVS_DIR    = MODULE_ROOT / "envs"          # user's real envs (never touched)
TEST_ENVS_DIR = MODULE_ROOT / "envs" / "test"  # isolated dir for integration tests
STATE_FILE  = SCRIPT_DIR / ".test_env_state.json"
DEFAULT_ENV_FILE = SCRIPT_DIR / "account-admin.env"

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

def _green(s: str) -> str:  return f"\033[32m{s}\033[0m"
def _red(s: str)   -> str:  return f"\033[31m{s}\033[0m"
def _cyan(s: str)  -> str:  return f"\033[36m{s}\033[0m"
def _bold(s: str)  -> str:  return f"\033[1m{s}\033[0m"
def _yellow(s: str)-> str:  return f"\033[33m{s}\033[0m"

def _banner(title: str) -> None:
    width = 66
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)

def _step(msg: str) -> None:
    print(f"\n{_cyan('──')} {msg}")

def _ok(msg: str) -> None:
    print(f"  {_green('✓')}  {msg}")

def _warn(msg: str) -> None:
    print(f"  {_yellow('⚠')}  {msg}", file=sys.stderr)

def _err(msg: str) -> None:
    print(f"  {_red('✗')}  {msg}", file=sys.stderr)

# ---------------------------------------------------------------------------
# AWS / IAM helpers  (boto3-based, installed on demand)
# ---------------------------------------------------------------------------

def _ensure_boto3() -> None:
    try:
        import boto3  # noqa: F401
    except ImportError:
        import subprocess
        _warn("boto3 not found — installing…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "boto3"])


def _aws_session(cfg: dict[str, str], region: str):
    """Return a boto3 Session using explicit keys from cfg or the default chain."""
    import boto3

    kwargs: dict = {}
    if cfg.get("AWS_ACCESS_KEY_ID"):
        kwargs["aws_access_key_id"]     = cfg["AWS_ACCESS_KEY_ID"]
        kwargs["aws_secret_access_key"] = cfg.get("AWS_SECRET_ACCESS_KEY", "")
        if cfg.get("AWS_SESSION_TOKEN"):
            kwargs["aws_session_token"] = cfg["AWS_SESSION_TOKEN"]
    if cfg.get("AWS_PROFILE") and "aws_access_key_id" not in kwargs:
        kwargs["profile_name"] = cfg["AWS_PROFILE"]
    return boto3.Session(region_name=region, **kwargs)


def _create_uc_iam_role(
    cfg: dict,
    role_name: str,
    bucket: str,          # just the bucket name, no s3:// prefix
    account_id: str,      # Databricks account UUID (used as ExternalId)
    region: str,
) -> str:
    """Create an IAM role suitable for a UC External Location. Returns the role ARN.

    Initial trust policy allows the generic Databricks UC root principal
    (414351767826:root) to assume the role.  After the Databricks storage
    credential is created, call _update_uc_trust_policy() to tighten it to
    the specific unity_catalog_iam_arn returned by the API.
    """
    _ensure_boto3()
    session = _aws_session(cfg, region)
    iam = session.client("iam")

    # Determine the caller's AWS account ID for the ARN we're about to create.
    sts       = session.client("sts", region_name=region)
    aws_acct  = sts.get_caller_identity()["Account"]
    role_arn  = f"arn:aws:iam::{aws_acct}:role/{role_name}"

    # Initial trust: only the generic Databricks root principal.
    # We cannot include the role's own ARN here because the role doesn't exist
    # yet (circular reference).  The self-assume + specific UC principal ARN
    # are both added by _update_uc_trust_policy() after the role is created.
    initial_trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": "arn:aws:iam::414351767826:root"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": account_id}},
            },
        ],
    }

    iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(initial_trust),
        Description="Unity Catalog External Location role - provision_test_env.py",
        Tags=[
            {"Key": "ManagedBy",  "Value": "provision_test_env"},
            {"Key": "DatabricksAccountId", "Value": account_id},
        ],
    )

    # Inline S3 permission policy — scoped to the test bucket.
    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
                    "s3:GetBucketLocation", "s3:ListBucket",
                    "s3:ListBucketMultipartUploads", "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                    f"arn:aws:s3:::{bucket}/*",
                ],
            },
        ],
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=f"{role_name}-s3",
        PolicyDocument=json.dumps(s3_policy),
    )

    # IAM changes can take a few seconds to propagate globally.
    _warn("Waiting 15 s for IAM role to propagate…")
    time.sleep(15)
    return role_arn


def _update_uc_trust_policy(
    cfg: dict,
    role_name: str,
    role_arn: str,
    unity_catalog_iam_arn: str,
    account_id: str,
    region: str,
) -> None:
    """Narrow the trust policy to the specific Databricks UC principal."""
    _ensure_boto3()
    session = _aws_session(cfg, region)
    iam     = session.client("iam")

    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": unity_catalog_iam_arn},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": account_id}},
            },
            {
                "Effect": "Allow",
                "Principal": {"AWS": role_arn},
                "Action": "sts:AssumeRole",
            },
        ],
    }
    iam.update_assume_role_policy(
        RoleName=role_name,
        PolicyDocument=json.dumps(trust),
    )


def _ensure_s3_bucket(cfg: dict, bucket_name: str, region: str) -> bool:
    """Create the S3 bucket if it does not already exist.

    Returns True if the bucket was created by this call (and should therefore
    be deleted on teardown), False if it already existed.
    """
    _ensure_boto3()
    from botocore.exceptions import ClientError

    session = _aws_session(cfg, region)
    s3 = session.client("s3", region_name=region)

    try:
        s3.head_bucket(Bucket=bucket_name)
        _ok(f"S3 bucket already exists: s3://{bucket_name}")
        return False
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in ("404", "NoSuchBucket", "403"):
            # Unexpected error — re-raise so it surfaces clearly.
            raise

    # Bucket does not exist (404/NoSuchBucket) or we got 403 on a bucket name
    # that belongs to someone else.  403 is treated as "exists but not ours";
    # only 404/NoSuchBucket means we should create it.
    if code == "403":
        _err(f"S3 bucket s3://{bucket_name} exists but is owned by another AWS account.")
        _err("Choose a different bucket name in DATABRICKS_S3_BUCKET.")
        raise RuntimeError(f"Bucket s3://{bucket_name} is owned by another account (HTTP 403).")

    _step(f"Creating S3 bucket: s3://{bucket_name}  (region={region})")
    try:
        if region == "us-east-1":
            # us-east-1 does NOT accept a LocationConstraint — it's the default.
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        # Block public access — best practice for UC storage buckets.
        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        _ok(f"S3 bucket created: s3://{bucket_name}")
        return True
    except ClientError as exc:
        _err(f"Could not create S3 bucket s3://{bucket_name}: {exc}")
        raise


def _delete_s3_prefix(cfg: dict, bucket_name: str, prefix: str, region: str) -> None:
    """Delete all objects under *prefix* inside *bucket_name*."""
    _ensure_boto3()
    from botocore.exceptions import ClientError

    session = _aws_session(cfg, region)
    s3 = session.client("s3", region_name=region)

    prefix = prefix.rstrip("/") + "/"
    _step(f"Deleting S3 objects under s3://{bucket_name}/{prefix}")
    paginator = s3.get_paginator("list_objects_v2")
    deleted = 0
    try:
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            s3.delete_objects(
                Bucket=bucket_name,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
            )
            deleted += len(objects)
    except ClientError as exc:
        _warn(f"Could not fully clean S3 prefix s3://{bucket_name}/{prefix}: {exc}")
    _ok(f"Deleted {deleted} object(s) from s3://{bucket_name}/{prefix}")


def _delete_s3_bucket(cfg: dict, bucket_name: str, region: str) -> None:
    """Empty and delete an S3 bucket that was created by _ensure_s3_bucket."""
    _ensure_boto3()
    from botocore.exceptions import ClientError

    session = _aws_session(cfg, region)
    s3 = session.client("s3", region_name=region)

    # Delete all object versions and delete-markers (handles versioned buckets).
    _step(f"Emptying S3 bucket: s3://{bucket_name}")
    try:
        paginator = s3.get_paginator("list_object_versions")
        deleted = 0
        for page in paginator.paginate(Bucket=bucket_name):
            to_delete = [
                {"Key": v["Key"], "VersionId": v["VersionId"]}
                for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
            ]
            if to_delete:
                s3.delete_objects(Bucket=bucket_name, Delete={"Objects": to_delete})
                deleted += len(to_delete)
    except ClientError as exc:
        _warn(f"Could not empty bucket (may have no versioning): {exc}")

    # Also handle non-versioned objects.
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name):
            objects = page.get("Contents", [])
            if objects:
                s3.delete_objects(
                    Bucket=bucket_name,
                    Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
                )
    except ClientError as exc:
        _warn(f"Could not clean non-versioned objects: {exc}")

    try:
        s3.delete_bucket(Bucket=bucket_name)
        _ok(f"S3 bucket deleted: s3://{bucket_name}")
    except ClientError as exc:
        _warn(f"Could not delete S3 bucket s3://{bucket_name}: {exc}")
        _warn("Delete it manually in the AWS Console → S3.")


def _delete_iam_role(cfg: dict, role_name: str, region: str) -> None:
    """Delete the IAM role created by _create_uc_iam_role (inline policies + role)."""
    _ensure_boto3()
    session = _aws_session(cfg, region)
    iam     = session.client("iam")

    try:
        for policy in iam.list_role_policies(RoleName=role_name).get("PolicyNames", []):
            iam.delete_role_policy(RoleName=role_name, PolicyName=policy)
    except iam.exceptions.NoSuchEntityException:
        return  # role doesn't exist — nothing to do

    try:
        for p in iam.list_attached_role_policies(RoleName=role_name).get("AttachedPolicies", []):
            iam.detach_role_policy(RoleName=role_name, PolicyArn=p["PolicyArn"])
    except Exception:
        pass

    try:
        iam.delete_role(RoleName=role_name)
    except Exception as exc:
        _warn(f"Could not delete IAM role {role_name!r}: {exc}")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE .env file (comments and blank lines ignored)."""
    cfg: dict[str, str] = {}
    if not path.exists():
        return cfg
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def _load_config(env_file: Path) -> dict[str, str]:
    """Load config from env file, with os.environ overrides."""
    cfg = _load_env_file(env_file)
    for key in [
        "DATABRICKS_ACCOUNT_ID",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
        "DATABRICKS_AWS_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ]:
        if key in os.environ:
            cfg[key] = os.environ[key]
    return cfg


def _validate_config(cfg: dict[str, str]) -> None:
    required = [
        "DATABRICKS_ACCOUNT_ID",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
        "DATABRICKS_AWS_REGION",
    ]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        _err(f"Missing required config keys: {', '.join(missing)}")
        print(f"\n  Edit {DEFAULT_ENV_FILE} and fill in all values.", file=sys.stderr)
        sys.exit(1)

# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return None


def _clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()

# ---------------------------------------------------------------------------
# Workspace URL helper
# ---------------------------------------------------------------------------

def _workspace_host(workspace) -> str:
    """Derive the workspace HTTPS host from a Workspace SDK object."""
    # The SDK returns deployment_name like "dbc-b89659bd-e807"
    # Workspace URL is https://<deployment_name>.cloud.databricks.com
    if hasattr(workspace, "workspace_url") and workspace.workspace_url:
        url = workspace.workspace_url
        return url if url.startswith("https://") else f"https://{url}"
    deployment = getattr(workspace, "deployment_name", None)
    if deployment:
        return f"https://{deployment}.cloud.databricks.com"
    # Fallback: construct from workspace_id (works for most AWS deployments)
    return f"https://dbc-{workspace.workspace_id}.cloud.databricks.com"

# ---------------------------------------------------------------------------
# REST API helpers for workspace provisioning
# (used when the installed SDK is too old to support compute_mode=SERVERLESS)
# ---------------------------------------------------------------------------

_ACCOUNT_HOST = "https://accounts.cloud.databricks.com"
_SSL_CTX = ssl.create_default_context()


def _oauth_token(account_id: str, client_id: str, client_secret: str) -> str:
    """Obtain an OAuth2 M2M access token from the Databricks account."""
    url  = f"{_ACCOUNT_HOST}/oidc/accounts/{account_id}/v1/token"
    cred = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "scope": "all-apis",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Basic {cred}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(req, context=_SSL_CTX) as resp:
        return json.loads(resp.read())["access_token"]


def _account_get(token: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{_ACCOUNT_HOST}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, context=_SSL_CTX) as resp:
        return json.loads(resp.read())


def _account_post(token: str, path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        f"{_ACCOUNT_HOST}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            detail = json.loads(body_bytes).get("message", body_bytes.decode())
        except Exception:
            detail = body_bytes.decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} {e.reason} — {detail}") from e


def _create_serverless_workspace_rest(
    account_id: str,
    client_id: str,
    client_secret: str,
    ws_name: str,
    region: str,
    timeout_s: int = 1200,
) -> tuple[int, str]:
    """Create a serverless workspace via REST API and wait until RUNNING.

    Returns (workspace_id, workspace_host).
    Used when the installed databricks-sdk is too old to support compute_mode.
    """
    token = _oauth_token(account_id, client_id, client_secret)

    ws_data = _account_post(token, f"/api/2.0/accounts/{account_id}/workspaces", {
        "workspace_name": ws_name,
        "aws_region":     region,
        "pricing_tier":   "ENTERPRISE",
        "compute_mode":   "SERVERLESS",
    })
    ws_id = ws_data["workspace_id"]
    print(f"  Workspace ID {ws_id} created — polling for RUNNING state…")

    deadline = time.time() + timeout_s
    poll = 30
    while time.time() < deadline:
        time.sleep(poll)
        data   = _account_get(token, f"/api/2.0/accounts/{account_id}/workspaces/{ws_id}")
        status = data.get("workspace_status", "UNKNOWN")
        msg    = data.get("workspace_status_message", "")
        print(f"  [{int(time.time() % 100000)}]  {status}  {msg}")
        if status == "RUNNING":
            deployment = data.get("deployment_name", "")
            host = (f"https://{deployment}.cloud.databricks.com"
                    if deployment else f"https://dbc-{ws_id}.cloud.databricks.com")
            return ws_id, host
        if status in ("FAILED", "BANNED", "CANCELLED"):
            raise RuntimeError(f"Workspace creation failed: {status} — {msg}")
        poll = min(poll + 10, 60)   # back off up to 60s between polls

    raise TimeoutError(f"Workspace did not reach RUNNING within {timeout_s // 60} minutes")


# ---------------------------------------------------------------------------
# Auth file writer
# ---------------------------------------------------------------------------

def _write_auth_file(
    env: str,
    account_id: str,
    client_id: str,
    client_secret: str,
    workspace_id: int,
    workspace_host: str,
) -> Path:
    """Write envs/<env>/auth.auto.tfvars with the provisioned credentials."""
    env_dir = ENVS_DIR / env
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / "data_access").mkdir(parents=True, exist_ok=True)

    content = f"""\
# Generated by provision_test_env.py — DO NOT EDIT MANUALLY.
# Run `python scripts/provision_test_env.py teardown` to clean up.
# This file is gitignored.

databricks_account_id    = "{account_id}"
databricks_client_id     = "{client_id}"
databricks_client_secret = "{client_secret}"
databricks_workspace_id  = "{workspace_id}"
databricks_workspace_host = "{workspace_host}"
"""
    auth_file = env_dir / "auth.auto.tfvars"
    auth_file.write_text(content)
    return auth_file

# ---------------------------------------------------------------------------
# Provision
# ---------------------------------------------------------------------------

def cmd_provision(cfg: dict[str, str], dry_run: bool = False, force: bool = False) -> None:
    _banner("Provision Fresh Integration-Test Environment")

    account_id    = cfg["DATABRICKS_ACCOUNT_ID"]
    client_id     = cfg["DATABRICKS_CLIENT_ID"]
    client_secret = cfg["DATABRICKS_CLIENT_SECRET"]
    region        = cfg["DATABRICKS_AWS_REGION"]

    # Derive the bucket name from the caller's AWS account ID.
    # The bucket is created automatically if it does not exist (Step 0).
    _ensure_boto3()
    _tmp_session    = _aws_session(cfg, region)
    _aws_account_id = _tmp_session.client("sts", region_name=region).get_caller_identity()["Account"]
    bucket_name     = f"genie-uc-test-{_aws_account_id}"
    ms_bucket_url   = f"s3://{bucket_name}"

    # Check if already provisioned
    existing = _load_state()
    if existing:
        if force:
            _warn("Existing environment found — tearing it down before re-provisioning (--force).")
            _warn(f"  Workspace:  {existing.get('workspace_name')} ({existing.get('workspace_id')})")
            _warn(f"  Metastore:  {existing.get('metastore_name')} ({existing.get('metastore_id')})")
            cmd_teardown(cfg)
        else:
            _warn("A provisioned environment already exists (found .test_env_state.json).")
            _warn(f"  Workspace:  {existing.get('workspace_name')} ({existing.get('workspace_id')})")
            _warn(f"  Metastore:  {existing.get('metastore_name')} ({existing.get('metastore_id')})")
            print("\n  Run `teardown` first, or use --force to replace it.", file=sys.stderr)
            sys.exit(1)

    run_id         = uuid.uuid4().hex[:10]
    ws_name        = f"genie-test-{run_id}"
    ms_name        = f"genie-test-ms-{run_id}"
    iam_role_name  = f"genie-test-uc-role-{run_id}"   # created + deleted by this script
    # Each run gets its own S3 prefix so catalog data is fully isolated.
    ext_loc_url    = f"{ms_bucket_url}/genie-test-{run_id}"

    print(f"\n  Run ID          : {run_id}")
    print(f"  Workspace       : {ws_name}")
    print(f"  Metastore       : {ms_name}")
    print(f"  Region          : {region}")
    print(f"  S3 bucket       : {bucket_name}  (auto-managed)")
    print(f"  External loc    : {ext_loc_url}")
    print(f"  IAM role        : {iam_role_name}  (will be created)")
    print(f"  SP (admin)      : {client_id}")

    if dry_run:
        print("\n  [DRY RUN] No resources will be created.")
        return

    # ------------------------------------------------------------------
    # Step 0: Ensure the S3 bucket exists (create it if not).
    # We track whether WE created it so teardown can clean up accordingly.
    # ------------------------------------------------------------------
    bucket_created = _ensure_s3_bucket(cfg, bucket_name, region)

    # ------------------------------------------------------------------
    # Ensure the SDK is new enough to support compute_mode=SERVERLESS.
    # CustomerFacingComputeMode was added in databricks-sdk 0.6x.
    # If it's missing, upgrade automatically (requires internet access).
    # ------------------------------------------------------------------
    _has_compute_mode = False
    try:
        from databricks.sdk.service.provisioning import CustomerFacingComputeMode
        _COMPUTE_MODE = CustomerFacingComputeMode.SERVERLESS
        _has_compute_mode = True
    except ImportError:
        pass

    if not _has_compute_mode:
        import importlib
        import subprocess as _sp
        _warn("databricks-sdk is too old (CustomerFacingComputeMode missing).")
        _warn("Upgrading automatically…  (pip install --upgrade databricks-sdk)")
        result = _sp.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "databricks-sdk"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            _err("Upgrade failed. Run manually:  pip install --upgrade databricks-sdk")
            _err(result.stderr[-1000:])
            sys.exit(1)
        # Reload the module so the upgraded version is used in this process.
        import databricks.sdk.service.provisioning as _prov_mod
        importlib.reload(_prov_mod)
        try:
            from databricks.sdk.service.provisioning import CustomerFacingComputeMode
            _COMPUTE_MODE = CustomerFacingComputeMode.SERVERLESS
            _has_compute_mode = True
            _ok("databricks-sdk upgraded successfully.")
        except ImportError:
            # Unlikely after a successful upgrade, but fall back to REST.
            _warn("Could not import CustomerFacingComputeMode even after upgrade.")
            _warn("Will use REST API fallback for workspace creation.")

    from databricks.sdk import AccountClient
    from databricks.sdk.service.provisioning import PricingTier
    from databricks.sdk.service.iam import WorkspacePermission, ComplexValue
    from databricks.sdk.service.catalog import (
        CreateAccountsMetastore,
        CreateAccountsStorageCredential,
        CreateMetastoreAssignment,
        UpdateAccountsMetastore,
        AwsIamRoleRequest,
    )

    a = AccountClient(
        host="https://accounts.cloud.databricks.com",
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
    )

    # ------------------------------------------------------------------
    # Step 1: Resolve the SP's SCIM ID
    # ------------------------------------------------------------------
    _step("Resolving Service Principal SCIM identity")
    sp_scim_id: int | None = None
    try:
        for sp in a.service_principals.list():
            if str(sp.application_id) == str(client_id):
                sp_scim_id = sp.id
                _ok(f"Found SP: display_name={sp.display_name!r}  scim_id={sp.id}  app_id={sp.application_id}")
                break
        if sp_scim_id is None:
            _warn("Could not find SP by client_id in account.")
    except Exception as exc:
        _warn(f"SP lookup failed: {exc}")

    # ------------------------------------------------------------------
    # Step 2: Create admin group and add SP as a member
    # ------------------------------------------------------------------
    group_name = f"genie-test-admins-{run_id}"
    _step(f"Creating admin group: {group_name}")
    group_id: str | None = None
    try:
        members = [ComplexValue(value=str(sp_scim_id))] if sp_scim_id else []
        grp = a.groups.create(display_name=group_name, members=members)
        group_id = grp.id
        _ok(f"Group created: id={group_id}  members={[m.value for m in (grp.members or [])]}")
    except Exception as exc:
        _warn(f"Could not create admin group: {exc}")
        _warn("Will fall back to assigning the SP directly.")

    # Shared mutable state dict — saved incrementally after each step so
    # that a crash mid-way still leaves enough info for teardown.
    state: dict = {
        "run_id":          run_id,
        "workspace_name":  ws_name,
        "workspace_id":    None,
        "workspace_host":  None,
        "metastore_name":  ms_name,
        "metastore_id":    None,
        "ext_loc_url":     ext_loc_url,
        "iam_role_name":   iam_role_name,   # deleted by teardown
        "bucket_name":     bucket_name,     # used by teardown for S3 cleanup
        "bucket_created":  bucket_created,  # if True, teardown deletes the bucket
        "ext_loc_prefix":  f"genie-test-{run_id}",  # S3 prefix to clean on teardown
        "region":          region,
        "account_id":        account_id,
        "sp_client_id":      client_id,
        "sp_scim_id":        sp_scim_id,
        "admin_group_name":  group_name,
        "admin_group_id":    group_id,
        "written_auth_envs": [],
        "provisioned_at":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # ------------------------------------------------------------------
    # Step 2: Create serverless workspace (fire and wait)
    # ------------------------------------------------------------------
    _step(f"Creating serverless workspace: {ws_name}")
    print("  (This typically takes 10-15 minutes — please wait…)")

    if _has_compute_mode:
        ws_obj = a.workspaces.create_and_wait(
            workspace_name=ws_name,
            aws_region=region,
            pricing_tier=PricingTier.ENTERPRISE,
            compute_mode=_COMPUTE_MODE,
        )
        ws_id   = ws_obj.workspace_id
        ws_host = _workspace_host(ws_obj)
    else:
        ws_id, ws_host = _create_serverless_workspace_rest(
            account_id, client_id, client_secret, ws_name, region
        )

    state["workspace_id"]   = ws_id
    state["workspace_host"] = ws_host
    _save_state(state)   # save now — workspace exists even if later steps fail
    _ok(f"Workspace ready: id={ws_id}  host={ws_host}")

    # ------------------------------------------------------------------
    # Step 3a: Create a fresh AWS IAM role for this test run.
    # The role is scoped to the test S3 prefix and will be deleted on teardown.
    # ------------------------------------------------------------------
    _step(f"Creating AWS IAM role: {iam_role_name}")
    iam_role_arn = _create_uc_iam_role(
        cfg=cfg,
        role_name=iam_role_name,
        bucket=bucket_name,
        account_id=account_id,
        region=region,
    )
    state["iam_role_name"] = iam_role_name   # ensure teardown can delete it
    _save_state(state)
    _ok(f"IAM role created: {iam_role_arn}")

    # ------------------------------------------------------------------
    # Step 3b: Create a fresh Unity Catalog metastore (no storage_root).
    # Storage is managed via an External Location (created in step 3d),
    # which is the recommended UC pattern — External Locations provide
    # fine-grained, path-scoped S3 access instead of a metastore-wide root.
    # ------------------------------------------------------------------
    _step(f"Creating Unity Catalog metastore: {ms_name}")
    ms_resp = a.metastores.create(
        metastore_info=CreateAccountsMetastore(
            name=ms_name,
            region=region,
            # No storage_root — catalogs will use an explicit External Location.
        )
    )
    ms_info = getattr(ms_resp, "metastore_info", None) or ms_resp
    ms_id   = ms_info.metastore_id
    state["metastore_id"] = ms_id
    _save_state(state)
    _ok(f"Metastore created: id={ms_id}")

    # ------------------------------------------------------------------
    # Step 3c: Register the IAM role as a storage credential in the new
    # metastore.  The Databricks API returns unity_catalog_iam_arn — the
    # specific ARN of the Databricks UC service role that will assume our
    # IAM role.  We then tighten the trust policy to use that exact ARN.
    # ------------------------------------------------------------------
    _step(f"Registering storage credential in metastore")
    storage_cred_id       = None
    unity_catalog_iam_arn = None
    try:
        new_cred_resp = a.storage_credentials.create(
            metastore_id=ms_id,
            credential_info=CreateAccountsStorageCredential(
                name="test-ext-loc-cred",
                aws_iam_role=AwsIamRoleRequest(role_arn=iam_role_arn),
                comment="Storage credential for test External Location — provision_test_env.py",
            ),
        )
        new_cred_info         = getattr(new_cred_resp, "credential_info", None) or new_cred_resp
        storage_cred_id       = new_cred_info.id
        # Extract the Databricks-side UC IAM ARN so we can narrow the trust policy.
        aws_iam_role_info     = getattr(new_cred_info, "aws_iam_role", None)
        unity_catalog_iam_arn = getattr(aws_iam_role_info, "unity_catalog_iam_arn", None)
        _ok(f"Storage credential registered: id={storage_cred_id!r}")
        if unity_catalog_iam_arn:
            _ok(f"Databricks UC principal  : {unity_catalog_iam_arn}")
    except Exception as exc:
        _warn(f"Could not register storage credential: {exc}")
        _warn("External location creation will fail.")

    # ------------------------------------------------------------------
    # Step 3d: Tighten the IAM trust policy now that we know the exact
    # Databricks UC principal ARN.  This is a security best practice —
    # the initial trust allows 414351767826:root; we narrow it to the
    # specific unity_catalog_iam_arn returned by the credential API.
    # ------------------------------------------------------------------
    if unity_catalog_iam_arn:
        _step("Updating IAM trust policy with Databricks UC principal")
        try:
            _update_uc_trust_policy(
                cfg=cfg,
                role_name=iam_role_name,
                role_arn=iam_role_arn,
                unity_catalog_iam_arn=unity_catalog_iam_arn,
                account_id=account_id,
                region=region,
            )
            _ok("Trust policy updated")
            # AWS IAM is eventually consistent — wait for the updated trust
            # policy (including the self-assume statement) to propagate before
            # Databricks validates it when creating the External Location.
            # 15 s is often too short; use 60 s to avoid transient failures.
            _warn("Waiting 60 s for trust policy propagation…")
            time.sleep(60)
        except Exception as exc:
            _warn(f"Could not update trust policy: {exc}")
            _warn("Storage credential may not work. Update the trust policy manually in AWS IAM.")

    # ------------------------------------------------------------------
    # Step 4: Assign metastore to workspace
    # ------------------------------------------------------------------
    _step("Assigning metastore to workspace")
    a.metastore_assignments.create(
        workspace_id=ws_id,
        metastore_id=ms_id,
        metastore_assignment=CreateMetastoreAssignment(
            workspace_id=ws_id,
            metastore_id=ms_id,
            default_catalog_name="main",
        ),
    )
    _ok("Metastore assigned to workspace")

    # ------------------------------------------------------------------
    # Step 5: Create the External Location BEFORE transferring metastore
    # ownership.  The SP is still the metastore creator at this point and
    # therefore has full metastore admin rights.  After ownership is
    # transferred to the admin group the SP loses implicit admin and would
    # receive "User does not have CREATE EXTERNAL LOCATION" errors.
    #
    # Trailing slash on the URL is required so Databricks prefix-matches
    # sub-paths like s3://bucket/prefix/catalog_name as being covered by
    # this location.
    # ------------------------------------------------------------------
    if storage_cred_id:
        ext_loc_url_with_slash = ext_loc_url.rstrip("/") + "/"
        _step(f"Creating External Location: {ext_loc_url_with_slash}")
        # Retry with back-off because IAM trust-policy propagation is eventually
        # consistent.  The first attempt occasionally fails with "Bucket X does not
        # exist" even though the bucket is reachable — this is Databricks signalling
        # that it could not assume the IAM role yet.  A short retry resolves it.
        el_created = False
        for _attempt, _delay in enumerate([0, 30, 60]):
            if _delay:
                _warn(f"  Retrying External Location creation in {_delay} s (attempt {_attempt + 1})…")
                time.sleep(_delay)
            try:
                from databricks.sdk import WorkspaceClient as _WC
                w_new = _WC(host=ws_host, client_id=client_id, client_secret=client_secret)
                el = w_new.external_locations.create(
                    name="test-external-location",
                    url=ext_loc_url_with_slash,
                    credential_name="test-ext-loc-cred",
                    comment="Test External Location — provision_test_env.py",
                )
                _ok(f"External Location created: {el.url}")
                el_created = True
                # The SP (metastore creator) has implicit admin rights on the
                # external location it created — no explicit grant needed.
                break
            except Exception as exc:
                _warn(f"Could not create External Location (attempt {_attempt + 1}): {exc}")
        if not el_created:
            _warn("Catalog creation will require an explicit MANAGED LOCATION.")

    # Note: we intentionally do NOT transfer metastore ownership to the admin
    # group here.  The SP (account admin and metastore creator) retains its
    # implicit metastore admin status, which grants CREATE CATALOG and all
    # other UC privileges needed for the integration tests.  Transferring
    # ownership would strip those rights and cause catalog creation to fail.

    # ------------------------------------------------------------------
    # Step 7: Set admin group AND SP directly as workspace admins.
    # workspace_assignment.update takes a numeric SCIM principal_id.
    #
    # We assign BOTH:
    #   • the admin group  — inheritable permissions for future members
    #   • the SP directly  — ensures OAuth M2M works immediately without
    #                        waiting for SCIM group-membership sync to propagate
    # ------------------------------------------------------------------
    principals_to_assign: list[tuple[int, str]] = []
    if group_id:
        principals_to_assign.append((int(group_id), f"group {group_name!r}"))
    if sp_scim_id:
        principals_to_assign.append((sp_scim_id, f"SP (scim_id={sp_scim_id})"))

    if principals_to_assign:
        for principal_id, label in principals_to_assign:
            _step(f"Adding {label} as workspace admin")
            try:
                a.workspace_assignment.update(
                    workspace_id=ws_id,
                    principal_id=principal_id,
                    permissions=[WorkspacePermission.ADMIN],
                )
                _ok(f"Workspace admin granted to {label}")
            except Exception as exc:
                _warn(f"Could not assign workspace admin to {label}: {exc}")
    else:
        _warn("Skipping workspace admin assignment (no group or SP SCIM ID available).")
        _warn("Add the admin group as workspace admin manually in the Workspace Settings.")

    # Allow the workspace identity system to propagate the new assignments
    # before anything tries to authenticate via OAuth M2M.
    _warn("Waiting 20 s for workspace identity propagation…")
    time.sleep(20)

    # ------------------------------------------------------------------
    # Step 7: Write auth.auto.tfvars into the isolated envs/test/ directory
    #         so user's real envs/dev/ is never touched.
    # ------------------------------------------------------------------
    _step(f"Writing auth.auto.tfvars into {TEST_ENVS_DIR.relative_to(MODULE_ROOT)}/")
    written_envs = []
    for env in ["dev", "bu2", "prod"]:
        env_dir = TEST_ENVS_DIR / env
        env_dir.mkdir(parents=True, exist_ok=True)
        (TEST_ENVS_DIR / env / "data_access").mkdir(parents=True, exist_ok=True)
        content = (
            f'# Generated by provision_test_env.py — DO NOT EDIT MANUALLY.\n'
            f'# Run `python scripts/provision_test_env.py teardown` to clean up.\n'
            f'databricks_account_id     = "{account_id}"\n'
            f'databricks_client_id      = "{client_id}"\n'
            f'databricks_client_secret  = "{client_secret}"\n'
            f'databricks_workspace_id   = "{ws_id}"\n'
            f'databricks_workspace_host = "{ws_host}"\n'
            f'# Base S3 prefix for catalog managed storage (External Location).\n'
            f'# Each catalog gets its own subfolder: {{catalog_storage_base}}/{{catalog_name}}/\n'
            f'catalog_storage_base      = "{ext_loc_url}"\n'
        )
        auth_path = env_dir / "auth.auto.tfvars"
        auth_path.write_text(content)
        written_envs.append(str(auth_path))
        _ok(f"Wrote {auth_path.relative_to(MODULE_ROOT)}")

    acct_dir = TEST_ENVS_DIR / "account"
    acct_dir.mkdir(parents=True, exist_ok=True)
    (acct_dir / "auth.auto.tfvars").write_text(
        f'# Generated by provision_test_env.py\n'
        f'databricks_account_id    = "{account_id}"\n'
        f'databricks_client_id     = "{client_id}"\n'
        f'databricks_client_secret = "{client_secret}"\n'
        f'databricks_workspace_id  = "{ws_id}"\n'
        f'databricks_workspace_host = "{ws_host}"\n'
    )
    _ok(f"Wrote {(acct_dir / 'auth.auto.tfvars').relative_to(MODULE_ROOT)}")

    state["written_auth_envs"] = written_envs
    state["test_envs_dir"] = str(TEST_ENVS_DIR)
    _save_state(state)
    _ok(f"State saved to {STATE_FILE.relative_to(MODULE_ROOT)}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    _banner("Environment Ready")
    print(f"\n  Workspace      : {ws_host}")
    print(f"  Workspace ID   : {ws_id}")
    print(f"  Metastore      : {ms_name}  ({ms_id})")
    print(f"  External loc   : {ext_loc_url}")
    print(f"  Admin group    : {group_name}  ({group_id})")
    print(f"  Config dir     : envs/test/  (your real envs/dev/ is untouched)")
    print()
    print("  Next steps:")
    print()
    print(f"    python scripts/run_integration_tests.py")
    print()
    print("  To tear down when finished:")
    print("    python scripts/provision_test_env.py teardown")
    print()


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

def cmd_teardown(dry_run: bool = False) -> None:
    _banner("Tear Down Integration-Test Environment")

    state = _load_state()
    if not state:
        _warn("No provisioned environment found (state file missing).")
        _warn("Nothing to tear down.")
        return

    ws_id  = state["workspace_id"]
    ms_id  = state["metastore_id"]
    ws_name = state["workspace_name"]
    ms_name = state["metastore_name"]
    account_id    = state["account_id"]
    client_id     = state["sp_client_id"]

    print(f"\n  Workspace  : {ws_name} ({ws_id})")
    print(f"  Metastore  : {ms_name} ({ms_id})")
    print(f"  Provisioned: {state.get('provisioned_at', 'unknown')}")

    if dry_run:
        print("\n  [DRY RUN] No resources will be deleted.")
        return

    # Load secrets from env file with os.environ overrides.
    # Using _load_config (not _load_env_file) so that freshly-exported AWS
    # credentials in the shell (e.g. a renewed AWS_SESSION_TOKEN) take
    # priority over stale values stored in the file.  This matters for
    # long test runs where temporary STS tokens can expire before teardown.
    env_file = DEFAULT_ENV_FILE
    env_cfg  = _load_config(env_file)
    client_secret = (
        os.environ.get("DATABRICKS_CLIENT_SECRET")
        or env_cfg.get("DATABRICKS_CLIENT_SECRET")
        or ""
    )
    if not client_secret:
        _err("DATABRICKS_CLIENT_SECRET not found in env file or environment.")
        _err(f"  Set it in {env_file} or export DATABRICKS_CLIENT_SECRET=...")
        sys.exit(1)

    from databricks.sdk import AccountClient

    a = AccountClient(
        host="https://accounts.cloud.databricks.com",
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
    )

    # ------------------------------------------------------------------
    # Step 0: Delete the AWS IAM role (created by provision, no longer needed)
    # ------------------------------------------------------------------
    iam_role_name = state.get("iam_role_name")
    region        = state.get("region", "us-east-1")
    if iam_role_name:
        _step(f"Deleting AWS IAM role: {iam_role_name}")
        try:
            # Reload AWS credentials from the env file for teardown.
            _delete_iam_role(env_cfg, iam_role_name, region)
            _ok(f"IAM role deleted: {iam_role_name}")
        except Exception as exc:
            _warn(f"Could not delete IAM role {iam_role_name!r}: {exc}")
            if "ExpiredToken" in str(exc) or "expired" in str(exc).lower():
                _warn("Your AWS session token has expired.  To retry with fresh credentials:")
                _warn("  1. Export new tokens:  AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...")
                _warn("  2. Re-run teardown:    python scripts/provision_test_env.py teardown")
                _warn("  Or delete manually:   AWS Console → IAM → Roles → search for the name above.")
            else:
                _warn("Delete it manually in the AWS console: IAM → Roles → search for the name above.")
    else:
        _step("No IAM role in state — skipping IAM deletion")

    # ------------------------------------------------------------------
    # Step 0b: S3 cleanup
    #  • Always remove objects under the test prefix (good housekeeping).
    #  • If we created the bucket, also delete it entirely.
    # ------------------------------------------------------------------
    bucket_name    = state.get("bucket_name")
    bucket_created = state.get("bucket_created", False)
    ext_loc_prefix = state.get("ext_loc_prefix", "")
    region         = state.get("region", "us-east-1")
    if bucket_name and ext_loc_prefix:
        try:
            _delete_s3_prefix(env_cfg, bucket_name, ext_loc_prefix, region)
        except Exception as exc:
            _warn(f"Could not clean S3 prefix: {exc}")
    if bucket_name and bucket_created:
        _step(f"Deleting S3 bucket created by provision: s3://{bucket_name}")
        try:
            _delete_s3_bucket(env_cfg, bucket_name, region)
        except Exception as exc:
            _warn(f"Could not delete S3 bucket: {exc}")
            _warn(f"Delete it manually: aws s3 rb s3://{bucket_name} --force")
    elif bucket_name:
        _ok(f"Bucket s3://{bucket_name} was pre-existing — not deleted.")

    # ------------------------------------------------------------------
    # Step 1: Unassign metastore from workspace (required before deletion)
    # ------------------------------------------------------------------
    _step("Unassigning metastore from workspace")
    try:
        a.metastore_assignments.delete(workspace_id=ws_id, metastore_id=ms_id)
        _ok("Metastore unassigned")
    except Exception as exc:
        _warn(f"Could not unassign metastore (may already be unassigned): {exc}")

    # ------------------------------------------------------------------
    # Step 2: Delete metastore (force=True deletes all catalogs + policies)
    # ------------------------------------------------------------------
    _step(f"Deleting metastore: {ms_name}")
    try:
        a.metastores.delete(metastore_id=ms_id, force=True)
        _ok(f"Metastore deleted (all catalogs, schemas, policies removed)")
    except Exception as exc:
        _warn(f"Could not delete metastore: {exc}")
        _warn("You may need to delete it manually in the Account Console.")

    # ------------------------------------------------------------------
    # Step 3: Delete admin group
    # ------------------------------------------------------------------
    group_id   = state.get("admin_group_id")
    group_name = state.get("admin_group_name", "")
    if group_id:
        _step(f"Deleting admin group: {group_name}")
        try:
            a.groups.delete(id=group_id)
            _ok(f"Admin group deleted ({group_name})")
        except Exception as exc:
            _warn(f"Could not delete admin group: {exc}")
    else:
        _step("No admin group in state — skipping group deletion")

    # ------------------------------------------------------------------
    # Step 4: Delete workspace
    # ------------------------------------------------------------------
    _step(f"Deleting workspace: {ws_name}")
    try:
        a.workspaces.delete(workspace_id=int(ws_id))
        _ok(f"Workspace deleted")
    except Exception as exc:
        _warn(f"Could not delete workspace: {exc}")
        _warn("You may need to delete it manually in the Account Console.")

    # ------------------------------------------------------------------
    # Step 5: Remove the entire envs/test/ directory
    # ------------------------------------------------------------------
    _step("Removing envs/test/ directory")
    test_envs = Path(state.get("test_envs_dir", str(TEST_ENVS_DIR)))
    if test_envs.exists():
        import shutil as _shutil
        _shutil.rmtree(test_envs)
        _ok(f"Removed {test_envs.relative_to(MODULE_ROOT)}")

    # ------------------------------------------------------------------
    # Step 6: Clear state
    # ------------------------------------------------------------------
    _clear_state()
    _ok("State file cleared")

    _banner("Teardown Complete")
    print("\n  The IAM role, workspace, metastore, and admin group have been deleted.")
    if bucket_created:
        print(f"  S3 bucket s3://{bucket_name} was created by provision and has been deleted.")
    elif bucket_name:
        print(f"  S3 test prefix cleaned; bucket s3://{bucket_name} (pre-existing) was not deleted.")
    print("  Run `provision` to create a fresh environment for the next test run.")
    print()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def cmd_status() -> None:
    _banner("Integration-Test Environment Status")
    state = _load_state()
    if not state:
        print("\n  No provisioned environment (state file not found).")
        print(f"\n  Run `python scripts/provision_test_env.py provision` to create one.")
        return

    print(f"\n  Run ID       : {state.get('run_id')}")
    print(f"  Provisioned  : {state.get('provisioned_at', 'unknown')}")
    print()
    print(f"  Workspace")
    print(f"    Name       : {state.get('workspace_name')}")
    print(f"    ID         : {state.get('workspace_id')}")
    print(f"    Host       : {state.get('workspace_host')}")
    print()
    print(f"  Metastore")
    print(f"    Name       : {state.get('metastore_name')}")
    print(f"    ID         : {state.get('metastore_id')}")
    print(f"    Storage    : {state.get('metastore_storage')}")
    print()
    print(f"  Admin group  : {state.get('admin_group_name')}  ({state.get('admin_group_id')})")
    print(f"  SP (member)  : {state.get('sp_client_id')}")
    print(f"  Config dir   : {state.get('test_envs_dir', 'envs/test/')}")
    print()
    print("  Run the tests:")
    print(f"    python scripts/run_integration_tests.py")
    print()
    print("  Tear down:")
    print("    python scripts/provision_test_env.py teardown")
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision / tear down a fresh Databricks integration-test environment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "command",
        choices=["provision", "teardown", "status"],
        help="Action to perform",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        metavar="PATH",
        help=f"Path to account-admin credentials env file (default: {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without creating/deleting any resources",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With provision: overwrite an existing provisioned environment",
    )
    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
        return

    if args.command == "teardown":
        cmd_teardown(dry_run=args.dry_run)
        return

    # provision
    cfg = _load_config(Path(args.env_file))
    _validate_config(cfg)
    cmd_provision(cfg, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
