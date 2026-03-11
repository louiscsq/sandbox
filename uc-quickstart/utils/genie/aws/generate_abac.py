#!/usr/bin/env python3
"""
Generate ABAC masking_functions.sql and abac.auto.tfvars from table DDL files.

Reads DDL files from a folder (or fetches them live from Databricks),
combines them with the ABAC prompt template, sends to an LLM, and writes
the generated output files.  Optionally runs validate_abac.py on the result.

Authentication:
  The script reads auth.auto.tfvars for Databricks credentials and
  env.auto.tfvars for uc_catalog + uc_tables and environment config.  Catalog/schema
  for UDF deployment are auto-derived from uc_catalog (or the first table in uc_tables)
  (override with --catalog / --schema).

Supported LLM providers:
  - databricks (default) — Claude Sonnet via Databricks Foundation Model API
  - anthropic            — Claude via the Anthropic API
  - openai               — GPT-4o / o1 via OpenAI API

Usage:
  # One-time setup
  cp auth.auto.tfvars.example auth.auto.tfvars   # credentials (gitignored)
  cp env.auto.tfvars.example env.auto.tfvars     # tables + environment (checked in)
  # Edit env.auto.tfvars:
  #   uc_catalog = "prod_catalog"
  #   uc_tables  = ["sales.customers", "sales.orders", "finance.*"]

  # Generate (reads uc_catalog + uc_tables from env config; catalog/schema auto-derived)
  python generate_abac.py

  # Or override tables via CLI
  python generate_abac.py --tables prod.sales.customers prod.sales.orders

  # Use a specific provider / model
  python generate_abac.py --provider anthropic --model claude-sonnet-4-20250514

  # Fall back to local DDL files (legacy — requires --catalog / --schema)
  cp my_tables.sql ddl/
  python generate_abac.py --catalog my_catalog --schema my_schema
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

PRODUCT_NAME = "genierails"
PRODUCT_VERSION = "0.1.0"

SCRIPT_DIR = Path(__file__).resolve().parent
WORK_DIR = Path.cwd()
PROMPT_TEMPLATE_PATH = SCRIPT_DIR / "ABAC_PROMPT.md"
DEFAULT_AUTH_FILE = WORK_DIR / "auth.auto.tfvars"
DEFAULT_ENV_FILE = WORK_DIR / "env.auto.tfvars"

REQUIRED_PACKAGES = {
    "python-hcl2": "hcl2",
    "databricks-sdk": "databricks.sdk",
}


def _ensure_packages():
    """Auto-install required packages if missing."""
    missing = []
    for pip_name, import_name in REQUIRED_PACKAGES.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print(f"  Installing missing packages: {', '.join(missing)}...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", *missing],
        )
    try:
        __import__("databricks.sdk.useragent")
    except (ImportError, ModuleNotFoundError):
        print("  Upgrading databricks-sdk (need databricks.sdk.useragent)...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "databricks-sdk"],
        )


_ensure_packages()


def _load_tfvars(path: Path, label: str) -> dict:
    """Load a single .tfvars file. Returns empty dict if not found."""
    if not path.exists():
        return {}
    import hcl2
    try:
        with open(path) as f:
            cfg = hcl2.load(f)
        non_empty = {k: v for k, v in cfg.items() if v}
        if non_empty:
            print(f"  Loaded {label} from: {path}")
        return cfg
    except Exception as e:
        print(f"  WARNING: Failed to parse {path}: {e}")
        return {}


def load_auth_config(auth_file: Path, env_file: Path | None = None) -> dict:
    """Load config from auth + env tfvars files. Merges both; env overrides auth.

    Supports the new split format (uc_catalog + schema-relative uc_tables) as well as
    the legacy full-ref format (uc_tables = ["catalog.schema.table"]).  When uc_catalog
    is set, relative uc_tables entries are expanded into full 3-part refs before being
    returned so the rest of the script does not need to know about the split.
    """
    cfg = _load_tfvars(auth_file, "credentials")
    if env_file is None:
        env_file = auth_file.parent / "env.auto.tfvars"
    env_cfg = _load_tfvars(env_file, "environment")
    cfg.update(env_cfg)

    # Combine uc_catalog + relative uc_tables into full 3-part refs when the new
    # split format is used.  The --tables CLI flag always passes full refs directly
    # and bypasses this function, so only config-file values need expansion here.
    uc_catalog = cfg.get("uc_catalog", "")
    uc_tables = cfg.get("uc_tables", [])
    if uc_catalog and uc_tables:
        cfg["uc_tables"] = [f"{uc_catalog}.{t}" for t in uc_tables]

    if "uc_tables" in cfg and cfg["uc_tables"]:
        print(f"    uc_tables: {', '.join(cfg['uc_tables'])}")
    return cfg


def configure_databricks_env(auth_cfg: dict):
    """Set Databricks SDK env vars from auth config if not already set."""
    mapping = {
        "databricks_workspace_host": "DATABRICKS_HOST",
        "databricks_client_id": "DATABRICKS_CLIENT_ID",
        "databricks_client_secret": "DATABRICKS_CLIENT_SECRET",
    }
    for tfvar_key, env_key in mapping.items():
        val = auth_cfg.get(tfvar_key, "")
        if val and not os.environ.get(env_key):
            os.environ[env_key] = val


def load_ddl_files(ddl_dir: Path) -> str:
    """Read all .sql files from ddl_dir and concatenate them."""
    sql_files = sorted(ddl_dir.glob("*.sql"))
    if not sql_files:
        print(f"ERROR: No .sql files found in {ddl_dir}")
        print("  Place your CREATE TABLE / DESCRIBE TABLE DDL in .sql files there.")
        sys.exit(1)

    parts = []
    for f in sql_files:
        content = f.read_text().strip()
        if content:
            parts.append(f"-- Source: {f.name}\n{content}")
            print(f"  Loaded DDL: {f.name} ({len(content)} chars)")

    combined = "\n\n".join(parts)
    print(f"  Total DDL: {len(combined)} chars from {len(sql_files)} file(s)\n")
    return combined


def _parse_table_ref(ref: str) -> tuple[str, str, str]:
    """Parse 'catalog.schema.table' or 'catalog.schema.*' into parts."""
    parts = ref.split(".")
    if len(parts) != 3:
        print(f"ERROR: Invalid table reference '{ref}'")
        print("  Expected format: catalog.schema.table or catalog.schema.*")
        sys.exit(1)
    return parts[0], parts[1], parts[2]


def format_table_info(table_info) -> str:
    """Format a TableInfo object into CREATE TABLE DDL text."""
    full_name = table_info.full_name
    lines = [f"-- Table: {full_name}"]
    lines.append(f"CREATE TABLE {full_name} (")
    if table_info.columns:
        col_parts = []
        for col in table_info.columns:
            type_text = col.type_text or "STRING"
            part = f"  {col.name} {type_text}"
            if col.comment:
                safe = col.comment.replace("'", "''")
                part += f" COMMENT '{safe}'"
            col_parts.append(part)
        lines.append(",\n".join(col_parts))
    lines.append(");")
    if table_info.comment:
        lines.append(f"-- Table comment: {table_info.comment}")
    return "\n".join(lines)


def _parse_str_field(val) -> str:
    """Safely extract the first string from a list-or-string field in serialized_space."""
    if isinstance(val, list):
        return val[0] if val else ""
    return val or ""


def parse_genie_config_from_serialized_space(serialized: str, description: str = "") -> dict:
    """Parse a Genie Space's serialized_space JSON into a genie_space_configs dict.

    Returns a dict with keys: description, instructions, sample_questions,
    benchmarks, sql_filters, sql_expressions, sql_measures, join_specs.
    Only includes keys that have non-empty values.
    """
    import json as _json

    try:
        space_data = _json.loads(serialized)
    except Exception:
        return {}

    config: dict = {}

    if description:
        config["description"] = description

    # Instructions (free-text)
    text_instrs = space_data.get("instructions", {}).get("text_instructions", [])
    if text_instrs:
        content = _parse_str_field(text_instrs[0].get("content", ""))
        if content:
            config["instructions"] = content

    # Sample questions
    sq_items = space_data.get("config", {}).get("sample_questions", [])
    questions = [_parse_str_field(item.get("question", "")) for item in sq_items]
    questions = [q for q in questions if q]
    if questions:
        config["sample_questions"] = questions

    # Benchmarks
    bm_items = space_data.get("benchmarks", {}).get("questions", [])
    benchmarks = []
    for bm in bm_items:
        question = _parse_str_field(bm.get("question", ""))
        sql = ""
        for ans in bm.get("answer", []):
            if ans.get("format") == "SQL":
                sql = _parse_str_field(ans.get("content", ""))
                break
        if question and sql:
            benchmarks.append({"question": question, "sql": sql})
    if benchmarks:
        config["benchmarks"] = benchmarks

    snippets = space_data.get("instructions", {}).get("sql_snippets", {})

    # SQL filters
    filters = [
        {"sql": _parse_str_field(f.get("sql", "")), "display_name": f.get("display_name", "")}
        for f in snippets.get("filters", [])
        if _parse_str_field(f.get("sql", ""))
    ]
    if filters:
        config["sql_filters"] = filters

    # SQL expressions
    exprs = [
        {"alias": e.get("alias", ""), "sql": _parse_str_field(e.get("sql", ""))}
        for e in snippets.get("expressions", [])
        if _parse_str_field(e.get("sql", ""))
    ]
    if exprs:
        config["sql_expressions"] = exprs

    # SQL measures
    measures = [
        {"alias": m.get("alias", ""), "sql": _parse_str_field(m.get("sql", ""))}
        for m in snippets.get("measures", [])
        if _parse_str_field(m.get("sql", ""))
    ]
    if measures:
        config["sql_measures"] = measures

    # Join specs
    joins = [
        {
            "left_table": j.get("left", {}).get("identifier", ""),
            "right_table": j.get("right", {}).get("identifier", ""),
            "sql": _parse_str_field(j.get("sql", "")),
        }
        for j in space_data.get("instructions", {}).get("join_specs", [])
        if _parse_str_field(j.get("sql", ""))
    ]
    if joins:
        config["join_specs"] = joins

    return config


def _hcl_str(s: str) -> str:
    """Format a Python string as an HCL quoted string literal."""
    escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("${", "$${")
    return f'"{escaped}"'


def format_genie_space_configs_hcl(configs: dict[str, dict]) -> str:
    """Convert a dict of {space_key: config_dict} to the genie_space_configs HCL block.

    The space_key is the human-readable name used as the map key in abac.auto.tfvars.
    """
    lines = ["genie_space_configs = {"]

    for space_name, cfg in configs.items():
        lines.append(f"  {_hcl_str(space_name)} = {{")

        if cfg.get("description"):
            lines.append(f"    description = {_hcl_str(cfg['description'])}")

        if cfg.get("instructions"):
            lines.append(f"    instructions = {_hcl_str(cfg['instructions'])}")

        if cfg.get("sample_questions"):
            lines.append("    sample_questions = [")
            for q in cfg["sample_questions"]:
                lines.append(f"      {_hcl_str(q)},")
            lines.append("    ]")

        if cfg.get("benchmarks"):
            lines.append("    benchmarks = [")
            for bm in cfg["benchmarks"]:
                lines.append("      {")
                lines.append(f"        question = {_hcl_str(bm['question'])}")
                lines.append(f"        sql      = {_hcl_str(bm['sql'])}")
                lines.append("      },")
            lines.append("    ]")

        if cfg.get("sql_filters"):
            lines.append("    sql_filters = [")
            for f in cfg["sql_filters"]:
                lines.append("      {")
                lines.append(f"        sql          = {_hcl_str(f['sql'])}")
                lines.append(f"        display_name = {_hcl_str(f.get('display_name', ''))}")
                lines.append("      },")
            lines.append("    ]")

        if cfg.get("sql_expressions"):
            lines.append("    sql_expressions = [")
            for e in cfg["sql_expressions"]:
                lines.append("      {")
                lines.append(f"        alias = {_hcl_str(e['alias'])}")
                lines.append(f"        sql   = {_hcl_str(e['sql'])}")
                lines.append("      },")
            lines.append("    ]")

        if cfg.get("sql_measures"):
            lines.append("    sql_measures = [")
            for m in cfg["sql_measures"]:
                lines.append("      {")
                lines.append(f"        alias = {_hcl_str(m['alias'])}")
                lines.append(f"        sql   = {_hcl_str(m['sql'])}")
                lines.append("      },")
            lines.append("    ]")

        if cfg.get("join_specs"):
            lines.append("    join_specs = [")
            for j in cfg["join_specs"]:
                lines.append("      {")
                lines.append(f"        left_table  = {_hcl_str(j['left_table'])}")
                lines.append(f"        right_table = {_hcl_str(j['right_table'])}")
                lines.append(f"        sql         = {_hcl_str(j['sql'])}")
                lines.append("      },")
            lines.append("    ]")

        lines.append("  }")

    lines.append("}")
    return "\n".join(lines)


def remove_hcl_top_level_block(text: str, key: str) -> str:
    """Remove a top-level HCL assignment block 'key = { ... }' from text.

    Uses brace counting to correctly handle nested objects.
    """
    import re as _re

    pattern = _re.compile(rf"^{_re.escape(key)}\s*=\s*\{{", _re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return text

    start = m.start()
    depth = 0
    end = m.end() - 1  # position of the opening {

    for i in range(m.end() - 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    # Strip one surrounding newline to avoid double blank lines
    block_end = end + 1
    if block_end < len(text) and text[block_end] == "\n":
        block_end += 1

    return text[:start] + text[block_end:]


def fetch_tables_from_genie_space(space_id: str, auth_cfg: dict) -> tuple[list[str], dict, str]:
    """Fetch tables and config from an existing Genie Space via the REST API.

    Returns (table_identifiers, genie_config_dict, space_title).
    Uses GET /api/2.0/genie/spaces/{space_id} and parses serialized_space.

    Retries up to 5 times with backoff when serialized_space is empty —
    Databricks may process it asynchronously immediately after creation.
    """
    import json as _json
    import time as _time

    from databricks.sdk import WorkspaceClient

    configure_databricks_env(auth_cfg)
    w = WorkspaceClient(product=PRODUCT_NAME, product_version=PRODUCT_VERSION)

    print(f"  Querying Genie Space {space_id}...")
    try:
        resp = w.api_client.do("GET", f"/api/2.0/genie/spaces/{space_id}")
    except Exception as e:
        print(f"  WARNING: Could not reach Genie Space {space_id}: {e}")
        return [], {}, ""

    if not isinstance(resp, dict):
        print(f"  WARNING: Unexpected response type from Genie Space {space_id}.")
        return [], {}, ""

    space_title = resp.get("title", "")
    description = resp.get("description", "")
    serialized = resp.get("serialized_space", "")

    # Genie Spaces may take 1-3 minutes after creation before serialized_space
    # is populated by the Databricks backend (async processing).
    # Retry with increasing backoff — total budget ~4 minutes.
    if not serialized:
        retry_delays = [5, 10, 20, 30, 45, 60, 90]
        for attempt, delay in enumerate(retry_delays, start=1):
            print(f"  Genie Space {space_id} has no serialized_space yet — "
                  f"retrying in {delay}s (attempt {attempt}/{len(retry_delays)})...")
            _time.sleep(delay)
            try:
                resp = w.api_client.do("GET", f"/api/2.0/genie/spaces/{space_id}")
                space_title = resp.get("title", space_title)
                description = resp.get("description", description)
                serialized = resp.get("serialized_space", "")
            except Exception as e:
                print(f"  WARNING: Retry failed: {e}")
            if serialized:
                break

    if not serialized:
        print(f"  WARNING: Genie Space {space_id} returned no serialized_space after retries.")
        return [], {}, space_title

    # --- Tables ---
    try:
        space_data = _json.loads(serialized)
        tables = space_data.get("data_sources", {}).get("tables", [])
        identifiers = [t["identifier"] for t in tables if "identifier" in t]
    except Exception as e:
        print(f"  WARNING: Could not parse table list from Genie Space {space_id}: {e}")
        identifiers = []

    if identifiers:
        print(f"    Discovered {len(identifiers)} table(s): {', '.join(identifiers)}")
    else:
        print(f"  WARNING: Genie Space {space_id} has no tables configured yet.")

    # --- Config ---
    genie_config = parse_genie_config_from_serialized_space(serialized, description=description)
    n_benchmarks = len(genie_config.get("benchmarks", []))
    n_filters = len(genie_config.get("sql_filters", []))
    n_measures = len(genie_config.get("sql_measures", []))
    print(
        f"    Parsed config: {n_benchmarks} benchmark(s), "
        f"{n_filters} filter(s), {n_measures} measure(s)"
    )

    return identifiers, genie_config, space_title


def fetch_tables_from_databricks(
    table_refs: list[str],
    auth_cfg: dict,
) -> tuple[str, list[tuple[str, str]]]:
    """Fetch table DDLs from Databricks using the SDK.

    Returns (ddl_text, catalog_schema_pairs) where catalog_schema_pairs
    is a deduplicated list of (catalog, schema) tuples found.
    """
    from databricks.sdk import WorkspaceClient

    configure_databricks_env(auth_cfg)
    w = WorkspaceClient(product=PRODUCT_NAME, product_version=PRODUCT_VERSION)

    tables = []
    for ref in table_refs:
        catalog, schema, table = _parse_table_ref(ref)
        if table == "*":
            print(f"  Listing tables in {catalog}.{schema}...")
            for t in w.tables.list(
                catalog_name=catalog, schema_name=schema
            ):
                tables.append(t)
                print(f"    Found: {t.full_name}")
        else:
            full_name = f"{catalog}.{schema}.{table}"
            print(f"  Fetching: {full_name}...")
            t = w.tables.get(full_name=full_name)
            tables.append(t)

    if not tables:
        print("ERROR: No tables found for the given references.")
        sys.exit(1)

    seen_pairs: dict[tuple[str, str], list[str]] = {}
    parts = []
    for t in tables:
        parts.append(format_table_info(t))
        cat = t.catalog_name
        sch = t.schema_name
        pair = (cat, sch)
        seen_pairs.setdefault(pair, []).append(t.name)

    ddl_text = "\n\n".join(parts)
    catalog_schemas = list(seen_pairs.keys())

    print(
        f"  Fetched {len(tables)} table(s) from "
        f"{len(catalog_schemas)} catalog.schema pair(s)\n"
    )
    return ddl_text, catalog_schemas


def build_prompt(ddl_text: str,
                 catalog_schemas: list[tuple[str, str]] | None = None,
                 group_names: list[str] | None = None,
                 per_space_name: str | None = None,
                 space_names: list[str] | None = None) -> str:
    """Build the full prompt by injecting DDL and optional group names into the template.

    When per_space_name is set, an extra instruction is injected telling the LLM
    to generate ONLY config for that specific space (skip groups and tag_policies,
    which are shared state established by full generation).

    When space_names is set, the LLM is told to use exactly those names as the
    keys in genie_space_configs — preventing it from inventing its own titles.
    """
    template = PROMPT_TEMPLATE_PATH.read_text()

    section_marker = "### MY TABLES"
    idx = template.find(section_marker)

    cs_lines = ""
    if catalog_schemas:
        cs_lines = "Tables span these catalog.schema pairs:\n"
        for cat, sch in catalog_schemas:
            cs_lines += f"  - {cat}.{sch}\n"
        cs_lines += (
            "\nFor each fgac_policy, set catalog, function_catalog, and function_schema "
            "to match the catalog.schema of the tables the policy applies to.\n"
        )

    groups_lines = ""
    if group_names:
        groups_lines = (
            "\n### REQUIRED GROUP NAMES\n\n"
            "Use EXACTLY these group names in the generated config (groups, "
            "fgac_policies to_principals, genie ACLs). Do NOT invent new names.\n\n"
        )
        for g in group_names:
            groups_lines += f"  - {g}\n"
        groups_lines += "\n"

    space_names_lines = ""
    if space_names:
        space_names_lines = (
            "\n### REQUIRED GENIE SPACE NAMES\n\n"
            "Use EXACTLY these name(s) as the keys in `genie_space_configs`. "
            "Do NOT rename, merge, or invent alternative titles. "
            "Each name must appear verbatim as a map key.\n\n"
        )
        for name in space_names:
            space_names_lines += f"  - \"{name}\"\n"
        space_names_lines += "\n"

    per_space_instruction = ""
    if per_space_name:
        per_space_instruction = (
            "\n### PER-SPACE GENERATION MODE\n\n"
            f"You are generating config for a SINGLE Genie Space named: \"{per_space_name}\"\n\n"
            "IMPORTANT CONSTRAINTS:\n"
            "- Generate ONLY: genie_space_configs (for this space), tag_assignments "
            "(for the tables listed below), fgac_policies, and masking functions.\n"
            "- Do NOT generate 'groups' — those are established shared governance state.\n"
            "- Do NOT generate 'tag_policies' — those are established shared governance state.\n"
            "- Do NOT generate 'group_members' — those are established shared governance state.\n"
            "- The groups to use in fgac_policies and genie ACLs are listed under "
            "REQUIRED GROUP NAMES above. Use them exactly.\n\n"
        )

    if idx == -1:
        print("WARNING: Could not find '### MY TABLES' in ABAC_PROMPT.md")
        print("  Appending DDL at the end of the prompt instead.\n")
        prompt = template + f"\n\n{per_space_instruction}{groups_lines}{space_names_lines}{cs_lines}\n\n{ddl_text}\n"
    else:
        prompt_body = template[:idx].rstrip()
        user_input = (
            f"\n\n{per_space_instruction}"
            f"{groups_lines}"
            f"{space_names_lines}"
            f"### MY TABLES\n\n"
            f"{cs_lines}\n"
            f"```sql\n{ddl_text}\n```\n"
        )
        prompt = prompt_body + user_input

    return prompt


def extract_code_blocks(response_text: str) -> tuple[str | None, str | None]:
    """Extract the SQL and HCL code blocks from the LLM response."""
    sql_block = None
    hcl_block = None

    blocks = re.findall(r"```(\w*)\n(.*?)```", response_text, re.DOTALL)

    for lang, content in blocks:
        content = content.strip()
        lang_lower = lang.lower()

        if lang_lower == "sql" and sql_block is None:
            sql_block = content
        elif lang_lower in ("hcl", "terraform") and hcl_block is None:
            hcl_block = content
        elif not lang and sql_block is None and "CREATE" in content.upper() and "FUNCTION" in content.upper():
            sql_block = content
        elif not lang and hcl_block is None and "groups" in content and "tag_policies" in content:
            hcl_block = content

    return sql_block, hcl_block


TFVARS_STRIP_KEYS = {
    "databricks_account_id",
    "databricks_client_id",
    "databricks_client_secret",
    "databricks_workspace_id",
    "databricks_workspace_host",
    "uc_catalog_name",
    "uc_schema_name",
    "uc_tables",
}


def sanitize_tfvars_hcl(hcl_block: str) -> str:
    """
    Make AI-generated tfvars easier and safer to use:
    - Strip auth variables (these come from auth.auto.tfvars)
    - Insert section-level explanations and doc links
    """

    # --- Strip auth fields (and common adjacent headers) ---
    stripped_lines: list[str] = []
    for line in hcl_block.splitlines():
        if re.match(r"^\s*#\s*Authentication\b", line, re.IGNORECASE):
            continue
        if re.match(r"^\s*#\s*Databricks\s+Authentication\b", line, re.IGNORECASE):
            continue

        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in TFVARS_STRIP_KEYS:
            continue

        stripped_lines.append(line)

    # Collapse excessive blank lines
    compact: list[str] = []
    last_blank = False
    for line in stripped_lines:
        blank = line.strip() == ""
        if blank and last_blank:
            continue
        compact.append(line)
        last_blank = blank

    text = "\n".join(compact).strip() + "\n"

    # --- Insert explanatory blocks before major sections ---
    docs = (
        "# Docs:\n"
        "# - Governed tags / tag policies: https://docs.databricks.com/en/database-objects/tags.html\n"
        "# - Unity Catalog ABAC overview: https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac\n"
        "# - ABAC policies (masks + filters): https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac/policies\n"
        "# - Row filters + column masks: https://docs.databricks.com/en/tables/row-and-column-filters.html\n"
        "#\n"
    )

    groups_block = (
        "# ----------------------------------------------------------------------------\n"
        "# Groups (business roles)\n"
        "# ----------------------------------------------------------------------------\n"
        "# Keys are group names. Use these to represent business personas (e.g., Analyst,\n"
        "# Researcher, Compliance). These groups are used for workspace onboarding,\n"
        "# Databricks One consumer access, data grants, and optional Genie Space ACLs.\n"
        "#\n"
        + docs
    )

    tag_policies_block = (
        "# ----------------------------------------------------------------------------\n"
        "# Tag policies (governed tags)\n"
        "# ----------------------------------------------------------------------------\n"
        "# Each entry defines a governed tag key and the allowed values. You’ll assign\n"
        "# these tags to tables/columns below, then reference them in FGAC policies.\n"
        "#\n"
        + docs
    )

    tag_assignments_block = (
        "# ----------------------------------------------------------------------------\n"
        "# Tag assignments (classify tables/columns)\n"
        "# ----------------------------------------------------------------------------\n"
        "# Apply governed tags to Unity Catalog objects.\n"
        "# - entity_type: \"tables\" or \"columns\"\n"
        "# - entity_name: fully qualified three-level name\n"
        "#   - table:  \"catalog.schema.Table\"\n"
        "#   - column: \"catalog.schema.Table.Column\"\n"
        "# - Table-level tags are optional; use them to scope column masks or row filters\n"
        "#   to specific tables, or for governance.\n"
        "#\n"
        + docs
    )

    fgac_block = (
        "# ----------------------------------------------------------------------------\n"
        "# FGAC policies (who sees what, and how)\n"
        "# ----------------------------------------------------------------------------\n"
        "# Each entry creates either a COLUMN MASK or ROW FILTER policy.\n"
        "#\n"
        "# Common fields:\n"
        "# - name: logical name for the policy (must be unique)\n"
        "# - policy_type: POLICY_TYPE_COLUMN_MASK | POLICY_TYPE_ROW_FILTER\n"
        "# - catalog: catalog this policy is scoped to\n"
        "# - function_catalog: catalog where the masking UDF lives\n"
        "# - function_schema: schema where the masking UDF lives\n"
        "# - to_principals: list of group names who receive this policy\n"
        "# - except_principals: optional list of groups excluded (break-glass/admin)\n"
        "# - comment: human-readable intent (recommended)\n"
        "#\n"
        "# For COLUMN MASK:\n"
        "# - match_condition: ABAC condition, e.g. hasTagValue('phi_level','full_phi')\n"
        "# - match_alias: the column alias used by the ABAC engine\n"
        "# - function_name: masking UDF name (relative; Terraform prefixes catalog.schema)\n"
        "# - when_condition: (optional) scope to specific tagged tables\n"
        "#\n"
        "# For ROW FILTER:\n"
        "# - when_condition: (optional) scope to specific tagged tables\n"
        "# - function_name: row filter UDF name (relative; must be zero-argument)\n"
        "#\n"
        "# Example \u2014 column mask (mask SSN for analysts, exempt compliance):\n"
        "#   {\n"
        "#     name              = \"mask_ssn_analysts\"\n"
        "#     policy_type       = \"POLICY_TYPE_COLUMN_MASK\"\n"
        "#     to_principals     = [\"Junior_Analyst\", \"Senior_Analyst\"]\n"
        "#     except_principals = [\"Compliance_Officer\"]\n"
        "#     comment           = \"Mask SSN showing only last 4 digits\"\n"
        "#     match_condition   = \"hasTagValue('pii_level', 'highly_sensitive')\"\n"
        "#     match_alias       = \"masked_ssn\"\n"
        "#     function_name     = \"mask_ssn\"\n"
        "#   }\n"
        "#\n"
        "# Example \u2014 row filter (restrict regional staff to their rows):\n"
        "#   {\n"
        "#     name           = \"filter_us_region\"\n"
        "#     policy_type    = \"POLICY_TYPE_ROW_FILTER\"\n"
        "#     to_principals  = [\"US_Region_Staff\"]\n"
        "#     comment        = \"Only show rows where region = US\"\n"
        "#     when_condition = \"hasTagValue('region_scope', 'global')\"\n"
        "#     function_name  = \"filter_by_region_us\"\n"
        "#   }\n"
        "#\n"
        + docs
    )

    def insert_before(pattern: str, block: str, s: str) -> str:
        # Avoid double-inserting if the block already exists nearby
        if block.strip() in s:
            return s
        return re.sub(pattern, block + r"\g<0>", s, count=1, flags=re.MULTILINE)

    text = insert_before(r"^groups\s*=\s*\{", groups_block, text)
    text = insert_before(r"^tag_policies\s*=\s*\[", tag_policies_block, text)
    text = insert_before(r"^tag_assignments\s*=\s*\[", tag_assignments_block, text)
    text = insert_before(r"^fgac_policies\s*=\s*\[", fgac_block, text)

    return text


def call_anthropic(prompt: str, model: str) -> str:
    """Call Claude via the Anthropic API."""
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package not installed. Run:")
        print("  pip install anthropic")
        sys.exit(2)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        print("  export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    print(f"  Calling Anthropic ({model})...")

    message = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def call_openai(prompt: str, model: str) -> str:
    """Call GPT via the OpenAI API."""
    try:
        import openai
    except ImportError:
        print("ERROR: openai package not installed. Run:")
        print("  pip install openai")
        sys.exit(2)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set.")
        print("  export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    client = openai.OpenAI(api_key=api_key)
    print(f"  Calling OpenAI ({model})...")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a Databricks Unity Catalog ABAC expert."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=8192,
    )
    return response.choices[0].message.content


def call_databricks(prompt: str, model: str) -> str:
    """Call a model via the Databricks Foundation Model API."""
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
    except ImportError:
        print("ERROR: databricks-sdk package not installed. Run:")
        print("  pip install databricks-sdk")
        sys.exit(2)

    from databricks.sdk.config import Config

    cfg = Config(http_timeout_seconds=600, product=PRODUCT_NAME, product_version=PRODUCT_VERSION)
    w = WorkspaceClient(config=cfg)
    print(f"  Calling Databricks FMAPI ({model})...")

    response = w.serving_endpoints.query(
        name=model,
        messages=[
            ChatMessage(role=ChatMessageRole.SYSTEM, content="You are a Databricks Unity Catalog ABAC expert."),
            ChatMessage(role=ChatMessageRole.USER, content=prompt),
        ],
        max_tokens=8192,
    )
    return response.choices[0].message.content


PROVIDERS = {
    "databricks": {
        "call": call_databricks,
        "default_model": "databricks-claude-sonnet-4",
    },
    "anthropic": {
        "call": call_anthropic,
        "default_model": "claude-sonnet-4-20250514",
    },
    "openai": {
        "call": call_openai,
        "default_model": "gpt-4o",
    },
}


class Spinner:
    """Simple terminal spinner for long-running operations."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str = "Working"):
        self._message = message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time = 0.0

    def __enter__(self):
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        if self._thread:
            self._thread.join()
        elapsed = time.time() - self._start_time
        sys.stderr.write(f"\r  {self._message} — done ({elapsed:.1f}s)\n")
        sys.stderr.flush()

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            elapsed = time.time() - self._start_time
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stderr.write(f"\r  {frame} {self._message} ({elapsed:.0f}s)")
            sys.stderr.flush()
            i += 1
            self._stop.wait(0.1)


