#!/usr/bin/env python3
"""Remap a generated draft from one env's catalog namespace to another.

Simple catalog substitution: only the catalog name changes between environments.
Schema and table names are assumed stable (Databricks best practice).

Usage:
  python scripts/remap_generated_config.py \\
    <source_abac> <source_sql> <src_catalog> <dest_catalog> <out_abac> <out_sql>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def remap_hcl(text: str, src_catalog: str, dest_catalog: str) -> str:
    """Substitute all catalog references in HCL text.

    Handles:
    - Catalog-prefixed table refs:  "src_catalog.schema.table"  -> "dest_catalog.schema.table"
    - Standalone catalog fields:    catalog = "src_catalog"     -> catalog = "dest_catalog"
    - function_catalog fields:      function_catalog = "src..."  -> function_catalog = "dest..."
    """
    # Replace catalog-prefixed table refs (e.g. in entity_name, inline strings)
    result = text.replace(f"{src_catalog}.", f"{dest_catalog}.")

    # Replace standalone catalog field assignments without a trailing dot
    # (e.g. catalog = "src_catalog" — not already caught by the prefix replace above)
    for field in ("catalog", "function_catalog"):
        result = re.sub(
            rf'(^\s*{re.escape(field)}\s*=\s*"){re.escape(src_catalog)}(")',
            rf'\g<1>{dest_catalog}\g<2>',
            result,
            flags=re.MULTILINE,
        )

    return result


def remap_sql(text: str, src_catalog: str, dest_catalog: str) -> str:
    """Substitute catalog references in masking SQL.

    Handles USE CATALOG statements and catalog-prefixed identifiers.
    """
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(
            r"^(USE\s+CATALOG\s+)([^;\s]+)(;?)$",
            stripped,
            re.IGNORECASE,
        )
        if match:
            prefix, catalog, suffix = match.groups()
            catalog = catalog.rstrip(";")
            new_catalog = dest_catalog if catalog == src_catalog else catalog
            lines.append(f"{prefix}{new_catalog}{suffix}")
        else:
            lines.append(line.replace(f"{src_catalog}.", f"{dest_catalog}."))

    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) != 7:
        print(
            "Usage: python scripts/remap_generated_config.py "
            "<source_abac> <source_sql> <src_catalog> "
            "<dest_catalog> <out_abac> <out_sql>"
        )
        sys.exit(1)

    source_abac = Path(sys.argv[1])
    source_sql = Path(sys.argv[2])
    src_catalog = sys.argv[3]
    dest_catalog = sys.argv[4]
    out_abac = Path(sys.argv[5])
    out_sql = Path(sys.argv[6])

    for path in (source_abac, source_sql):
        if not path.exists():
            print(f"ERROR: Required file not found: {path}")
            sys.exit(1)

    if not src_catalog:
        print("ERROR: src_catalog is empty. Set uc_catalog in the source env.auto.tfvars.")
        sys.exit(1)
    if not dest_catalog:
        print("ERROR: dest_catalog is empty. Provide DEST_CATALOG=<catalog>.")
        sys.exit(1)

    out_abac.parent.mkdir(parents=True, exist_ok=True)
    out_sql.parent.mkdir(parents=True, exist_ok=True)

    out_abac.write_text(remap_hcl(source_abac.read_text(), src_catalog, dest_catalog))
    out_sql.write_text(remap_sql(source_sql.read_text(), src_catalog, dest_catalog))

    if src_catalog == dest_catalog:
        print(f"  Catalog unchanged: {src_catalog} (same-catalog remap is a no-op)")
    else:
        print(f"  Catalog remap: {src_catalog} -> {dest_catalog}")
    print(f"  Wrote remapped generated config: {out_abac}")
    print(f"  Wrote remapped masking SQL:      {out_sql}")


if __name__ == "__main__":
    main()