def call_with_retries(call_fn, prompt: str, model: str, max_retries: int) -> str:
    """Call an LLM provider with exponential backoff retries."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            with Spinner(f"Calling LLM (attempt {attempt}/{max_retries})"):
                return call_fn(prompt, model)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = min(2 ** attempt, 60)
                print(f"\n  Attempt {attempt} failed: {e}")
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"\n  Attempt {attempt} failed: {e}")
    raise RuntimeError(f"All {max_retries} attempts failed. Last error: {last_error}")


def autofix_tag_policies(tfvars_path: Path) -> int:
    """Add tag values used in assignments/policies but missing from tag_policies."""
    text = tfvars_path.read_text()

    allowed: dict[str, list[str]] = {}
    for m in re.finditer(
        r'\{\s*key\s*=\s*"([^"]+)"[^}]*?values\s*=\s*\[([^\]]*)\]',
        text,
        re.DOTALL,
    ):
        allowed[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))

    used: dict[str, set[str]] = {}
    for m in re.finditer(r'tag_key\s*=\s*"([^"]+)"[^}]*?tag_value\s*=\s*"([^"]+)"', text, re.DOTALL):
        used.setdefault(m.group(1), set()).add(m.group(2))
    for m in re.finditer(r"hasTagValue\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", text):
        used.setdefault(m.group(1), set()).add(m.group(2))

    added_total = 0
    for key in used:
        if key not in allowed:
            continue
        missing = sorted(used[key] - set(allowed[key]))
        if not missing:
            continue
        old_vals = ", ".join(f'"{v}"' for v in allowed[key])
        new_vals = ", ".join(f'"{v}"' for v in allowed[key] + missing)
        text = text.replace(
            f'values = [{old_vals}]',
            f'values = [{new_vals}]',
            1,
        )
        allowed[key].extend(missing)
        added_total += len(missing)
        for val in missing:
            print(f"  [AUTOFIX] Added '{val}' to tag_policy '{key}'")

    if added_total:
        tfvars_path.write_text(text)

    return added_total


def sanitize_space_key(name: str) -> str:
    """Convert a human-readable space name to a safe directory/Terraform key.

    Mirrors the sanitization applied in Terraform locals:
      'Finance Analytics' -> 'finance_analytics'
      'Exec Dashboard (Q1)' -> 'exec_dashboard_q1'
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def load_groups_from_account_config() -> list[str]:
    """Load existing group names from the shared account abac.auto.tfvars.

    Returns an empty list if the file doesn't exist or has no groups.
    The account config lives at <env_parent>/account/abac.auto.tfvars
    relative to the current working directory.
    """
    account_abac = WORK_DIR.parent / "account" / "abac.auto.tfvars"
    if not account_abac.exists():
        return []
    try:
        import hcl2
        with open(account_abac) as f:
            cfg = hcl2.load(f)
        groups = cfg.get("groups") or {}
        if isinstance(groups, dict) and groups:
            names = list(groups.keys())
            print(f"  Auto-loaded {len(names)} group(s) from account config.")
            return names
    except Exception as e:
        print(f"  WARNING: Could not read account groups from {account_abac}: {e}")
    return []


def bootstrap_per_space_dirs(out_dir: Path, auth_cfg: dict, hcl_text: str) -> None:
    """After a full generation, extract each space's genie_space_configs entry
    and write it to generated/spaces/<key>/abac.auto.tfvars.

    This bootstraps the per-space directory structure so that subsequent
    per-space generation runs can patch individual spaces without touching others.
    """
    try:
        import hcl2
        import io
        parsed = hcl2.load(io.StringIO(hcl_text))
        genie_cfgs: dict = parsed.get("genie_space_configs") or {}
    except Exception as e:
        print(f"  WARNING: Could not parse genie_space_configs for bootstrap: {e}")
        return

    if not genie_cfgs:
        return

    spaces_dir = out_dir / "spaces"
    for space_name, cfg in genie_cfgs.items():
        key = sanitize_space_key(space_name)
        space_dir = spaces_dir / key
        space_dir.mkdir(parents=True, exist_ok=True)

        space_abac = space_dir / "abac.auto.tfvars"
        content = (
            "# ============================================================================\n"
            f"# Per-space config for: {space_name}\n"
            "# Bootstrapped by full generation. Re-run: make generate SPACE=\"" + space_name + "\"\n"
            "# to regenerate only this space without touching others.\n"
            "# ============================================================================\n\n"
            + format_genie_space_configs_hcl({space_name: cfg})
            + "\n"
        )
        space_abac.write_text(content)

    print(
        f"  Bootstrapped {len(genie_cfgs)} per-space dir(s) under {spaces_dir.relative_to(out_dir.parent) if out_dir.parent != out_dir else spaces_dir}"
    )


def run_validation(out_dir: Path) -> bool:
    """Run validate_abac.py on the generated files. Returns True if passed."""
    validator = SCRIPT_DIR / "validate_abac.py"
    resolved_out_dir = out_dir.resolve()
    tfvars_path = resolved_out_dir / "abac.auto.tfvars"
    sql_path = resolved_out_dir / "masking_functions.sql"

    if not validator.exists():
        print("\n  [SKIP] validate_abac.py not found — skipping validation")
        return True

    cmd = [sys.executable, str(validator), str(tfvars_path)]
    if sql_path.exists():
        cmd.append(str(sql_path))

    print("\n  Running validation...\n")
    result = subprocess.run(cmd, cwd=str(WORK_DIR))
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate ABAC configuration from table DDL using AI",
        epilog=(
            "Examples:\n"
            "  python generate_abac.py                       # reads uc_tables from env.auto.tfvars\n"
            "  python generate_abac.py --tables 'prod.sales.*'  # CLI override\n"
            "  python generate_abac.py --promote              # generate + validate + split into account + env data_access + workspace\n"
            "  python generate_abac.py --dry-run              # print prompt without calling LLM\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tables", nargs="+", metavar="CATALOG.SCHEMA.TABLE",
        help="Fully-qualified table refs to fetch from Databricks "
             "(overrides uc_tables in env.auto.tfvars). "
             "E.g. prod.sales.customers or prod.sales.* for all tables in a schema",
    )
    parser.add_argument("--catalog", help="Catalog for masking UDFs (auto-derived from first uc_tables entry if omitted)")
    parser.add_argument("--schema", help="Schema for masking UDFs (auto-derived from first uc_tables entry if omitted)")
    parser.add_argument(
        "--auth-file",
        default=str(DEFAULT_AUTH_FILE),
        help="Path to auth tfvars file (default: auth.auto.tfvars)",
    )
    parser.add_argument(
        "--provider",
        choices=list(PROVIDERS.keys()),
        default="databricks",
        help="LLM provider (default: databricks)",
    )
    parser.add_argument("--model", help="Model name (defaults depend on provider)")
    parser.add_argument(
        "--ddl-dir",
        default="ddl",
        help="Directory containing .sql DDL files (default: ./ddl/)",
    )
    parser.add_argument(
        "--out-dir",
        default="generated",
        help="Output directory for generated files (default: ./generated/)",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Max LLM call attempts with exponential backoff (default: 3)")
    parser.add_argument("--skip-validation", action="store_true", help="Skip running validate_abac.py")
    parser.add_argument("--promote", action="store_true",
        help="Auto-split validated output into account + env data_access + workspace configs")
    parser.add_argument("--dry-run", action="store_true", help="Build the prompt and print it without calling the LLM")
    parser.add_argument(
        "--groups",
        help="Comma-separated group names to use in generated config. "
             "When set, the LLM uses these exact names instead of inventing new ones. "
             "Useful for IDP-synced groups (e.g. --groups 'Finance_Analyst,Clinical_Staff').",
    )
    parser.add_argument(
        "--space",
        metavar="SPACE_NAME",
        help="Name of a single Genie Space to (re)generate. "
             "Fetches only that space's tables, instructs the LLM to skip groups and "
             "tag_policies (shared state), and writes output to generated/spaces/<key>/. "
             "Existing groups are auto-loaded from envs/account/abac.auto.tfvars. "
             "After writing, the assembled generated/abac.auto.tfvars is patched with "
             "the new space's content — other spaces are untouched. "
             "Example: make generate SPACE=\"Finance Analytics\"",
    )

    args = parser.parse_args()

    ddl_dir = Path(args.ddl_dir)
    out_dir = Path(args.out_dir)
    auth_file = Path(args.auth_file)

    print("=" * 60)
    print("  ABAC Configuration Generator")
    if args.space:
        print(f"  Mode: per-space — '{args.space}'")
    print("=" * 60)

    auth_cfg = load_auth_config(auth_file)

    # ── Per-space mode: resolve the target space and redirect out_dir ────────
    # When --space is given, we only generate config for that one space.
    # The output goes to generated/spaces/<key>/ instead of generated/, and
    # after writing we merge the new content back into generated/abac.auto.tfvars.
    target_space_cfg: dict | None = None
    space_key: str = ""

    if args.space:
        genie_spaces_cfg_all = auth_cfg.get("genie_spaces", [])
        for sp in genie_spaces_cfg_all:
            sp_name = sp.get("name") or sp.get("genie_space_id") or ""
            if sp_name == args.space or sanitize_space_key(sp_name) == sanitize_space_key(args.space):
                target_space_cfg = sp
                break

        if target_space_cfg is None:
            print(f"ERROR: No Genie Space named '{args.space}' found in env.auto.tfvars.")
            print("  Available spaces:")
            for sp in genie_spaces_cfg_all:
                print(f"    - {sp.get('name') or sp.get('genie_space_id') or '(unnamed)'}")
            sys.exit(1)

        space_key = sanitize_space_key(
            target_space_cfg.get("name") or target_space_cfg.get("genie_space_id") or args.space
        )
        # Redirect output to the per-space directory
        base_out_dir = Path(args.out_dir)
        out_dir = base_out_dir / "spaces" / space_key
        print(f"  Space key:  {space_key}")
        print(f"  Out dir:    {out_dir}")

        # Auto-load existing groups from the account config so the LLM reuses them
        if not args.groups:
            existing_groups = load_groups_from_account_config()
            if existing_groups:
                args.groups = ",".join(existing_groups)

    catalog = args.catalog or ""
    schema = args.schema or ""

    catalog_schemas: list[tuple[str, str]] | None = None

    # ── Auto-discover tables and config from genie_spaces entries ────────────
    # For spaces where genie_space_id is set but uc_tables is empty, query the
    # Genie Space API to learn what tables and config that space contains.
    # The existing space's genie_space_configs is parsed verbatim from the API
    # (no LLM involvement) and injected into the generated abac.auto.tfvars
    # after the LLM runs, replacing whatever the LLM generated for that space.
    api_genie_configs: dict[str, dict] = {}  # space_name -> config parsed from API

    if not args.tables:
        genie_spaces_cfg = auth_cfg.get("genie_spaces", [])
        # In per-space mode, restrict scanning to only the target space
        if target_space_cfg is not None:
            genie_spaces_cfg = [target_space_cfg]
        if genie_spaces_cfg:
            all_space_tables: list[str] = []
            discovered_from_api: list[str] = []

            for space in genie_spaces_cfg:
                space_tables = space.get("uc_tables") or []
                space_id = space.get("genie_space_id") or ""
                space_name = space.get("name") or space_id

                if space_id:
                    # Always query the API for existing spaces to get config.
                    # Tables are also discovered here if uc_tables is not set.
                    if not space_tables:
                        print(f"\n  Genie Space '{space_name}' has no uc_tables — querying API...")
                    else:
                        print(f"\n  Querying existing Genie Space '{space_name}' for config...")

                    tables, genie_cfg, api_title = fetch_tables_from_genie_space(space_id, auth_cfg)

                    # Use the API title as the canonical name if no name was given
                    effective_name = space_name if space_name != space_id else (api_title or space_id)

                    if not space_tables:
                        all_space_tables.extend(tables)
                        discovered_from_api.extend(tables)
                    else:
                        all_space_tables.extend(space_tables)

                    if genie_cfg:
                        api_genie_configs[effective_name] = genie_cfg
                else:
                    all_space_tables.extend(space_tables)

            # Merge space tables with any top-level uc_tables (dedup, space tables first)
            existing_top = auth_cfg.get("uc_tables") or []
            merged = list(dict.fromkeys(all_space_tables + existing_top))
            if merged:
                auth_cfg["uc_tables"] = merged

            if discovered_from_api:
                print(
                    "\n  Auto-discovered tables from existing Genie Space(s):\n"
                    + "".join(f"    - {t}\n" for t in discovered_from_api)
                    + "\n  NOTE: Add these tables to data_access/env.auto.tfvars so that\n"
                    "  UC grants and masking functions are applied to them as well."
                )

    # Resolve table refs: CLI --tables overrides uc_tables from config
    table_refs = args.tables or auth_cfg.get("uc_tables") or None

    if table_refs:
        source = "--tables CLI" if args.tables else "uc_tables in auth config"
        print(f"  Provider: {args.provider}")
        print(f"  Out dir:  {out_dir}")
        print(f"  Tables:   {', '.join(table_refs)} (from {source})")
        print()

        ddl_text, catalog_schemas = fetch_tables_from_databricks(
            table_refs, auth_cfg,
        )

        if not catalog or not schema:
            if not catalog_schemas:
                print("ERROR: No tables found — cannot determine UDF deployment location.")
                print("  Use --catalog and --schema to specify explicitly.")
                sys.exit(1)
            catalog = catalog or catalog_schemas[0][0]
            schema = schema or catalog_schemas[0][1]

        if catalog_schemas and len(catalog_schemas) > 1:
            print("  Masking UDFs will be deployed to:")
            for cat, sch in catalog_schemas:
                print(f"    - {cat}.{sch}")
        else:
            print(f"  Masking UDFs will be deployed to: {catalog}.{schema}")

        # Save fetched DDLs for inspection
        ddl_dir.mkdir(parents=True, exist_ok=True)
        fetched_path = ddl_dir / "_fetched.sql"
        fetched_path.write_text(ddl_text + "\n")
        print(f"  Fetched DDLs saved to: {fetched_path}")
    else:
        # Legacy mode: read from ddl/ directory
        if not catalog:
            print("ERROR: --catalog is required when using DDL files (no uc_tables configured).")
            sys.exit(1)
        if not schema:
            print("ERROR: --schema is required when using DDL files (no uc_tables configured).")
            sys.exit(1)

        if not ddl_dir.exists():
            print(f"\nERROR: DDL directory '{ddl_dir}' does not exist.")
            print(f"  mkdir -p {ddl_dir}")
            print("  # Then place your CREATE TABLE .sql files there")
            sys.exit(1)

        print(f"  Catalog:  {catalog}")
        print(f"  Schema:   {schema}")
        print(f"  Provider: {args.provider}")
        print(f"  DDL dir:  {ddl_dir}")
        print(f"  Out dir:  {out_dir}")
        print()

        ddl_text = load_ddl_files(ddl_dir)

    group_names = None
    if args.groups:
        group_names = [g.strip() for g in args.groups.split(",") if g.strip()]
        src = "auto-loaded from account config" if target_space_cfg is not None and not args.groups.startswith(args.groups) else "--groups CLI"
        print(f"  Groups:   {', '.join(group_names)} ({src})")

    # Collect space names from config so the LLM uses them verbatim as
    # genie_space_configs keys instead of inventing its own titles.
    configured_space_names: list[str] | None = None
    if not args.tables:
        _spaces = auth_cfg.get("genie_spaces", [])
        if target_space_cfg is not None:
            # Per-space mode: only the target space name matters
            _spaces = [target_space_cfg]
        names = [s.get("name") for s in _spaces if s.get("name")]
        if names:
            configured_space_names = names

    prompt = build_prompt(
        ddl_text,
        catalog_schemas=catalog_schemas,
        group_names=group_names,
        per_space_name=args.space if args.space else None,
        space_names=configured_space_names,
    )

    if args.dry_run:
        print("=" * 60)
        print("  DRY RUN — Prompt that would be sent:")
        print("=" * 60)
        print(prompt)
        sys.exit(0)

    if args.provider == "databricks":
        configure_databricks_env(auth_cfg)

    provider_cfg = PROVIDERS[args.provider]
    model = args.model or provider_cfg["default_model"]
    call_fn = provider_cfg["call"]

    response_text = call_with_retries(call_fn, prompt, model, args.max_retries)

    sql_block, hcl_block = extract_code_blocks(response_text)

    if not sql_block:
        print("\nWARNING: Could not extract SQL code block from the response.")
        print("  The full response will be saved to generated_response.md for manual extraction.\n")
    if not hcl_block:
        print("\nWARNING: Could not extract HCL code block from the response.")
        print("  The full response will be saved to generated_response.md for manual extraction.\n")

    out_dir.mkdir(parents=True, exist_ok=True)

    response_path = out_dir / "generated_response.md"
    response_path.write_text(response_text)
    print(f"\n  Full LLM response saved to: {response_path}")

    tuning_md = f"""# Review & Tune (Before Apply)

This folder contains a **first draft** of:
- `masking_functions.sql` — masking UDFs + row filter functions
- `abac.auto.tfvars` — groups, tags, FGAC policies, and Genie Space config

Before you apply, tune for your business roles, security requirements, and Genie accuracy:

## Checklist — Genie Accuracy (review first)

- **Benchmarks**: Each benchmark question must be **unambiguous and self-contained**. The natural-language question and its ground-truth SQL must agree on the exact scope — e.g., "What is the average risk score for **active** customers?" (not "What is the average customer risk score?"). Run benchmarks in the Genie UI after apply to verify accuracy.
- **SQL filters**: Do the default WHERE clauses match your business definitions? (e.g., "active customers" = `CustomerStatus = 'Active'`, "completed transactions" = `TransactionStatus = 'Completed'`). These filters guide Genie's SQL generation.
- **SQL measures**: Are the standard metrics correct? (e.g., total revenue = `SUM(Amount)`, average risk = `AVG(RiskScore)`).
- **SQL expressions**: Are the computed dimensions useful? (e.g., transaction year, age bucket).
- **Join specs**: Do the join conditions between tables use the correct keys? Incorrect joins cause wrong results across all multi-table queries.
- **Instructions**: Does the instruction text define business defaults (e.g., "customer" means active by default) and domain conventions (date handling, metric calculations)?

## Checklist — ABAC & Masking

- **Groups and personas**: Do the groups map to real business roles?
- **Sensitive columns**: Are the right columns tagged (PII/PHI/financial/etc.)?
- **Masking behavior**: Are you using the right approach (partial, redact, hash) per sensitivity and use case?
- **Row filters and exceptions**: Are filters too broad/strict? Are exceptions minimal and intentional?

## Checklist — Genie Space Metadata

- **Genie title & description**: Does the AI-generated title/description accurately represent the space?
- **Genie sample questions**: Do the sample questions reflect what business users will ask?
- **Validate before apply**: Run validation before `terraform apply`.

## Suggested workflow

1. Review and edit `masking_functions.sql` and `abac.auto.tfvars` in `generated/`.
2. Validate after each change:
   ```bash
   make validate-generated
   ```
3. When ready, apply (validates again, promotes shared account + workspace config, then runs terraform):
   ```bash
   make apply
   ```

"""

    tuning_path = out_dir / "TUNING.md"
    tuning_path.write_text(tuning_md)
    print(f"  Tuning checklist written to: {tuning_path}")

    if sql_block:
        all_cs = catalog_schemas if catalog_schemas else [(catalog, schema)]
        targets = ", ".join(f"{c}.{s}" for c, s in all_cs)
        sql_header = (
            "-- ============================================================================\n"
            "-- GENERATED MASKING FUNCTIONS (FIRST DRAFT)\n"
            "-- ============================================================================\n"
            f"-- Target(s): {targets}\n"
            "-- Next: review generated/TUNING.md, tune if needed, then run this SQL.\n"
            "-- ============================================================================\n\n"
        )

        final_sql = sql_header + sql_block
        sql_path = out_dir / "masking_functions.sql"
        sql_path.write_text(final_sql + "\n")
        print(f"  masking_functions.sql written to: {sql_path}")
        print(f"    Target schemas: {targets}")

    if hcl_block:
        hcl_header = (
            "# ============================================================================\n"
            "# GENERATED ABAC CONFIG (FIRST DRAFT)\n"
            "# ============================================================================\n"
            "# NOTE: Authentication comes from auth.auto.tfvars, environment from env.auto.tfvars.\n"
            "# Tune the following before apply:\n"
            "# - groups (business roles)\n"
            "# - tag_assignments (what data is considered sensitive)\n"
            "# - fgac_policies (who sees what, and how)\n"
            "# Then validate before promoting into shared account + workspace config:\n"
            "#   python validate_abac.py generated/abac.auto.tfvars generated/masking_functions.sql\n"
            "# ============================================================================\n\n"
        )

        hcl_block = sanitize_tfvars_hcl(hcl_block)

        # ── Inject API-parsed genie_space_configs for existing spaces ─────────
        # The LLM generates genie_space_configs from DDL, but for spaces with a
        # genie_space_id the UI config is authoritative. Replace the LLM-generated
        # block with the verbatim parse from the Genie Space API.
        if api_genie_configs:
            hcl_block = remove_hcl_top_level_block(hcl_block, "genie_space_configs")
            injected_hcl = (
                "\n# genie_space_configs parsed verbatim from the existing Genie Space(s).\n"
                "# Edit here to manage space config as code; make apply pushes changes back.\n"
                + format_genie_space_configs_hcl(api_genie_configs)
            )
            hcl_block = hcl_block.rstrip() + "\n" + injected_hcl + "\n"
            print(
                f"  Injected genie_space_configs from Genie API for: "
                f"{', '.join(api_genie_configs)}"
            )

        tfvars_path = out_dir / "abac.auto.tfvars"
        tfvars_path.write_text(hcl_header + hcl_block + "\n")
        print(f"  abac.auto.tfvars written to: {tfvars_path}")

        n_fixed = autofix_tag_policies(tfvars_path)
        if n_fixed:
            print(f"  Auto-fixed {n_fixed} missing tag_policy value(s)")

        # ── Per-space mode: bootstrap per-space dir, then merge into assembled ──
        if target_space_cfg is not None and space_key:
            # The per-space dir is already out_dir; merge its content into
            # the assembled generated/abac.auto.tfvars one level up.
            assembled_dir = out_dir.parent.parent  # generated/spaces/<key>/../.. = generated/
            merge_script = SCRIPT_DIR / "scripts" / "merge_space_configs.py"
            subprocess.check_call(
                [sys.executable, str(merge_script), str(assembled_dir), space_key]
            )

        # ── Full generation: bootstrap per-space dirs from the assembled output ─
        elif target_space_cfg is None and not args.space:
            bootstrap_per_space_dirs(out_dir, auth_cfg, hcl_block)

    # In per-space mode, validate the assembled generated/ dir (what apply uses),
    # not the per-space subdirectory.
    validation_dir = out_dir.parent.parent if (target_space_cfg is not None and space_key) else out_dir

    if sql_block and hcl_block and not args.skip_validation:
        passed = run_validation(validation_dir)
        if not passed:
            print("\n  Validation found errors. Review the output above and fix before running terraform apply.")
            sys.exit(1)

        if args.promote and passed:
            if WORK_DIR.name in {"account", "data_access"}:
                print("\n  [SKIP] --promote requires a workspace env directory (e.g. envs/dev).")
            elif target_space_cfg is not None and space_key:
                print("\n  [SKIP] --promote is not supported with --space. Run make apply after reviewing.")
            else:
                split_script = SCRIPT_DIR / "scripts" / "split_abac_config.py"
                account_path = WORK_DIR.parent / "account" / "abac.auto.tfvars"
                data_access_dir = WORK_DIR / "data_access"
                data_access_dir.mkdir(parents=True, exist_ok=True)
                workspace_path = WORK_DIR / "abac.auto.tfvars"
                subprocess.check_call(
                    [
                        sys.executable,
                        str(split_script),
                        str(tfvars_path),
                        str(account_path),
                        str(data_access_dir / "abac.auto.tfvars"),
                        str(workspace_path),
                    ]
                )
                if sql_block:
                    shutil.copy2(sql_path, data_access_dir / "masking_functions.sql")
                print(
                    "\n  Promoted into shared account + env-scoped data_access + workspace configs."
                )
    elif not args.skip_validation and (not sql_block or not hcl_block):
        print("\n  [SKIP] Validation skipped — could not extract both code blocks.")
        print(f"  Review {response_path} and manually extract the files.")

    print("\n" + "=" * 60)
    print("  Done!")
    if sql_block and hcl_block:
        if args.promote:
            env_name = Path.cwd().name
            env_suffix = f" ENV={env_name}" if env_name != "dev" else ""
            print("  Files promoted into the current env workspace. Next step:")
            print(f"    make apply{env_suffix}   (or: terraform init && terraform apply -parallelism=1)")
        elif args.space:
            env_name = Path.cwd().name
            env_suffix = f" ENV={env_name}" if env_name != "dev" else ""
            assembled_dir = out_dir.parent.parent
            print(f"  Per-space output: {out_dir.resolve()}")
            print(f"  Merged into:      {(assembled_dir / 'abac.auto.tfvars').resolve()}")
            print("  Next steps:")
            print(f"    1. Review generated/spaces/{space_key}/abac.auto.tfvars  (space-specific draft)")
            print(f"    2. Review generated/abac.auto.tfvars  (assembled — what apply uses)")
            print(f"    3. make validate-generated{env_suffix}")
            print(f"    4. make apply{env_suffix}")
        else:
            env_name = Path.cwd().name
            env_suffix = f" ENV={env_name}" if env_name != "dev" else ""
            print("  Next steps:")
            print(f"    1. Review the tuning checklist:")
            print(f"       {out_dir.resolve()}/TUNING.md")
            print(f"    2. Review and tune generated files:")
            print(f"       {out_dir.resolve()}/masking_functions.sql")
            print(f"       {out_dir.resolve()}/abac.auto.tfvars")
            print(f"    3. make validate-generated{env_suffix}   (check your changes anytime)")
            print(f"    4. make apply{env_suffix}   (validates, splits shared account/workspace config, runs terraform apply)")
    print("=" * 60)


if __name__ == "__main__":
    main()
